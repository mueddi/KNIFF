"""Datenmodell (Kern) fuer Kniff.

Privacy by Design:
  * ``messages`` (Transkripte) haengen an ``attempts`` und sind ausschliesslich
    aus der Schueler-Rolle lesbar. Die Eltern-Endpoints greifen NIE auf diese
    Tabelle zu.
  * ``progress_aggregates`` ist eine SEPARATE Tabelle, die nur grobe Aggregate
    haelt. Nur sie wird der Eltern-Rolle exponiert.
"""
from __future__ import annotations

import enum
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Role(str, enum.Enum):
    student = "student"
    parent = "parent"


class Plan(str, enum.Enum):
    free = "free"
    token = "token"
    school = "school"


class AttemptStatus(str, enum.Enum):
    active = "active"
    solved = "solved"
    abandoned = "abandoned"


class MessageRole(str, enum.Enum):
    tutor = "tutor"
    student = "student"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    # Anzeigename statt Klarname (Privacy)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.student, nullable=False)
    grade_level: Mapped[str | None] = mapped_column(String(40), nullable=True)  # z.B. "2. Oberstufe"
    language: Mapped[str] = mapped_column(String(8), default="de", nullable=False)

    # Passwort-Login (scrypt-Hash); NULL bei Alt-Konten aus der Magic-Link-Zeit
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Abo / Kontingent: token_balance in Tokens (1 Token = 1 Rappen verrechnete
    # KI-Leistung); dazu das monatliche Gratis-Kontingent mit Monats-Marke.
    plan: Mapped[Plan] = mapped_column(Enum(Plan), default=Plan.free, nullable=False)
    token_balance: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    free_used_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Monatszaehler: mit Kniff Plus zaehlt er den GESAMTEN Monatsverbrauch
    # (Fair-Use), nicht nur den Gratis-Anteil - der Name ist historisch.
    free_month: Mapped[str | None] = mapped_column(String(7), nullable=True)  # "YYYY-MM"

    # Kniff Plus (Stripe-Abo). Plus ist aktiv, solange abo_bis in der Zukunft
    # liegt - kein neuer Plan-Wert, damit das Postgres-Enum unangetastet bleibt.
    stripe_customer_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    abo_bis: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    abo_gekuendigt: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    abo_intervall: Mapped[str | None] = mapped_column(String(8), nullable=True)  # "monat" | "jahr"

    # Privacy-Schalter: gibt der/die Schueler:in Aggregate fuer Eltern frei?
    share_with_parents: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Betreiber-Konto: darf die Aufgaben-Bibliothek verwalten
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Zeitpunkt der AGB-/Datenschutz-Zustimmung bei der Registrierung
    terms_accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Passwort-Aenderung erhoeht die Version -> alle alten Tokens sofort ungueltig
    token_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # E-Mail-Besitz per Link-Klick bewiesen (Bestandskonten per Migration TRUE)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    topics: Mapped[list[Topic]] = relationship(back_populates="user", cascade="all, delete-orphan")
    exercises: Mapped[list[Exercise]] = relationship(back_populates="user", cascade="all, delete-orphan")


class MagicLink(Base):
    """Einmal-Token fuer passwortlosen Login (Magic-Link)."""
    __tablename__ = "magic_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    token: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)


class LoginAttempt(Base):
    """Fehlgeschlagene Passwort-Logins pro E-Mail – Grundlage fuer das Rate-Limit
    (Brute-Force-Schutz). Erfolgreicher Login loescht die Eintraege der E-Mail."""
    __tablename__ = "login_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)


class RegisterAttempt(Base):
    """Erfolgreiche Registrierungen pro IP – Bremse gegen Gratis-Token-Farmen
    (jedes neue Konto erhaelt Gratis-Tokens, die echtes Geld kosten)."""
    __tablename__ = "register_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    ip: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)


class Topic(Base):
    """Manuell angelegter Themen-Container. Keine automatische Klassifikation."""
    __tablename__ = "topics"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # grobe Kategorie fuer die Filter-Chips (vom Schueler gewaehlt)
    category: Mapped[str] = mapped_column(String(40), default="andere", nullable=False)
    color: Mapped[str] = mapped_column(String(16), default="#6366f1", nullable=False)
    # Lernziele, eine pro Zeile – Grundlage der Probepruefung. Frei formuliert,
    # denn ein Kind schreibt hier ab, was auf dem Arbeitsblatt steht.
    learning_goals: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # Archiviert statt geloescht: ein fertiges Thema soll aus dem Weg, die
    # Noten-Historie muss aber bleiben. NULL = aktiv.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    user: Mapped[User] = relationship(back_populates="topics")
    exercises: Mapped[list[Exercise]] = relationship(back_populates="topic")


class Exercise(Base):
    __tablename__ = "exercises"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("topics.id"), index=True, nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    image_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # erkannter / eingegebener Mathe-Ausdruck (z.B. "3*x + 5 = 20")
    math_expression: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Stammt die Aufgabe aus der Bibliothek: Nummer der Bibliotheks-Aufgabe.
    # Kein Fremdschluessel – eine geloeschte Bibliotheks-Aufgabe darf die
    # Arbeit des Schuelers nicht mitreissen.
    library_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    user: Mapped[User] = relationship(back_populates="exercises")
    topic: Mapped[Topic | None] = relationship(back_populates="exercises")
    attempts: Mapped[list[Attempt]] = relationship(back_populates="exercise", cascade="all, delete-orphan")


class Attempt(Base):
    """Eine Hinweis-Leiter-Session zu einer Exercise. Backend haelt den Leiter-Zustand."""
    __tablename__ = "attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    exercise_id: Mapped[int] = mapped_column(ForeignKey("exercises.id"), index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    status: Mapped[AttemptStatus] = mapped_column(Enum(AttemptStatus), default=AttemptStatus.active, nullable=False)
    # erreichte Hinweis-Stufe 0..4
    hint_level: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Anzahl eigener (mathe-relevanter) Antwortversuche des Schuelers
    own_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    solved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now, nullable=False)

    exercise: Mapped[Exercise] = relationship(back_populates="attempts")
    messages: Mapped[list[Message]] = relationship(back_populates="attempt", cascade="all, delete-orphan")


