"""Auth per Magic-Link (passwortlos) + JWT."""
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from .. import i18n
from ..config import settings
from ..database import get_db
from ..deps import bearer, get_current_user
from ..models import LoginAttempt, MagicLink, RegisterAttempt, Role, User
from ..schemas import (
    AccountDeleteRequest,
    MagicLinkRequest,
    MagicLinkResponse,
    PasswordChangeRequest,
    PasswordLoginRequest,
    PasswordRegisterRequest,
    SupabaseVerifyRequest,
    TokenResponse,
    UserOut,
    UserUpdate,
    VerifyRequest,
)
from ..security import (
    create_access_token,
    decode_access_token,
    hash_password,
    hash_token,
    new_magic_token,
    verify_password,
)
from ..services import alert
from ..services.mailer import send_magic_link
from ..services.supabase_auth import (
    SupabaseMailFailed,
    SupabaseRateLimited,
    get_verified_email,
    send_magic_link_via_supabase,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

LINK_TTL_MINUTES = 30
# Rate-Limit: max. Link-Anfragen pro E-Mail im Zeitfenster (Spam-/Abuse-Schutz)
RATE_LIMIT_MAX = 5
RATE_LIMIT_WINDOW_MINUTES = 15
# Brute-Force-Schutz Passwort-Login: max. Fehlversuche pro E-Mail im Zeitfenster
LOGIN_FAIL_MAX = 8
LOGIN_FAIL_WINDOW_MINUTES = 15
# Registrierungs-Bremse: max. neue Konten pro IP und Tag. Grosszuegig genug
# fuer Familien und ein Schulzimmer hinter derselben IP, aber ein Skript kann
# sich keine hunderten Gratis-Token-Konten farmen.
REGISTER_IP_MAX_PER_DAY = 15

log = logging.getLogger("schrittweise.auth")


def _client_ip(request: Request) -> str:
    """Client-IP hinter dem Vercel-Proxy (erster Eintrag in X-Forwarded-For)."""
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()[:64]
    return (request.client.host if request.client else "unbekannt")[:64]


# Dummy-Hash für konstante Antwortzeit bei unbekannter E-Mail (kein User-Enumeration-Timing)
_DUMMY_HASH = hash_password("nur-fuer-timing-vergleich")


def _deliver_login_mail(db: Session, email: str) -> None:
    """Erstellt einen Login-/Bestaetigungslink und verschickt ihn (wirft bei Fehler)."""
    token = new_magic_token()
    db.add(MagicLink(
        email=email,
        token=hash_token(token),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=LINK_TTL_MINUTES),
    ))
    db.commit()
    if settings.supabase_auth_enabled:
        send_magic_link_via_supabase(email, f"{settings.frontend_base_url}/login/verify")
    elif settings.smtp_enabled:
        send_magic_link(email, f"{settings.frontend_base_url}/login/verify?token={token}")


