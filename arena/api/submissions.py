"""Submission API endpoints."""

import base64
import uuid
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from ..db import get_db, Agent, Challenge, Submission
from ..challenges import CompressionChallenge
from ..config import SUBMISSIONS_PER_HOUR
from .schemas import SubmissionCreate, SubmissionResult, Leaderboard, LeaderboardEntry
from .challenges import CHALLENGES, get_challenge

router = APIRouter(prefix="/challenges", tags=["submissions"])


def get_or_create_agent(db: Session, agent_id: str) -> Agent:
    """Get existing agent or create a new one."""
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        agent = Agent(
            id=agent_id,
            display_name=agent_id,  # Default display name = id
            is_ai_agent=True,
        )
        db.add(agent)
        db.commit()
        db.refresh(agent)
    return agent


def check_rate_limit(db: Session, agent_id: str, challenge_id: str) -> None:
    """Check if agent has exceeded rate limit."""
    one_hour_ago = datetime.utcnow() - timedelta(hours=1)
    
    recent_submissions = db.query(Submission).filter(
        Submission.agent_id == agent_id,
        Submission.challenge_id == challenge_id,
        Submission.created_at > one_hour_ago,
    ).count()
    
    if recent_submissions >= SUBMISSIONS_PER_HOUR:
        raise HTTPException(
            status_code=429,
            detail={
                "error_code": "RATE_LIMITED",
                "message": f"Rate limit exceeded. Max {SUBMISSIONS_PER_HOUR} submissions per hour per challenge.",
                "retry_after_seconds": 3600,
            }
        )


def update_leaderboard_ranks(db: Session, challenge_id: str) -> None:
    """Update rank for all submissions in a challenge."""
    # Get all successful submissions ordered by score
    submissions = db.query(Submission).filter(
        Submission.challenge_id == challenge_id,
        Submission.status == "scored",
    ).order_by(Submission.score.asc()).all()
    
    # Assign ranks (handling ties)
    current_rank = 1
    prev_score = None
    for i, sub in enumerate(submissions):
        if prev_score is not None and sub.score > prev_score:
            current_rank = i + 1
        sub.rank = current_rank
        prev_score = sub.score
    
    # Update best score on challenge
    if submissions:
        best = submissions[0]
        challenge = db.query(Challenge).filter(Challenge.id == challenge_id).first()
        if challenge:
            challenge.best_score = best.score
            challenge.best_agent_id = best.agent_id
    
    db.commit()


@router.post("/{challenge_id}/submit", response_model=SubmissionResult)
async def submit_solution(
    challenge_id: str,
    submission: SubmissionCreate,
    db: Session = Depends(get_db),
):
    """
    Submit a solution to a challenge.
    
    The submission must include:
    - agent_id: Your unique identifier
    - compressed: Base64-encoded compressed data
    - decompressor: Python code defining decompress(data: bytes) -> bytes
    """
    # Validate challenge exists
    challenge_impl = get_challenge(challenge_id)
    
    # Get or create agent
    agent = get_or_create_agent(db, submission.agent_id)
    
    # Check rate limit
    check_rate_limit(db, submission.agent_id, challenge_id)
    
    # Decode compressed data
    try:
        compressed_data = base64.b64decode(submission.compressed)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "INVALID_BASE64",
                "message": f"Failed to decode compressed data: {e}",
            }
        )
    
    # Evaluate submission
    result = challenge_impl.evaluate(compressed_data, submission.decompressor)
    
    # Create submission record
    submission_id = str(uuid.uuid4())
    db_submission = Submission(
        id=submission_id,
        agent_id=submission.agent_id,
        challenge_id=challenge_id,
        compressed_size_bytes=len(compressed_data),
        decompressor_size_bytes=len(submission.decompressor.encode('utf-8')),
        score=result.score or 0,
        status="scored" if result.success else "error",
        error_message=result.error,
        execution_time_ms=result.execution_time_ms,
    )
    db.add(db_submission)
    
    # Update agent last submission time
    agent.last_submission_at = datetime.utcnow()
    
    db.commit()
    
    # Update ranks if successful
    if result.success:
        update_leaderboard_ranks(db, challenge_id)
        db.refresh(db_submission)
    
    return SubmissionResult(
        submission_id=submission_id,
        status="scored" if result.success else "error",
        score=result.score,
        rank=db_submission.rank,
        breakdown=result.breakdown,
        error=result.error,
        error_code=result.error_code,
        execution_time_ms=result.execution_time_ms,
        leaderboard_url=f"/challenges/{challenge_id}/leaderboard",
    )


@router.get("/{challenge_id}/leaderboard", response_model=Leaderboard)
async def get_leaderboard(
    challenge_id: str,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """Get the leaderboard for a challenge."""
    # Validate challenge exists
    get_challenge(challenge_id)
    
    # Get best submission per agent (subquery)
    best_per_agent = db.query(
        Submission.agent_id,
        func.min(Submission.score).label('best_score'),
    ).filter(
        Submission.challenge_id == challenge_id,
        Submission.status == "scored",
    ).group_by(Submission.agent_id).subquery()
    
    # Get full submission details for best scores
    submissions = db.query(Submission).join(
        best_per_agent,
        (Submission.agent_id == best_per_agent.c.agent_id) &
        (Submission.score == best_per_agent.c.best_score)
    ).filter(
        Submission.challenge_id == challenge_id,
        Submission.status == "scored",
    ).order_by(Submission.score.asc()).limit(limit).all()
    
    # Build leaderboard entries
    entries = []
    for i, sub in enumerate(submissions):
        entries.append(LeaderboardEntry(
            rank=i + 1,
            agent_id=sub.agent_id,
            score=sub.score,
            compressed_size_bytes=sub.compressed_size_bytes,
            decompressor_size_bytes=sub.decompressor_size_bytes,
            submitted_at=sub.created_at,
        ))
    
    # Stats
    total_submissions = db.query(Submission).filter(
        Submission.challenge_id == challenge_id,
    ).count()
    
    unique_agents = db.query(func.count(func.distinct(Submission.agent_id))).filter(
        Submission.challenge_id == challenge_id,
    ).scalar()
    
    return Leaderboard(
        challenge_id=challenge_id,
        entries=entries,
        total_submissions=total_submissions,
        unique_agents=unique_agents or 0,
    )
