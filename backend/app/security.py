"""JWT-Erzeugung/-Pruefung, Passwort-Hashing und Token-Helfer."""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from .config import settings


def create_access_token(user_id: int, role: str, via: str = "password",
                        token_version: int = 0) -> str:
    """via="email": Login kam ueber einen Mail-Link – erlaubt Passwort-Neusetzen
    ohne altes Passwort (Passwort-vergessen-Flow).
    token_version ("tv"): Passwort-Aenderung erhoeht die Version am Konto und
    macht damit alle vorher ausgestellten Tokens sofort ungueltig."""
    minuten = settings.jwt_email_expire_minutes if via == "email" else settings.jwt_expire_minutes
    expire = datetime.now(timezone.utc) + timedelta(minutes=minuten)
    payload = {"sub": str(user_id), "role": role, "via": via, "tv": token_version, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None


def hash_password(password: str) -> str:
    """Passwort-Hash mit scrypt (Standardbibliothek, keine Zusatz-Dependency)."""
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt:16384:8:1${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        params, salt_hex, digest_hex = stored.split("$")
        _, n, r, p = params.split(":")
        digest = hashlib.scrypt(
            password.encode(),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=32,
        )
        return secrets.compare_digest(digest.hex(), digest_hex)
    except Exception:
        return False


def new_magic_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Magic-Link-Tokens werden nur gehasht gespeichert (DB-Leak != Login)."""
    return hashlib.sha256(token.encode()).hexdigest()


def new_invite_code() -> str:
    # gut lesbarer 8-stelliger Code (keine 0/O/1/I Verwechslungen)
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(8))
