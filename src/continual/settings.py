from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# Into os.environ, not just this object — boto3 reads AWS_* from there.
load_dotenv(".env.local")


class Settings(BaseSettings):
    """App config, read from environment / .env.local (see .env.example)."""

    model_config = SettingsConfigDict(env_file=".env.local", extra="ignore")

    # Supabase Supavisor transaction pooler — db.py disables prepared statements for it.
    database_url: str = ""

    # Credentials come from the standard AWS_* env vars (boto3 default chain).
    s3_bucket: str = ""

    # Assembly rules (TRUNK_SPEC.md §5.2). Config, not literals: the first guess
    # at what counts as one episode depends on the customer's product and will be wrong.
    episode_idle_timeout_s: int = 1800
    episode_max_duration_s: int = 86_400

    # A field larger than this is treated as truncated, which disqualifies its
    # episode from `replayable` (TRUNK_SPEC.md §5.3).
    max_captured_field_bytes: int = 1024 * 1024


settings = Settings()
