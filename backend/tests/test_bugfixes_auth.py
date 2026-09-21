"""Ausweise aus einem Mail-Link sind kurzlebig."""
from datetime import datetime, timezone

from jose import jwt

from app.config import settings
from app.security import create_access_token


def test_mail_link_ausweis_laeuft_nach_einer_stunde_ab():
    normal = jwt.decode(create_access_token(1, "student"), settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    per_mail = jwt.decode(create_access_token(1, "student", via="email"), settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    jetzt = datetime.now(timezone.utc).timestamp()
    assert per_mail["exp"] - jetzt <= settings.jwt_email_expire_minutes * 60 + 5
    assert normal["exp"] - jetzt > 24 * 3600
