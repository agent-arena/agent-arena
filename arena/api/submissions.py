"""Async Submission API - submit returns immediately, poll for results."""

import base64
import uuid
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import func

from ..db import get_db, Agent, Challenge, Submission
from ..challenges import CompressionChallenge
from ..config import SUBMISSIONS_PER_HOUR
from .schemas import SubmissionCreate, SubmissionResult, Leaderboard, LeaderboardEntry
from .challenges import CHALLENGES, get_challenge

router = APIRouter(prefix="/challenges", tags=["submissions"])


# ============ Helper Functions ============

def get_or_create_agent(db: Session, agent_id: str) -> Agent:
    """Get existing agent or create a new one."""
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        agent = Agent(
            id=agent_id,
            display_name=agent_id,
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
                "message": f"Rate limit exceeded. Max {SUBMISSIONS_PER_HOUR} submissions per hour.",
                "retry_after_seconds": 3600,
            }
        )


def update_leaderboard_ranks(db: Session, challenge_id: str) -> None:
    """Update rank for all submissions in a challenge."""
    submissions = db.query(Submission).filter(
        Submission.challenge_id == challenge_id,
        Submission.status == "scored",
    ).order_by(Submission.score.asc()).all()
    
    current_rank = 1
    prev_score = None
    for i, sub in enumerate(submissions):
        if prev_score is not None and sub.score > prev_score:
            current_rank = i + 1
        sub.rank = current_rank
        prev_score = sub.score
    
    if submissions:
        best = submissions[0]
        challenge = db.query(Challenge).filter(Challenge.id == challenge_id).first()
        if challenge:
            challenge.best_score = best.score
            challenge.best_agent_id = best.agent_id
    
    db.commit()


# ============ Background Task ============

def process_submission(
    submission_id: str,
    challenge_id: str,
    compressed_data: bytes,
    decompressor_code: str,
):
    """Background task to evaluate submission."""
    from ..db import SessionLocal
    
    db = SessionLocal()
    try:
        # Get submission record
        submission = db.query(Submission).filter(Submission.id == submission_id).first()
        if not submission:
            return
        
        # Update status to processing
        submission.status = "processing"
        db.commit()
        
        # Run evaluation
        challenge_impl = get_challenge(challenge_id)
        result = challenge_impl.evaluate(compressed_data, decompressor_code)
        
        # Update submission with results
        submission.score = result.score or 0
        submission.status = "scored" if result.success else "error"
        submission.error_message = result.error
        submission.execution_time_ms = result.execution_time_ms
        
        # Store breakdown as JSON in a new field (or error details)
        # submission.result_data = result.breakdown  # if you add this field
        
        db.commit()
        
        # Update leaderboard if successful
        if result.success:
            update_leaderboard_ranks(db, challenge_id)
            
    except Exception as e:
        # Mark as error
        submission = db.query(Submission).filter(Submission.id == submission_id).first()
        if submission:
            submission.status = "error"
            submission.error_message = f"Internal error: {str(e)}"
            db.commit()
    finally:
        db.close()


# ============ Endpoints ============

@router.post("/{challenge_id}/submit")
async def submit_solution(
    challenge_id: str,
    submission: SubmissionCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Submit a solution to a challenge.
    
    Returns immediately with a submission_id. Poll GET /submissions/{id} for results.
    
    Status flow: pending → processing → scored/error
    """
    # Validate challenge exists
    challenge_impl = get_challenge(challenge_id)
    
    # Get or create agent
    agent = get_or_create_agent(db, submission.agent_id)
    
    # Check rate limit
    check_rate_limit(db, submission.agent_id, challenge_id)
    
    # Decode compressed data (validate early)
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
    
    # Create submission record with pending status
    submission_id = str(uuid.uuid4())
    db_submission = Submission(
        id=submission_id,
        agent_id=submission.agent_id,
        challenge_id=challenge_id,
        compressed_size_bytes=len(compressed_data),
        decompressor_size_bytes=len(submission.decompressor.encode('utf-8')),
        score=0,
        status="pending",  # Will be updated by background task
        error_message=None,
        execution_time_ms=0,
    )
    db.add(db_submission)
    agent.last_submission_at = datetime.utcnow()
    db.commit()
    
    # Queue background evaluation
    background_tasks.add_task(
        process_submission,
        submission_id,
        challenge_id,
        compressed_data,
        submission.decompressor,
    )
    
    # Return immediately
    return {
        "submission_id": submission_id,
        "status": "pending",
        "message": "Submission queued for evaluation",
        "poll_url": f"/submissions/{submission_id}",
    }


@router.get("/submissions/{submission_id}")
async def get_submission_status(
    submission_id: str,
    db: Session = Depends(get_db),
):
    """
    Get the status and results of a submission.
    
    Poll this endpoint until status is 'scored' or 'error'.
    """
    submission = db.query(Submission).filter(Submission.id == submission_id).first()
    
    if not submission:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "NOT_FOUND", "message": "Submission not found"}
        )
    
    response = {
        "submission_id": submission.id,
        "status": submission.status,
        "agent_id": submission.agent_id,
        "challenge_id": submission.challenge_id,
        "created_at": submission.created_at.isoformat(),
    }
    
    # Add results if complete
    if submission.status in ("scored", "error"):
        response.update({
            "score": submission.score if submission.status == "scored" else None,
            "rank": submission.rank,
            "breakdown": {
                "compressed_bytes": submission.compressed_size_bytes,
                "decompressor_bytes": submission.decompressor_size_bytes,
            },
            "execution_time_ms": submission.execution_time_ms,
            "error": submission.error_message,
            "leaderboard_url": f"/challenges/{submission.challenge_id}/leaderboard",
        })
    
    return response


# Keep existing leaderboard endpoint
@router.get("/{challenge_id}/leaderboard", response_model=Leaderboard)
async def get_leaderboard(
    challenge_id: str,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """Get the leaderboard for a challenge."""
    get_challenge(challenge_id)
    
    best_per_agent = db.query(
        Submission.agent_id,
        func.min(Submission.score).label('best_score'),
    ).filter(
        Submission.challenge_id == challenge_id,
        Submission.status == "scored",
    ).group_by(Submission.agent_id).subquery()
    
    submissions = db.query(Submission).join(
        best_per_agent,
        (Submission.agent_id == best_per_agent.c.agent_id) &
        (Submission.score == best_per_agent.c.best_score)
    ).filter(
        Submission.challenge_id == challenge_id,
        Submission.status == "scored",
    ).order_by(Submission.score.asc()).limit(limit).all()
    
    entries = [
        LeaderboardEntry(
            rank=i + 1,
            agent_id=sub.agent_id,
            score=sub.score,
            compressed_size_bytes=sub.compressed_size_bytes,
            decompressor_size_bytes=sub.decompressor_size_bytes,
            submitted_at=sub.created_at,
        )
        for i, sub in enumerate(submissions)
    ]
    
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