@router.post("/register", response_model=TokenResponse)
def register_password(payload: PasswordRegisterRequest, request: Request, db: Session = Depends(get_db)):
    """Konto mit E-Mail + Passwort anlegen und direkt einloggen."""
    # Honeypot: das unsichtbare Feld fuellt nur ein Bot aus.
    if payload.website:
        log.warning("Registrierung mit gefuelltem Honeypot abgewiesen (IP %s)", _client_ip(request))
        raise HTTPException(status.HTTP_400_BAD_REQUEST, i18n.t(i18n.lang_of(request=request), "Ungültige Anfrage.", "Invalid request."))

    if not payload.terms_accepted:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            i18n.t(i18n.lang_of(request=request), "Bitte akzeptiere die AGB und die Datenschutzerklärung.", "Please accept the terms of service and the privacy policy."),
        )

    # Bremse gegen Konto-Farmen: jedes Konto erhaelt Gratis-Tokens (echte Kosten).
    ip = _client_ip(request)
    day_start = datetime.now(timezone.utc) - timedelta(hours=24)
    recent = db.scalar(
        select(func.count(RegisterAttempt.id)).where(
            RegisterAttempt.ip == ip, RegisterAttempt.created_at >= day_start
        )
    ) or 0
    if recent >= REGISTER_IP_MAX_PER_DAY:
        log.warning("Registrierungs-Limit erreicht: %s Konten in 24h von IP %s", recent, ip)
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            i18n.t(i18n.lang_of(request=request), "Von diesem Anschluss wurden heute schon viele Konten erstellt – versuch es morgen nochmal.", "Many accounts were already created from this connection today – please try again tomorrow."),
        )

    email = payload.email.lower().strip()
    user = db.scalar(select(User).where(User.email == email))

    # Auch ein Konto OHNE Passwort (Magic-Link-Zeit) gehoert schon jemandem:
    # wer nur die E-Mail kennt, darf nicht per «Registrieren» ein Passwort
    # setzen und dessen Aufgaben, Chats und Noten lesen. Der Weg hinein ist
    # «Passwort vergessen» - dort beweist der Mail-Link den Besitz.
    if user is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, i18n.t(i18n.lang_of(request=request), "Konto existiert bereits – wechsle zu «Anmelden» oder «Passwort vergessen».", "Account already exists – switch to “Sign in” or “Forgot password”.")
        )

    if user is None:
        role = Role.parent if payload.role == "parent" else Role.student
        display = (payload.display_name or email.split("@")[0]).strip()[:80]
        user = User(
            email=email,
            display_name=display,
            role=role,
            grade_level=payload.grade_level,
            language=i18n.norm(payload.language),
        )
        db.add(user)

    user.password_hash = hash_password(payload.password)
    user.terms_accepted_at = datetime.now(timezone.utc)
    user.email_verified = False  # Besitz-Nachweis erst per Link-Klick
    # Registrierung fuers IP-Limit zaehlen; alte Eintraege gleich aufraeumen.
    db.execute(delete(RegisterAttempt).where(RegisterAttempt.created_at < day_start))
    db.add(RegisterAttempt(ip=ip))
    db.commit()
    db.refresh(user)

    # Bestaetigungs-Mail direkt mitschicken (best effort – Registrierung
    # scheitert NIE am Mailversand; der Banner in der App kann neu senden).
    if settings.supabase_auth_enabled or settings.smtp_enabled:
        try:
            _deliver_login_mail(db, email)
        except Exception as exc:
            log.warning("Bestätigungs-Mail bei Registrierung fehlgeschlagen (%s)", email)
            reason = getattr(exc, "reason", None) or f"{type(exc).__name__}: {exc}"
            alert.notify("mail", f"Bestätigungs-Mail an {email} nicht verschickt. {reason}", key="register")

    access = create_access_token(user.id, user.role.value, token_version=user.token_version or 0)
    return TokenResponse(access_token=access, user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenResponse)
def login_password(payload: PasswordLoginRequest, request: Request, db: Session = Depends(get_db)):
    email = payload.email.lower().strip()

    # Brute-Force-Bremse: zu viele Fehlversuche fuer diese E-Mail -> 429,
    # noch BEVOR das Passwort geprueft wird (auch ein korrektes zaehlt dann nicht).
    fail_window = datetime.now(timezone.utc) - timedelta(minutes=LOGIN_FAIL_WINDOW_MINUTES)
    fails = db.scalar(
        select(func.count(LoginAttempt.id)).where(
            LoginAttempt.email == email, LoginAttempt.created_at >= fail_window
        )
    ) or 0
    if fails >= LOGIN_FAIL_MAX:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            i18n.t(i18n.lang_of(request=request), "Zu viele fehlgeschlagene Versuche – warte 15 Minuten und versuch es dann nochmal.", "Too many failed attempts – wait 15 minutes and try again."),
        )

    user = db.scalar(select(User).where(User.email == email))

    stored = user.password_hash if user is not None and user.password_hash else _DUMMY_HASH
    ok = verify_password(payload.password, stored)
    if user is None or not user.password_hash or not ok:
        # Fehlversuch protokollieren; alte Eintraege gleich mit aufraeumen,
        # damit die Tabelle nicht unbegrenzt waechst.
        db.execute(delete(LoginAttempt).where(LoginAttempt.created_at < fail_window))
        db.add(LoginAttempt(email=email))
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, i18n.t(i18n.lang_of(request=request), "E-Mail oder Passwort falsch.", "Email or password is incorrect."))

    # Erfolg: Fehlversuchs-Zaehler dieser E-Mail zuruecksetzen
    if fails:
        db.execute(delete(LoginAttempt).where(LoginAttempt.email == email))
        db.commit()

    access = create_access_token(user.id, user.role.value, token_version=user.token_version or 0)
    return TokenResponse(access_token=access, user=UserOut.model_validate(user))


