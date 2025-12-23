# FIX: Set Windows event loop policy FIRST before any other imports
import sys
import asyncio

if sys.platform == 'win32':
    # This must be done BEFORE any other async code runs
    # ProactorEventLoop is required for Playwright subprocess spawning
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import logging
import traceback
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create FastAPI application
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Professional Auto Repair Estimation System",
    docs_url="/docs",
    redoc_url="/redoc",
)

# --------------------------------------------------------------------------
# CORS Middleware (Sabse pehle load hona chahiye)
# --------------------------------------------------------------------------
origins = [
    "http://localhost:5173",
    "http://localhost:5174",  # Aapka current frontend
    "http://127.0.0.1:5173",
    "http://127.0.0.1:5174",
    "http://localhost:3000",
    "https://frontend-production-1aae.up.railway.app",
]

# Agar settings mein PORTAL_BASE_URL hai
if hasattr(settings, "PORTAL_BASE_URL") and settings.PORTAL_BASE_URL:
    origins.append(settings.PORTAL_BASE_URL)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------------------------------------------------------
# Database Initialization (Startup Event)
# --------------------------------------------------------------------------
from app.core.database import init_db

@app.on_event("startup")
async def on_startup():
    try:
        logger.info("Connecting to Database...")
        await init_db()
        logger.info("Database Connection Successful!")
    except Exception as e:
        logger.error(f"Database Connection FAILED: {e}")
        # Error log print karein taaki terminal me dikhe
        print(f"CRITICAL DATABASE ERROR: {e}")

# --------------------------------------------------------------------------
# Global Exception Handler (Taaki 500 error pe bhi JSON response mile)
# --------------------------------------------------------------------------
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    error_msg = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    
    # Terminal mein error print karein
    print(f"ERROR OCCURRED AT {request.url.path}:")
    print(error_msg)
    
    try:
        with open("error_log.txt", "a") as f:
            f.write(f"\n--- Error at {request.url} ---\n")
            f.write(error_msg)
    except Exception:
        pass
        
    return JSONResponse(
        status_code=500,
        content={
            "message": "Internal Server Error",
            "detail": str(exc),
            "path": str(request.url)
        }
    )

# --------------------------------------------------------------------------
# Basic Routes
# --------------------------------------------------------------------------
@app.get("/")
async def root():
    return {
        "message": "Estimaro API is running",
        "version": settings.APP_VERSION,
        "docs": "/docs"
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

# --------------------------------------------------------------------------
# API Routers
# --------------------------------------------------------------------------
from app.api.v1 import api_router

app.include_router(api_router, prefix="/api/v1")