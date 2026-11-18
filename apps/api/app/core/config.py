from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    DATABASE_URL: str = "sqlite:///./interioriq.db"   # zero-infrastructure default
    SECRET_KEY: str = "dev-secret-change-me"
    TOKEN_MINUTES: int = 60 * 24
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_LLM_MODEL: str = "llama3.1:8b"
    STORAGE_PATH: str = "../../storage"
    OCR_PROVIDER: str = "auto"            # auto | paddleocr | rapidocr | tesseract
    MAX_UPLOAD_MB: int = 25
    # Quotation header (a Company Settings screen with a database table comes later; for now these come from the environment)
    COMPANY_NAME: str = "InteriorIQ Design Studio"
    COMPANY_ADDRESS: str = ""
    COMPANY_PHONE: str = ""
    COMPANY_EMAIL: str = ""
    COMPANY_GSTIN: str = ""
    QUOTE_VALID_DAYS: int = 30
    # Email (optional; zero cost with any SMTP account, e.g. Gmail + an app password). The password lives ONLY here (.env), never in the database or the UI.
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""                   # e.g. "Shreeji Interiors <studio@example.com>"; defaults to SMTP_USER
    SMTP_SECURITY: str = "starttls"       # starttls | ssl | none
    PUBLIC_URL: str = "http://localhost:3000"
    NOTIFY_WORKER: bool = True
    # M23: schema migrations + background jobs
    AUTO_MIGRATE: bool = True               # run `alembic upgrade head` at start-up; with several API servers set false and run it once per deploy
    TASK_BACKEND: str = "thread"            # thread = OCR + email run inside this API process (default, zero setup) | celery = separate worker processes
    CELERY_BROKER_URL: str = ""             # e.g. sqla+sqlite:///./celery-broker.db (free, no server) · sqla+postgresql://… · redis://localhost:6379/0
    OCR_STALE_MINUTES: int = 30             # a document 'reading' longer than this is treated as dead and can be re-read
    EMAIL_STALE_MINUTES: int = 10           # an email 'sending' longer than this goes back to the queue
    COMPANY_UTC_OFFSET_MIN: int = 330     # local time for "today"/"overdue" (India = +5:30). A fixed offset: Windows often lacks tz data            # background email sender (tests turn it off and drive the outbox directly)   # used in messages to link clients to their portal
    PDF_FONT_PATH: str = ""               # optional .ttf with the glyphs you need (e.g. Gujarati/Hindi); default is built-in Helvetica (Latin only)
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000"]
    # Local dev: the site may be opened as localhost OR 127.0.0.1, on 3000 or whichever port Next picks. Tighten for production.
    ALLOWED_ORIGIN_REGEX: str = r"https?://(localhost|127\.0\.0\.1)(:\d+)?"

settings = Settings()
