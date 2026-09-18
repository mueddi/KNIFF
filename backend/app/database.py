"""SQLAlchemy-Setup. Ueber DATABASE_URL abstrahiert – SQLite jetzt, Postgres spaeter."""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import NullPool

from .config import settings

def _normalize_url(url: str) -> str:
    """Manche Anbieter liefern postgres:// – SQLAlchemy braucht postgresql+psycopg://."""
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


DATABASE_URL = _normalize_url(settings.database_url)

# check_same_thread nur fuer SQLite noetig. Bei Postgres die Session-Zeitzone
# hart auf UTC pinnen: alle Timestamp-Spalten sind naive UTC-Wandzeit – ein
# abweichendes Server-Default-TZ wuerde Link-Ablauf und Rate-Limits verschieben.
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
else:
    connect_args = {"options": "-c timezone=utc"}

_engine_kwargs: dict = {"connect_args": connect_args, "pool_pre_ping": True}
if os.environ.get("VERCEL") and not DATABASE_URL.startswith("sqlite"):
    # Serverless: kein clientseitiges Connection-Pooling – sonst halten viele
    # Function-Instanzen Verbindungen offen und erschoepfen den Supabase-Pooler.
    _engine_kwargs["poolclass"] = NullPool
    _engine_kwargs.pop("pool_pre_ping")

