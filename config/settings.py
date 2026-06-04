"""
config/settings.py — Environment configuration
Integrity Compounders Alpha System v10.0

Loads all required environment variables from .env using python-dotenv.
Raises a clear error at import time if any required variable is missing.

Usage:
    from config.settings import settings
    print(settings.SUPABASE_URL)
    print(settings.ANTHROPIC_API_KEY)
"""

from pathlib import Path
from dotenv import dotenv_values

# ── Load .env from project root ───────────────────────────────────────────────
_ROOT    = Path(__file__).parent.parent
_env     = dotenv_values(_ROOT / ".env")

# ── Required variables ────────────────────────────────────────────────────────
REQUIRED = [
    "SUPABASE_URL",
    "SUPABASE_ANON_KEY",
    "SUPABASE_SERVICE_KEY",
    "DATABASE_URL",
    "ANTHROPIC_API_KEY",
]

# ── Validation ────────────────────────────────────────────────────────────────
_missing = [key for key in REQUIRED if not _env.get(key)]
if _missing:
    raise EnvironmentError(
        f"\n\n[config/settings.py] Missing required environment variable(s):\n"
        + "\n".join(f"  - {k}" for k in _missing)
        + f"\n\nMake sure these are set in: {_ROOT / '.env'}\n"
    )

# ── Settings object ───────────────────────────────────────────────────────────
class _Settings:
    # Supabase
    SUPABASE_URL:         str = _env["SUPABASE_URL"]
    SUPABASE_ANON_KEY:    str = _env["SUPABASE_ANON_KEY"]
    SUPABASE_SERVICE_KEY: str = _env["SUPABASE_SERVICE_KEY"]

    # Database
    DATABASE_URL:         str = _env["DATABASE_URL"]

    # Anthropic / Claude API
    ANTHROPIC_API_KEY:    str = _env["ANTHROPIC_API_KEY"]

    def __repr__(self) -> str:
        """Safe repr — never prints secret values."""
        def mask(v: str) -> str:
            return v[:8] + "..." + v[-4:] if len(v) > 12 else "***"
        return (
            f"Settings(\n"
            f"  SUPABASE_URL         = {self.SUPABASE_URL}\n"
            f"  SUPABASE_ANON_KEY    = {mask(self.SUPABASE_ANON_KEY)}\n"
            f"  SUPABASE_SERVICE_KEY = {mask(self.SUPABASE_SERVICE_KEY)}\n"
            f"  DATABASE_URL         = {self.DATABASE_URL[:30]}...\n"
            f"  ANTHROPIC_API_KEY    = {mask(self.ANTHROPIC_API_KEY)}\n"
            f")"
        )


settings = _Settings()


# ── Quick self-test ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("[config/settings.py] All required variables loaded successfully.\n")
    print(settings)
