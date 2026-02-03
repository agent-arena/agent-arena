"""API routes."""

from .challenges import router as challenges_router
from .submissions import router as submissions_router
from .agents import router as agents_router

__all__ = ["challenges_router", "submissions_router", "agents_router"]