@router.post("/change-password", response_model=TokenResponse)
def change_password(
    payload: PasswordChangeRequest,
    user: User = Depends(get_current_user),
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
):
    """Neues Passwort setzen. Ohne aktuelles Passwort nur, wenn der Login per
    Mail-Link kam (Passwort-vergessen-Flow) oder noch kein Passwort existiert."""
    token_payload = decode_access_token(creds.credentials) if creds else None
    via_email = bool(token_payload) and token_payload.get("via") == "email"

    if user.password_hash and not via_email:
        if not payload.current_password or not verify_password(
            payload.current_password, user.password_hash
        ):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Das aktuelle Passwort stimmt nicht."
            )

    user.password_hash = hash_password(payload.new_password)
    # Alle bestehenden Sitzungen aussperren (gestohlene/alte Tokens werden ungueltig).
    user.token_version = (user.token_version or 0) + 1
    db.commit()
    db.refresh(user)
    # Frisches Token ausgeben (via=password), damit die Session normal weiterlaeuft.
    access = create_access_token(user.id, user.role.value, token_version=user.token_version or 0)
    return TokenResponse(access_token=access, user=UserOut.model_validate(user))


@router.post("/request-link", response_model=MagicLinkResponse)
def request_link(payload: MagicLinkRequest, db: Session = Depends(get_db)):
    email = payload.email.lower().strip()

    window_start = datetime.now(timezone.utc) - timedelta(minutes=RATE_LIMIT_WINDOW_MINUTES)
    recent = db.scalar(
        select(func.count(MagicLink.id)).where(
            MagicLink.email == email, MagicLink.created_at >= window_start
        )
    ) or 0
    if recent >= RATE_LIMIT_MAX:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Zu viele Anfragen – warte ein paar Minuten und versuch es nochmal.",
        )

    user = db.scalar(select(User).where(User.email == email))

    # KEINE Konto-Anlage ueber diesen Pfad: Registrieren geht nur ueber
    # /register (dort greifen AGB-Zustimmung, Honeypot und IP-Limit).
    # Dieser Endpoint ist nur noch «Passwort vergessen» fuer BESTEHENDE Konten.
    if user is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Kein Konto mit dieser E-Mail – registriere dich über «Neu hier».",
        )

    token = new_magic_token()
    # Nur der Hash landet in der DB – ein DB-Leak erlaubt keinen Login.
    db.add(
        MagicLink(
            email=email,
            token=hash_token(token),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=LINK_TTL_MINUTES),
        )
    )
    db.commit()

    link = f"{settings.frontend_base_url}/login/verify?token={token}"

    # Bevorzugt: Login-Mail über Supabase Auth (kein eigener SMTP-Zugang nötig).
    # Der Rückweg läuft dann über /api/auth/verify-supabase statt über `token`.
    if settings.supabase_auth_enabled:
        try:
            send_magic_link_via_supabase(email, f"{settings.frontend_base_url}/login/verify")
            return MagicLinkResponse(sent=True, message="Wir haben dir einen Link geschickt.")
        except SupabaseRateLimited:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Zu viele Login-Mails in kurzer Zeit – warte ein paar Minuten und versuch es nochmal.",
            )
        except SupabaseMailFailed as exc:
            alert.notify("mail", f"Login-Mail an {email} nicht verschickt. {exc.reason}", key="supabase")
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Mailversand momentan nicht möglich – versuch es in ein paar Minuten nochmal.",
            )
        except Exception as exc:
            alert.notify("mail", f"Login-Mail an {email} nicht verschickt: {type(exc).__name__}: {exc}", key="supabase")
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Mailversand momentan nicht möglich – versuch es in ein paar Minuten nochmal.",
            )

    if settings.smtp_enabled:
        try:
            if send_magic_link(email, link):
                return MagicLinkResponse(sent=True, message="Wir haben dir einen Link geschickt.")
        except Exception as exc:
            alert.notify("mail", f"Login-Mail an {email} nicht verschickt (SMTP): {type(exc).__name__}: {exc}", key="smtp")
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Mailversand momentan nicht möglich – versuch es in ein paar Minuten nochmal.",
            )

    # Dev-Modus ohne Mailserver: Link direkt zurueckgeben, damit Login moeglich ist.
    if settings.magic_link_dev_return:
        return MagicLinkResponse(
            sent=False,
            message="Dev-Modus: Login-Link direkt zurueckgegeben (kein Mailversand konfiguriert).",
            dev_login_url=link,
            dev_token=token,
        )
    # Produktion ohne SMTP: klarer Fehler statt stiller Sackgasse
    raise HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "Login momentan nicht möglich (kein Mailversand konfiguriert). Bitte den Betreiber informieren.",
    )


