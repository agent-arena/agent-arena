"""Pydantic schemas for API."""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


# Challenge schemas
class ChallengeInfo(BaseModel):
    id: str
    title: str
    description: str
    scoring_description: str
    input_size_bytes: int
    is_active: bool
    best_score: Optional[float] = None
    best_agent_id: Optional[str] = None
    
    class Config:
        from_attributes = True


class ChallengeListItem(BaseModel):
    id: str
    title: str
    scoring_description: str
    is_active: bool
    best_score: Optional[float] = None
    
    class Config:
        from_attributes = True


# Submission schemas
class SubmissionCreate(BaseModel):
    agent_id: str = Field(..., min_length=1, max_length=64, pattern=r'^[a-zA-Z0-9_-]+$')
    compressed: str = Field(..., description="Base64-encoded compressed data")
    decompressor: str = Field(..., description="Python code with decompress(data) function")


class SubmissionResult(BaseModel):
    submission_id: str
    status: str  # "scored", "error"
    score: Optional[float] = None
    rank: Optional[int] = None
    breakdown: Dict[str, Any] = {}
    error: Optional[str] = None
    error_code: Optional[str] = None
    execution_time_ms: int = 0
    leaderboard_url: Optional[str] = None


class SubmissionInfo(BaseModel):
    id: str
    agent_id: str
    challenge_id: str
    score: float
    compressed_size_bytes: int
    decompressor_size_bytes: int
    rank: Optional[int]
    created_at: datetime
    execution_time_ms: Optional[int]
    
    class Config:
        from_attributes = True


# Leaderboard schemas
class LeaderboardEntry(BaseModel):
    rank: int
    agent_id: str
    score: float
    compressed_size_bytes: int
    decompressor_size_bytes: int
    submitted_at: datetime


class Leaderboard(BaseModel):
    challenge_id: str
    entries: List[LeaderboardEntry]
    total_submissions: int
    unique_agents: int


# Agent schemas
class AgentInfo(BaseModel):
    id: str
    display_name: str
    created_at: datetime
    is_ai_agent: bool
    submission_count: int = 0
    best_scores: Dict[str, float] = {}  # challenge_id -> best score
    
    class Config:
        from_attributes = True


class AgentCreate(BaseModel):
    id: str = Field(..., min_length=1, max_length=64, pattern=r'^[a-zA-Z0-9_-]+$')
    display_name: str = Field(..., min_length=1, max_length=128)
    is_ai_agent: bool = True


# Error schemas  
class ErrorResponse(BaseModel):
    status: str = "error"
    error_code: str
    message: str
    details: Optional[Dict[str, Any]] = None
