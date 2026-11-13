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
    # Runtime cache for AI answers. Deliberately NOT the dictionary file: that
    # file is a pinned, shipped asset (ASSET-PINS.json), and letting a live
    # request write to it silently changes the fingerprint of what we ship.
    ai_cache_path: str = "data/runtime/ai_cache.sqlite"
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

    # ---- Runtime guards for the AI endpoints (task P0.5) ----
    # Shared secret required in the X-AI-Token header on the AI routes. Empty =
    # no requirement (the pre-P0.5 behaviour), so shipping this changes nothing
    # until an operator sets it.
    ai_shared_secret: str = ""
    # In-memory quota. 0 = off. Values are also readable from the environment
    # (AI_RATE_LIMIT_PER_MIN / AI_DAILY_CAP) so they can be changed live.
    # Defaults are non-zero on purpose: a production deployment must not inherit
    # "no limiter at all" merely because nobody set a value. The limiter only
    # counts while ai_enabled is True, so offline-only lookups are unaffected.
    ai_rate_limit_per_min: int = 60
    ai_daily_cap: int = 2000
    # Two budgets, deliberately separate. The per-client values (keyed by
    # X-Client-Id, falling back to the caller's IP) stop one device from
    # consuming everything; the global values protect the provider quota as a
    # whole. Environment overrides: AI_RATE_LIMIT_PER_MIN, AI_DAILY_CAP_PER_CLIENT,
    # AI_RATE_LIMIT_GLOBAL_PER_MIN, AI_DAILY_CAP.
    ai_daily_cap_per_client: int = 100
    ai_rate_limit_global_per_min: int = 600

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

    # ---- Strict zero-cost failover (20-slot registry) --------------------------
    # free_only: an endpoint may only run when both prices are verified as 0.
    # Paid slots stay in the registry, disabled, so the shortfall is visible.
    ai_free_only: bool = True
    ai_max_models: int = 20
    ai_max_attempts_per_request: int = 6      # hard cap on endpoint calls per request
    ai_max_retries_per_provider: int = 2      # retries inside one endpoint
    ai_request_timeout_seconds: float = 45.0
    ai_max_total_request_seconds: float = 180.0
    ai_enable_local_fallback: bool = False    # Ollama is optional, never required
    ai_enable_paid_fallback: bool = False     # hard-coded off by policy
    ai_strict_zero_cost: bool = True
    ai_model_discovery_enabled: bool = True   # re-verify the OpenRouter catalogue
    ai_model_discovery_interval_hours: int = 24
    ai_output_validation_enabled: bool = True
    ai_free_quota_rpm: int = 20               # conservative, provider-unknown guard
    ai_free_quota_rpd: int = 1000

    # Supabase auth (optional). Set the project JWT secret to verify tokens
    # issued by Supabase Auth in the /me + favorites + feedback endpoints.
    supabase_url: str = ""
    supabase_jwt_secret: str = ""
    # Server-side only. Used for admin operations (delete a user, revoke
    # sessions). It must never reach a client; see docs/SECURITY.md.
    supabase_service_role_key: str = ""

    # Auth policy (docs/AUTH-SCHEMA.md). Values are enforced in code and, where
    # they are invariants, in Postgres too.
    auth_code_ttl_minutes: int = 10
    auth_max_code_attempts: int = 5
    auth_resend_cooldown_seconds: int = 60
    auth_max_emails_per_hour: int = 5
    auth_lockout_steps_seconds: str = "60,300,900"
    auth_username_min_length: int = 3
    auth_username_max_length: int = 20
    auth_password_min_length: int = 8
    auth_password_max_length: int = 128


settings = Settings()
