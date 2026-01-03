# ==================================================================================
# core/config.py — FastAPI Configuration (Render + SendGrid + Stripe + Pydantic v2)
# ==================================================================================
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import EmailStr, ValidationError
import sys


class Settings(BaseSettings):
    # ------------------------
    # DATABASE CONFIG
    # ------------------------
    DATABASE_URL: str

    # ------------------------
    # SECURITY CONFIG
    # ------------------------
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 300  # 5 hours

    # ------------------------
    # SENDGRID EMAIL CONFIG
    # ------------------------
    SENDGRID_API_KEY: str
    MAIL_FROM: EmailStr  # Example: "TeamFlow <your_email@gmail.com>"

    # ------------------------
    # FRONTEND & BACKEND CONFIG
    # ------------------------
    FRONTEND_URL: str = "https://teamflow-frontend-omega.vercel.app"
    BACKEND_URL: str = "https://teamflow-backend-1tt9.onrender.com"


    # -----------------------------------------
    # FRONTEND & BACKEND CONFI For LOCAL DEV
    # -----------------------------------------
    # FRONTEND_URL: str = "http://localhost:5173"
    # BACKEND_URL: str = "http://localhost:8000"


    # ------------------------
    # STRIPE / PAYMENT CONFIG
    # ------------------------
    STRIPE_SECRET_KEY: str | None = None
    STRIPE_WEBHOOK_SECRET: str | None = None

    @property
    def STRIPE_SUCCESS_URL(self) -> str:
        """
        Dynamic success URL for Stripe checkout
        Automatically adapts for local or production frontend.
        """
        return f"{self.FRONTEND_URL}/payment/success?session_id={{CHECKOUT_SESSION_ID}}"

    @property
    def STRIPE_CANCEL_URL(self) -> str:
        """Dynamic cancel URL for Stripe checkout"""
        return f"{self.FRONTEND_URL}/payment/cancel"

    # ------------------------
    # ENVIRONMENT SETTINGS
    # ------------------------
    ENVIRONMENT: str = "development"  # 'development' | 'production'
    DEBUG: bool = True

    @property
    def IS_PRODUCTION(self) -> bool:
        """Convenience helper to check if running in production"""
        return self.ENVIRONMENT.lower() == "production"

    # ------------------------
    # Pydantic v2 Settings
    # ------------------------
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # Ignores unknown env vars (Render defaults)
    )


# ------------------------
# Global Settings Loader
# ------------------------
try:
    settings = Settings()
    print("✅ Environment variables loaded successfully.")
    print(f"🌍 Environment: {settings.ENVIRONMENT}, Debug: {settings.DEBUG}")
except ValidationError as e:
    print("❌ Environment configuration error — missing or invalid settings!")
    print(e)
    sys.exit(1)
except Exception as ex:
    print("❌ Unexpected error while loading environment variables:")
    print(ex)
    sys.exit(1)
