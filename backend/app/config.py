"""Zentrale Konfiguration via pydantic-settings (liest aus .env / Umgebung)."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Anthropic
    anthropic_api_key: str = ""
    anthropic_model_default: str = "claude-haiku-4-5"
    anthropic_model_smart: str = "claude-sonnet-5"

    # Auth / JWT
    jwt_secret: str = "dev-secret-nur-fuer-lokal-nicht-in-produktion"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 43200  # 30 Tage

    # Datenbank – SQLite lokal, per DATABASE_URL auf Postgres umstellbar
    database_url: str = "sqlite:///./schrittweise.db"

    # CORS
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Magic-Link
    # Sicherer Default: AUS. Lokal aktiviert die .env (aus .env.example) den Dev-Modus;
    # in Produktion muss er bewusst gesetzt werden – sonst kein Login-Link-Leak.
    magic_link_dev_return: bool = False
    # Bewusste Freigabe, den Dev-Login AUSNAHMSWEISE in Produktion zu erlauben
    # (z.B. Test-Deploy vor SMTP-Einrichtung). Ohne dieses Flag verweigert die App
    # in Produktion den Start mit aktivem Dev-Login.
    allow_insecure_dev_login: bool = False
    frontend_base_url: str = "http://localhost:5173"

    # Supabase Auth: Login-Mails über Supabase statt eigenem SMTP (optional).
    # Beide Werte gesetzt -> Magic-Link-Mails verschickt Supabase.
    supabase_url: str = ""
    supabase_anon_key: str = ""

    # SMTP (optional)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "Kniff <no-reply@schrittweise.ch>"

    # Zieladresse fuer Betreiber-Alarme (KI-Ausfall, Webhook-Fehler);
    # Mails gehen nur raus, wenn zusaetzlich SMTP konfiguriert ist.
    alert_email: str = "mahmmouds62@gmail.com"

    # E-Mail-Bestaetigung erzwingen: unbestaetigte Konten koennen weder KI
    # nutzen noch kaufen (Schutz gegen Konto-Farmen mit Wegwerf-Adressen).
    # Standard AN, seit der Mailversand nachweislich laeuft: Versand ueber
    # Brevo, Link erreichbar, Anmeldung setzt email_verified. Beide
    # Bestaetigungswege (/verify und /verify-supabase) heben die Sperre auf.
    # Per REQUIRE_EMAIL_VERIFICATION=false abschaltbar, falls der Mailversand
    # einmal ausfaellt – dann sperrt sie sonst alle Neuregistrierungen aus.
    require_email_verification: bool = True

    # Kontingent: 1 Token = 1 Rappen verrechnete KI-Leistung.
    # Jedes Konto bekommt monatlich Gratis-Tokens; danach zahlt das Guthaben.
    free_monthly_tokens: int = 50
    # Sicherheitsmarge auf die echten KI-Kosten (3x = Schueler zahlen das
    # Dreifache der Anthropic-Kosten; deckt Stripe-Gebuehren + Gratis-Nutzer)
    billing_margin: float = 3.0

    # Umrechnungskurs fuer die Kosten-Anzeige im Admin-Bereich (Anthropic
    # rechnet in USD ab, der Betreiber denkt in CHF/Rappen)
    usd_chf_rate: float = 0.90

    # Stripe (Token-Paket-Kauf); beide leer = Zahlung deaktiviert
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    # TWINT-Abos gibt es bei Stripe erst ab dieser API-Version (27.5.2026);
    # damit liegt current_period_end am Abo-Posten (items.data[0]).
    stripe_api_version: str = "2026-05-27"

    # Kniff Plus: EIN Abo pro Kind statt Token-Pakete. Solange der Schalter
    # aus ist, verhaelt sich die App exakt wie bisher (Gratis-Tokens + Guthaben).
    abo_enabled: bool = False
    plus_name: str = "Kniff Plus"
    plus_preis_monat_rappen: int = 990
    plus_preis_jahr_rappen: int = 8900
    # Fair-Use fuer Plus, still: 1500 Tokens ~ 90-150 Aufgaben, echte Kosten
    # hoechstens ~5 CHF im Monat.
    plus_monatslimit_tokens: int = 1500
    # Probe: die ersten Aufgaben sind gratis - einmalig, in Aufgaben gezaehlt.
    trial_tasks: int = 10

    @property
    def payments_enabled(self) -> bool:
        return bool(self.stripe_secret_key and self.stripe_webhook_secret)

    @property
    def is_production(self) -> bool:
        """True, sobald die App auf Vercel laeuft – also auch in einer Vorschau.

        Absichtlich streng: die Vorschau soll dieselben Sicherheits-Riegel
        durchlaufen wie die echte Seite (Platzhalter-JWT_SECRET verweigert den
        Start, kein Dev-Login-Leak). Sonst prueft man in der Vorschau etwas
        anderes, als spaeter live steht.
        """
        import os

        return bool(os.environ.get("VERCEL"))

    @property
    def jwt_secret_is_placeholder(self) -> bool:
        return self.jwt_secret.startswith(("dev-secret", "change-me"))


    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def smtp_enabled(self) -> bool:
        return bool(self.smtp_host and self.smtp_from)

    @property
    def supabase_auth_enabled(self) -> bool:
        return bool(self.supabase_url and self.supabase_anon_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