@router.post("/verify", response_model=TokenResponse)
def verify(payload: VerifyRequest, db: Session = Depends(get_db)):
    ml = db.scalar(select(MagicLink).where(MagicLink.token == hash_token(payload.token)))
    if ml is None or ml.used:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Link ungültig oder bereits benutzt.")
    expires = ml.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Link abgelaufen. Fordere einen neuen an.")

    user = db.scalar(select(User).where(User.email == ml.email))
    if user is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Konto nicht gefunden.")

    # Einmal-Nutzung atomar: nur der Request, der used False->True dreht, gewinnt.
    # Verhindert, dass zwei parallele Verifikationen desselben Links beide ein Token bekommen.
    marked = db.execute(
        update(MagicLink).where(MagicLink.id == ml.id, MagicLink.used.is_(False)).values(used=True)
    )
    if marked.rowcount != 1:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Link ungültig oder bereits benutzt.")
    # Link-Klick beweist den Besitz der Mailbox
    user.email_verified = True
    db.commit()

    access = create_access_token(user.id, user.role.value, via="email", token_version=user.token_version or 0)
    return TokenResponse(access_token=access, user=UserOut.model_validate(user))


@router.post("/verify-supabase", response_model=TokenResponse)
def verify_supabase(payload: SupabaseVerifyRequest, db: Session = Depends(get_db)):
    """Tauscht ein Supabase-Access-Token (aus der Login-Mail) gegen das App-JWT."""
    email = get_verified_email(payload.access_token)
    if email is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Link ungültig oder abgelaufen. Fordere einen neuen an."
        )
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Kein Konto mit dieser E-Mail – registriere dich zuerst über «Neu hier».",
        )
    # Supabase hat die E-Mail verifiziert -> Besitz bewiesen
    if not user.email_verified:
        user.email_verified = True
        db.commit()
    access = create_access_token(user.id, user.role.value, via="email", token_version=user.token_version or 0)
    return TokenResponse(access_token=access, user=UserOut.model_validate(user))