class Message(Base):
    """Chat-Verlauf pro Attempt. NUR aus Schueler-Rolle lesbar (siehe Router-Guards)."""
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("attempts.id"), index=True, nullable=False)
    role: Mapped[MessageRole] = mapped_column(Enum(MessageRole), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # feinkoerniger Score intern (0..1), nach aussen nie sichtbar
    verification: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Hilfe-Stufe, mit der diese Tutor-Antwort erzeugt wurde (Anzeige im Chat)
    hint_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # angehaengtes Bild (Stift-Zeichnung/Foto), Pfad wie bei Exercise.image_path
    image_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    attempt: Mapped[Attempt] = relationship(back_populates="messages")


class ProgressAggregate(Base):
    """Separat befuellte Tabelle fuer die Elternansicht. Kein Zugriff auf Transkripte."""
    __tablename__ = "progress_aggregates"
    __table_args__ = (UniqueConstraint("user_id", "week_start", name="uq_user_week"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    week_start: Mapped[date] = mapped_column(Date, nullable=False)  # Montag der Woche

    autonomy_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # 0..1
    solved_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # «Bearbeitet» statt «geloest» als Hauptzahl: nur 12 % aller Versuche werden
    # ueberhaupt abgehakt, ein Elternteil saehe sonst fast immer eine Null.
    worked_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Summe der eigenen Rechenschritte des Kindes – Aufwand statt Ergebnis.
    own_steps: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Bearbeitete Aufgaben ohne Themen-Zuordnung. Nicht als «Stolperstein»
    # zeigen, sondern zum Zuordnen auffordern.
    ohne_thema: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    active_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Top-Stolperthemen als grobe Trends: [{"topic": "...", "trend": "noch_ueben"}]
    top_struggles: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Aktivitaet pro Wochentag (Mo..So) fuer das Balkendiagramm
    daily_activity: Mapped[list | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now, nullable=False)


class ParentLink(Base):
    """Verknuepfung Eltern-Account <-> Schueler-Account per Einladungscode."""
    __tablename__ = "parent_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    invite_code: Mapped[str] = mapped_column(String(16), unique=True, index=True, nullable=False)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    # pending = Code erstellt, noch nicht eingeloest; linked = verbunden
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    linked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Feedback(Base):
    """Nutzer-Feedback aus der App – wird gespeichert und ist nur fuer das
    Betreiber-Konto (Admin) einsehbar."""
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # von welcher Seite abgeschickt (z.B. /app/lernen) – hilft beim Einordnen
    page: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # "feedback" (freier Text) oder "problem" (Knopf «Problem melden» mit
    # Kategorie und automatisch mitgegebenem Zusammenhang)
    kind: Mapped[str] = mapped_column(String(20), default="feedback", nullable=False)
    category: Mapped[str | None] = mapped_column(String(30), nullable=True)
    attempt_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Aufgabentext, letzte Schueler- und Tutor-Nachricht, erkannter Text –
    # vom Server gefuellt, damit der Betreiber sieht, was schiefging
    context: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)


class UploadedImage(Base):
    """Aufgaben-Fotos und Stift-Bilder als Bytes in Postgres.

    /tmp ist auf Vercel fluechtig – Dateien verschwinden bei jedem Kaltstart
    und hinterlassen tote Bild-Links im Verlauf. ``content`` ist deferred,
    damit Abfragen ohne Bildbedarf die Bytes nie mitladen.
    """

    __tablename__ = "uploaded_images"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    # 128-Bit-Zufalls-Capability: die Bild-URL ist unerratbar (dasselbe
    # Sicherheitsmodell wie vorher der Zufalls-Dateiname unter /uploads)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(60), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, deferred=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)


class ApiUsage(Base):
    """Token-Verbrauch je Anthropic-Aufruf – Grundlage der Admin-Kostenauswertung.

    Jede echte API-Antwort liefert die Verbraeuche mit; hier landen sie samt
    berechneten Kosten (USD). ``kind`` unterscheidet Chat/Erkennung/KI-Suche.
    """

    __tablename__ = "api_usage"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    exercise_id: Mapped[int | None] = mapped_column(ForeignKey("exercises.id"), index=True, nullable=True)
    kind: Mapped[str] = mapped_column(String(20), index=True, nullable=False)  # chat | ocr | suche
    model: Mapped[str] = mapped_column(String(60), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Teilmenge von cache_write_tokens mit 1-Stunden-Frist (kostet 2x statt
    # 1.25x). Der Tutor cacht System-Prompt und Aufgabe eine Stunde lang.
    cache_write_1h_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    charged_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)


class Alert(Base):
    """Betreiber-Alarm: protokollierte Stoerung (KI/OCR/Webhook) fuer den Admin-Bereich."""

    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    detail: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)


class TokenAdjustment(Base):
    """Manuelle Guthaben-Korrektur durch den Betreiber (Kulanz, Rueckerstattung,
    verpasster Webhook) – jede Buchung mit Grund und Urheber protokolliert."""

    __tablename__ = "token_adjustments"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    admin_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    tokens: Mapped[int] = mapped_column(Integer, nullable=False)  # +Gutschrift / -Abzug
    reason: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)


class LibraryExercise(Base):
    """Eine Aufgabe der Bibliothek – vom Betreiber gepflegt, von Schuelern
    mit einem Klick im Tutor gestartet.

    Frueher lagen hier PDF-Arbeitsblaetter (library_documents, nie befuellt).
    Ein Blatt zum Anschauen hilft niemandem; eine Aufgabe als Text hat einen
    Pruefausdruck, kann nachgerechnet werden und landet direkt im Chat.
    """

    __tablename__ = "library_exercises"

    id: Mapped[int] = mapped_column(primary_key=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # maschinell loesbarer Ausdruck fuer die Nachrechnung (z.B. "3*x + 5 = 20")
    math_expression: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Themen-Name aus library_topics (frei benennbar)
    category: Mapped[str] = mapped_column(String(120), nullable=False)
    # komma-verbunden aus mittelstufe / oberstufe / gymnasium
    grade_levels: Mapped[str] = mapped_column(String(80), nullable=False)
    difficulty: Mapped[str] = mapped_column(String(20), default="mittel", nullable=False)
    # Herkunft / Lizenzhinweis (z.B. «Serlo, CC BY-SA 4.0», «eigene», «KI»)
    source: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)


class LibraryTopic(Base):
    """Vom Betreiber verwaltete Themen-Titel der Bibliothek (frei benennbar)."""

    __tablename__ = "library_topics"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)


