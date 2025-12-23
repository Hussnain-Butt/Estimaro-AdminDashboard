from pydantic_settings import BaseSettings
from typing import Literal


class Settings(BaseSettings):
    """
    Application configuration settings.
    Loads from environment variables or .env file.
    """
    
    # Application
    APP_NAME: str = "Estimaro API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True
    
    # Database
    DATABASE_URL: str
    
    # JWT Authentication
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 hours
    
    # External API Adapters
    # Options: mock, scraper, remote
    # - mock: Use fake data (development)
    # - scraper: Local Chrome CDP scraping (same server)
    # - remote: Call Scraper Microservice (different server)
    LABOR_ADAPTER_TYPE: Literal["mock", "alldata", "scraper", "remote"] = "mock"
    PARTS_ADAPTER_TYPE: Literal["mock", "partslink", "scraper", "remote"] = "mock"
    VENDOR_WORLDPAC_ADAPTER_TYPE: Literal["mock", "real", "scraper", "remote"] = "mock"
    
    # Vendor Credentials
    WORLDPAC_USERNAME: str = ""
    WORLDPAC_PASSWORD: str = ""
    
    SSF_USERNAME: str = ""
    SSF_PASSWORD: str = ""
    
    ALLDATA_USERNAME: str = ""
    ALLDATA_PASSWORD: str = ""
    
    PARTSLINK24_COMPANY_ID: str = ""
    PARTSLINK24_USERNAME: str = ""
    PARTSLINK24_PASSWORD: str = ""

    VENDOR_SSF_ADAPTER_TYPE: Literal["mock", "real", "scraper", "remote"] = "mock"
    TEKMETRIC_ADAPTER_TYPE: Literal["mock", "real"] = "mock"
    
    # Twilio (SMS Notifications)
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_PHONE_NUMBER: str = ""
    
    # Customer Portal
    PORTAL_BASE_URL: str = "http://localhost:3000"
    
    # Vendor Scoring Weights
    VENDOR_PRICE_WEIGHT: float = 0.5
    VENDOR_DISTANCE_WEIGHT: float = 0.3
    VENDOR_QUALITY_WEIGHT: float = 0.2
    
    # Tax Rate
    DEFAULT_TAX_RATE: float = 0.08
    
    # Scraper Microservice (Remote scraping via Windows RDP)
    SCRAPER_SERVICE_URL: str = "http://localhost:5000"
    SCRAPER_API_KEY: str = "estimaro_scraper_secret_2024"
    
    class Config:
        env_file = ".env"
        case_sensitive = True


# Global settings instance
settings = Settings()