@router.post("/delete-account", status_code=204)
def delete_account(
    payload: AccountDeleteRequest,
    user: User = Depends(get_current_user),
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
):
    """Konto samt Daten endgültig löschen (Datenschutz-Selbstbedienung).

    Bestätigung per Passwort; kam der Login über einen Mail-Link (via=email),
    ist der Besitz der Mailbox bereits bewiesen. Zahlungsbelege bleiben bei
    Stripe erhalten (Buchhaltung) – lokal wird alles entfernt."""
    token_payload = decode_access_token(creds.credentials) if creds else None
    via_email = bool(token_payload) and token_payload.get("via") == "email"
    if user.password_hash and not via_email:
        if not payload.password or not verify_password(payload.password, user.password_hash):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Das Passwort stimmt nicht.")
    if user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Betreiber-Konten können sich nicht selbst löschen.")

    from ..models import (
        ApiUsage, Attempt, Exam, ExamItem, Exercise, Feedback, Grade, Message,
        ParentLink, Payment, ProgressAggregate, TokenAdjustment, Topic,
        UploadedImage,
    )

    uid = user.id
    email = user.email
    attempt_ids = select(Attempt.id).where(Attempt.user_id == uid)
    exercise_ids = select(Exercise.id).where(Exercise.user_id == uid)
    db.execute(delete(Message).where(Message.attempt_id.in_(attempt_ids)))
    db.execute(delete(Attempt).where(Attempt.user_id == uid))
    # Kosten-Statistik bleibt (anonymisiert) – Personenbezug wird entfernt
    db.execute(update(ApiUsage).where(ApiUsage.user_id == uid).values(user_id=None))
    db.execute(update(ApiUsage).where(ApiUsage.exercise_id.in_(exercise_ids)).values(exercise_id=None))
    db.execute(delete(Exercise).where(Exercise.user_id == uid))
    # Noten und Probepruefungen haengen mit NOT-NULL-Fremdschluesseln an
    # users/topics/exams – ohne diese Zeilen brach die Loeschung auf Postgres
    # mit einer Fremdschluessel-Verletzung ab (SQLite prueft das nur mit
    # eingeschaltetem PRAGMA, siehe tests/conftest.py).
    exam_ids = select(Exam.id).where(Exam.user_id == uid)
    db.execute(delete(Grade).where(Grade.user_id == uid))
    db.execute(delete(ExamItem).where(ExamItem.exam_id.in_(exam_ids)))
    db.execute(delete(Exam).where(Exam.user_id == uid))
    db.execute(delete(Topic).where(Topic.user_id == uid))
    db.execute(delete(ProgressAggregate).where(ProgressAggregate.user_id == uid))
    db.execute(delete(ParentLink).where(ParentLink.student_id == uid))
    db.execute(update(ParentLink).where(ParentLink.parent_id == uid).values(parent_id=None))
    db.execute(delete(Feedback).where(Feedback.user_id == uid))
    db.execute(delete(UploadedImage).where(UploadedImage.user_id == uid))
    db.execute(delete(Payment).where(Payment.user_id == uid))
    # Guthaben-Korrekturen: Zeilen des Nutzers loeschen; wo er (frueher) als
    # Admin gebucht hat, nur den Personenbezug entfernen – sonst blockiert der
    # Fremdschluessel die Loeschung auf Postgres.
    db.execute(delete(TokenAdjustment).where(TokenAdjustment.user_id == uid))
    db.execute(update(TokenAdjustment).where(TokenAdjustment.admin_id == uid).values(admin_id=None))
    db.execute(delete(MagicLink).where(MagicLink.email == email))
    db.execute(delete(LoginAttempt).where(LoginAttempt.email == email))
    db.delete(user)
    db.commit()
    log.info("Konto geloescht (User-ID %s)", uid)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return UserOut.model_validate(user)


@router.patch("/me", response_model=UserOut)
def update_me(payload: UserUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # exclude_none: explizites {"display_name": null} darf keine NOT-NULL-Spalte auf None setzen (500).
    for field, value in payload.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return UserOut.model_validate(user)