engine = create_engine(DATABASE_URL, **_engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI-Dependency: liefert eine DB-Session und schliesst sie sauber."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Schema sicherstellen – aber NIE auf Kosten der Erreichbarkeit.

    Das hier laeuft bei JEDEM Kaltstart der Serverless-Funktion, also sehr oft.
    Zwei Dinge waren daran falsch:

    1. Es lief UNGESCHUETZT. War die Datenbank in dem Moment kurz nicht
       erreichbar, flog die Ausnahme bis in den Import von ``api/index.py`` –
       und Vercel meldete FUNCTION_INVOCATION_FAILED: die ganze Seite weg,
       nicht nur die eine Anfrage. Genau so ein 500er war am 31.07. zu sehen
       (beim zweiten Aufruf war wieder alles normal).
    2. Es fragte die Datenbank ueber ein Dutzend Mal, auch wenn nichts zu tun
       war: einmal ``create_all`` (mit eigener Reflexion), einmal die
       Tabellenliste und dann ``get_columns`` PRO Migrations-Eintrag.

    Jetzt: eine Reflexion, eine Spaltenabfrage pro betroffener Tabelle, und ein
    Fehler kostet hoechstens die Schema-Aktualisierung – nie den Start.
    """
    import logging

    try:
        _schema_sicherstellen()
    except Exception:
        logging.getLogger("schrittweise.db").exception(
            "Schema-Pruefung beim Start fehlgeschlagen – die App startet trotzdem. "
            "Fehlt eine Spalte, zeigen die betroffenen Anfragen das im Log."
        )


def _schema_sicherstellen() -> None:
    from sqlalchemy import inspect, text

    from . import models  # noqa: F401  – Modelle registrieren

    import logging

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    # create_all reflektiert selbst nochmal ueber ALLE Tabellen – das lohnt nur,
    # wenn wirklich eine fehlt (also beim allerersten Start und nach einer
    # neuen Tabelle im Modell).
    if set(Base.metadata.tables) - tables:
        Base.metadata.create_all(bind=engine)
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())

    # Mini-Migrationen: create_all ergaenzt keine Spalten in bestehenden Tabellen.
    # Fehler (z.B. fehlende Owner-Rechte) duerfen den Kaltstart nicht killen –
    # dann fehlt zwar die Spalte, aber der Rest der App laeuft und das Log zeigt warum.
    migrations = [
        ("users", "password_hash", "ALTER TABLE users ADD COLUMN password_hash VARCHAR(255)"),
        ("users", "is_admin", "ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT FALSE NOT NULL"),
        ("messages", "hint_level", "ALTER TABLE messages ADD COLUMN hint_level INTEGER"),
        ("users", "free_used_tokens", "ALTER TABLE users ADD COLUMN free_used_tokens INTEGER DEFAULT 0 NOT NULL"),
        ("users", "free_month", "ALTER TABLE users ADD COLUMN free_month VARCHAR(7)"),
        ("api_usage", "charged_tokens", "ALTER TABLE api_usage ADD COLUMN charged_tokens INTEGER DEFAULT 0 NOT NULL"),
        ("users", "terms_accepted_at", "ALTER TABLE users ADD COLUMN terms_accepted_at TIMESTAMP"),
        ("users", "token_version", "ALTER TABLE users ADD COLUMN token_version INTEGER DEFAULT 0 NOT NULL"),
        # DEFAULT TRUE: Bestandskonten (vor der Bestaetigungs-Pflicht registriert)
        # gelten als bestaetigt; NEUE Konten setzt die App explizit auf FALSE.
        ("users", "email_verified", "ALTER TABLE users ADD COLUMN email_verified BOOLEAN DEFAULT TRUE NOT NULL"),
        ("messages", "image_path", "ALTER TABLE messages ADD COLUMN image_path VARCHAR(255)"),
        # Lernziele je Thema (Grundlage der Probepruefung) + Archiv statt Loeschen.
        # DEFAULT '' NOT NULL, damit Bestands-Themen gueltig bleiben.
        ("topics", "learning_goals",
         "ALTER TABLE topics ADD COLUMN learning_goals TEXT DEFAULT '' NOT NULL"),
        ("topics", "archived_at", "ALTER TABLE topics ADD COLUMN archived_at TIMESTAMP"),
        # Elternansicht: «bearbeitet» statt «geloest» als Hauptzahl, plus
        # Aufwand und die Aufgaben ohne Thema. DEFAULT 0, damit alte
        # Wochenzeilen gueltig bleiben (sie zeigen dann 0 – ehrlich, denn
        # damals wurde nichts erhoben).
        ("progress_aggregates", "worked_count",
         "ALTER TABLE progress_aggregates ADD COLUMN worked_count INTEGER DEFAULT 0 NOT NULL"),
        ("progress_aggregates", "own_steps",
         "ALTER TABLE progress_aggregates ADD COLUMN own_steps INTEGER DEFAULT 0 NOT NULL"),
        ("progress_aggregates", "ohne_thema",
         "ALTER TABLE progress_aggregates ADD COLUMN ohne_thema INTEGER DEFAULT 0 NOT NULL"),
        # Kostenerfassung: Cache-Schreiben mit 1-Stunden-Frist kostet 2x statt
        # 1.25x. DEFAULT 0: alle Zeilen davor stammen aus dem 5-Minuten-Cache.
        ("api_usage", "cache_write_1h_tokens",
         "ALTER TABLE api_usage ADD COLUMN cache_write_1h_tokens INTEGER DEFAULT 0 NOT NULL"),
        # Bibliothek: aus welcher Bibliotheks-Aufgabe eine Schueler-Aufgabe stammt.
        ("exercises", "library_id", "ALTER TABLE exercises ADD COLUMN library_id INTEGER"),
        # «Problem melden»: Kategorie und Zusammenhang zur Meldung.
        ("feedback", "kind", "ALTER TABLE feedback ADD COLUMN kind VARCHAR(20) DEFAULT 'feedback' NOT NULL"),
        ("feedback", "category", "ALTER TABLE feedback ADD COLUMN category VARCHAR(30)"),
        ("feedback", "attempt_id", "ALTER TABLE feedback ADD COLUMN attempt_id INTEGER"),
        ("feedback", "image_path", "ALTER TABLE feedback ADD COLUMN image_path VARCHAR(255)"),
        ("feedback", "context", "ALTER TABLE feedback ADD COLUMN context TEXT"),
        ("feedback", "resolved_at", "ALTER TABLE feedback ADD COLUMN resolved_at TIMESTAMP"),
        # Kniff Plus (Stripe-Abo): alles nullable bzw. mit Default, damit
        # Bestandskonten unveraendert gueltig bleiben.
        ("users", "stripe_customer_id", "ALTER TABLE users ADD COLUMN stripe_customer_id VARCHAR(64)"),
        ("users", "stripe_subscription_id", "ALTER TABLE users ADD COLUMN stripe_subscription_id VARCHAR(64)"),
        ("users", "abo_bis", "ALTER TABLE users ADD COLUMN abo_bis TIMESTAMP"),
        ("users", "abo_gekuendigt", "ALTER TABLE users ADD COLUMN abo_gekuendigt BOOLEAN DEFAULT FALSE NOT NULL"),
        ("users", "abo_intervall", "ALTER TABLE users ADD COLUMN abo_intervall VARCHAR(8)"),
    ]
    # Spalten EINMAL pro Tabelle holen statt einmal pro Migrations-Eintrag:
    # 13 Eintraege verteilen sich auf 4 Tabellen.
    spalten: dict[str, set[str]] = {}
    for table, column, ddl in migrations:
        if table not in tables:
            continue
        try:
            if table not in spalten:
                spalten[table] = {col["name"] for col in inspector.get_columns(table)}
            if column in spalten[table]:
                continue
            with engine.begin() as conn:
                conn.execute(text(ddl))
            spalten[table].add(column)
        except Exception:
            logging.getLogger("schrittweise.db").exception(
                "Auto-Migration fehlgeschlagen (%s.%s)", table, column
            )

    # Frueher lief hier bei JEDEM Serverstart eine Daten-Umstellung der
    # Klassenstufen (drei SQL-Befehle pro Kaltstart). Sie ist erledigt: in der
    # Produktion nachgezaehlt sind 0 Zeilen betroffen, alle Stufen stehen
    # kanonisch (mittelstufe/oberstufe/gymnasium). Entfernt am 30.07.2026.
