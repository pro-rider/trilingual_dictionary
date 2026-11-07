from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Trilingual Dictionary API"
    version: str = "0.1.0"

    # CORS — locked rule: allow the Flutter app origin(s); "*" for dev only.
    cors_origins: list[str] = ["*"]

    # Offline-first dataset used in v1 (before Postgres is wired).
    dataset_path: str = "data/seed/en_zh_ne.json"
    dataset_version: int = 1

    # Merged SQLite dictionary built by tools/build_dictionary.py. Used as a
    # coverage fallback after the curated JSON fixture; ignored when missing.
    dictionary_db_path: str = "data/build/dictionary.sqlite"
    # Public base URL the client should use for image files served by /static.
    image_base_url: str = ""
    # Where fetch_images.py wrote the thumbnails/detail files.
    images_dir: str = "data/images"

    # PostgreSQL authoritative source (future). Not required to run in v1.
    database_url: str = (
        "postgresql+psycopg://postgres:postgres@localhost:5432/trilingual_dictionary"
    )

    # AI provider — never exposed to the Flutter app. Disabled by default.
    # Master switch: words missing from the dataset are generated on the fly.
    ai_enabled: bool = False

    # ---- Multi-provider LLM failover (priority: groq → gemini → openrouter) ----
    ai_providers_order: str = "groq,gemini,openrouter"
    ai_max_retries: int = 1          # attempts per provider, after the first
    ai_retry_backoff_seconds: float = 0.5
    # Circuit breaker (temporarily disable a repeatedly-failing provider)
    circuit_fail_threshold: int = 3
    circuit_cooldown_seconds: int = 30

    # Groq (OpenAI-compatible). Falls back to legacy ai_* fields for key/model.
    groq_api_key: str = ""
    groq_model: str = ""
    groq_timeout: float = 40
    groq_enabled: bool = True
    groq_base_url: str = "https://api.groq.com/openai/v1"

    # Google Gemini (native API)
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    gemini_timeout: float = 40
    gemini_enabled: bool = True
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"

    # OpenRouter (OpenAI-compatible, many free models)
    openrouter_api_key: str = ""
    openrouter_model: str = "meta-llama/llama-3.1-70b-instruct"
    openrouter_timeout: float = 40
    openrouter_enabled: bool = True
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # Legacy single-provider fields (kept for backward compatibility; Groq uses
    # groq_api_key/model when set, otherwise these).
    ai_api_key: str = ""
    ai_model: str = ""
    ai_base_url: str = "https://api.groq.com/openai/v1"

    # Supabase auth (optional). Set the project JWT secret to verify tokens
    # issued by Supabase Auth in the /me + favorites + feedback endpoints.
    supabase_url: str = ""
    supabase_jwt_secret: str = ""


settings = Settings()