class StripeEvent(Base):
    """Verarbeitete Stripe-Ereignisse: Stripe schickt Webhooks bei Zweifel
    mehrfach, die Ereignis-ID macht jede Verarbeitung idempotent."""

    __tablename__ = "stripe_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)


class Payment(Base):
    """Abgeschlossene Käufe (Stripe). session_id unique = Webhook-Idempotenz."""

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(20), default="stripe", nullable=False)
    session_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    amount_rappen: Mapped[int] = mapped_column(Integer, nullable=False)
    tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)


class Grade(Base):
    """Schulnote, die der Schueler selbst erfasst – oder die geschaetzte Note
    aus einer Probepruefung (``source='probe'``).

    Bewusst am Schueler UND optional am Thema: eine Note ohne Thema («Mathe-
    Prüfung») soll nicht verloren gehen, und ein geloeschtes Thema darf die
    Note nicht mitnehmen (``topic_id`` wird dann auf NULL gesetzt).
    """

    __tablename__ = "grades"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("topics.id"), index=True, nullable=True)
    # Schweizer Skala 1.0–6.0, eine Dezimalstelle. Float genuegt: es wird nie
    # damit gerechnet, nur gemittelt und angezeigt.
    value: Mapped[float] = mapped_column(Float, nullable=False)
    # Datum der PRUEFUNG, nicht der Erfassung – sonst stimmt der Verlauf nicht.
    taken_on: Mapped[date] = mapped_column(Date, nullable=False)
    label: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    # "selbst" = vom Schueler eingetragen, "probe" = aus einer Probepruefung
    source: Mapped[str] = mapped_column(String(16), default="selbst", nullable=False)
    exam_id: Mapped[int | None] = mapped_column(ForeignKey("exams.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)


class ExamStatus(str, enum.Enum):
    offen = "offen"        # erzeugt, noch nicht abgegeben
    bewertet = "bewertet"  # abgegeben und korrigiert


class Exam(Base):
    """Eine generierte Probepruefung zu einem Thema."""

    __tablename__ = "exams"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"), index=True, nullable=False)
    status: Mapped[ExamStatus] = mapped_column(Enum(ExamStatus), default=ExamStatus.offen,
                                               nullable=False)
    model: Mapped[str] = mapped_column(String(60), default="", nullable=False)
    # Kopie der Lernziele beim Erzeugen: aendert der Schueler sie spaeter,
    # bleibt nachvollziehbar, worauf DIESE Pruefung beruhte.
    learning_goals: Mapped[str] = mapped_column(Text, default="", nullable=False)
    grade_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    items: Mapped[list[ExamItem]] = relationship(back_populates="exam",
                                                 cascade="all, delete-orphan")


class ExamItem(Base):
    """Eine Aufgabe innerhalb einer Probepruefung."""

    __tablename__ = "exam_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id"), index=True, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    # Pruefausdruck fuer SymPy – leer, wenn keiner gewonnen werden konnte.
    # Dann und NUR dann muss das Modell die Antwort bewerten.
    math_expression: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    # Welches Lernziel diese Aufgabe abdeckt (Klartext, fuer die Auswertung)
    goal: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    student_answer: Mapped[str] = mapped_column(Text, default="", nullable=False)
    image_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # "correct" | "incorrect" | "unknown" (noch nicht bewertet: "")
    verdict: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    # Wer hat bewertet: "sympy" (gratis, deterministisch) oder "ki"
    judged_by: Mapped[str] = mapped_column(String(8), default="", nullable=False)

    exam: Mapped[Exam] = relationship(back_populates="items")
