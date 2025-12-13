from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings

# Create FastAPI application
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Professional Auto Repair Estimation System",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS Middleware - Allow frontend to communicate with backend
origins = [
    "http://localhost:5173",
    "http://localhost:5174",  # Local Vite
    # Local Vite
    "http://localhost:3000",  # Local fallback
    "https://frontend-production-1aae.up.railway.app",  # Railway Frontend
    settings.PORTAL_BASE_URL,  # Configured URL
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],  # Allow all HTTP methods
    allow_headers=["*"],  # Allow all headers
)


@app.get("/")
async def root():
    """Root endpoint - API health check."""
    return {
        "message": "Estimaro API is running",
        "version": settings.APP_VERSION,
        "docs": "/docs"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring."""
    return {"status": "healthy"}


# Import and include API routers
from app.api.v1 import api_router

app.include_router(api_router, prefix="/api/v1")
