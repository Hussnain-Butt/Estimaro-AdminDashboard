"""Centralized configuration loaded from .env"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    GEMINI_API_KEY: str = ""
    OLLAMA_HOST: str = "http://localhost:11434"
    HERMES_MODEL: str = "hermes3:8b"

    CHROME_DEBUG_PORT: int = 9222
    CHROME_DEBUG_HOST: str = "localhost"

    BACKEND_URL: str = ""
    BACKEND_POLL_INTERVAL: int = 5

    TEKMETRIC_API_KEY: str = ""
    TEKMETRIC_SHOP_ID: str = ""

    # ----- Portal login credentials (auto-login agent) -------------------
    # Real values live ONLY in .env on the VPS (gitignored). Never commit them.
    # Passwords are filled directly into the page by Playwright and are NEVER
    # sent to the LLM.
    ALLDATA_USERNAME: str = ""
    ALLDATA_PASSWORD: str = ""
    PARTSLINK24_USERNAME: str = ""
    PARTSLINK24_PASSWORD: str = ""
    PARTSLINK24_COMPANY_ID: str = ""
    SSF_USERNAME: str = ""
    SSF_PASSWORD: str = ""
    WORLDPAC_USERNAME: str = ""
    WORLDPAC_PASSWORD: str = ""
    TEKMETRIC_USERNAME: str = ""
    TEKMETRIC_PASSWORD: str = ""

    LOG_LEVEL: str = "INFO"
    SCREENSHOT_DIR: str = "./screenshots"
    MAX_AGENT_STEPS: int = 25

    @property
    def chrome_cdp_url(self) -> str:
        return f"http://{self.CHROME_DEBUG_HOST}:{self.CHROME_DEBUG_PORT}"


settings = Settings()
