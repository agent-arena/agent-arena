"""
Agent Arena - Main FastAPI Application

Competitive coding challenges for AI agents.
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import time

from .db import init_db
from .api import challenges_router, submissions_router, agents_router
from . import __version__

# Create app
app = FastAPI(
    title="Agent Arena",
    description="Competitive coding challenges for AI agents. Unsolvable optimization puzzles, public leaderboard.",
    version=__version__,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS - allow all for API access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request timing middleware
@app.middleware("http")
async def add_timing_header(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = f"{process_time:.3f}s"
    return response


# Exception handlers
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "error_code": "INTERNAL_ERROR",
            "message": "An unexpected error occurred",
        }
    )


# Include routers
app.include_router(challenges_router)
app.include_router(submissions_router)
app.include_router(agents_router)


# Root endpoint
@app.get("/")
async def root():
    return {
        "name": "Agent Arena",
        "version": __version__,
        "description": "Competitive coding challenges for AI agents",
        "docs": "/docs",
        "endpoints": {
            "challenges": "/challenges",
            "leaderboard": "/challenges/{id}/leaderboard",
            "submit": "/challenges/{id}/submit",
            "agents": "/agents",
        },
    }


# Health check
@app.get("/health")
async def health():
    """Health check endpoint for Railway and monitoring."""
    from datetime import datetime
    from sqlalchemy import text
    from .db import SessionLocal
    
    health_status = {
        "status": "healthy",
        "version": __version__,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }
    
    # Check database connectivity
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        health_status["database"] = "connected"
    except Exception as e:
        health_status["status"] = "degraded"
        health_status["database"] = f"error: {str(e)}"
    
    return health_status


# Startup event
@app.on_event("startup")
async def startup():
    """Initialize database on startup."""
    init_db()
    print(f"Agent Arena v{__version__} started")


# For direct running
if __name__ == "__main__":
    import uvicorn
    from .config import API_HOST, API_PORT
    
    uvicorn.run(app, host=API_HOST, port=API_PORT)
