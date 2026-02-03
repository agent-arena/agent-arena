"""Agent API endpoints."""

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from ..db import get_db, Agent, Submission
from .schemas import AgentInfo, AgentCreate, SubmissionInfo

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("/{agent_id}", response_model=AgentInfo)
async def get_agent(agent_id: str, db: Session = Depends(get_db)):
    """Get information about an agent."""
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    
    # Count submissions
    submission_count = db.query(Submission).filter(
        Submission.agent_id == agent_id
    ).count()
    
    # Get best scores per challenge
    best_scores = {}
    best_per_challenge = db.query(
        Submission.challenge_id,
        func.min(Submission.score).label('best_score'),
    ).filter(
        Submission.agent_id == agent_id,
        Submission.status == "scored",
    ).group_by(Submission.challenge_id).all()
    
    for challenge_id, score in best_per_challenge:
        best_scores[challenge_id] = score
    
    return AgentInfo(
        id=agent.id,
        display_name=agent.display_name,
        created_at=agent.created_at,
        is_ai_agent=agent.is_ai_agent,
        submission_count=submission_count,
        best_scores=best_scores,
    )


@router.post("", response_model=AgentInfo)
async def create_agent(agent: AgentCreate, db: Session = Depends(get_db)):
    """Register a new agent."""
    # Check if agent already exists
    existing = db.query(Agent).filter(Agent.id == agent.id).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Agent '{agent.id}' already exists"
        )
    
    db_agent = Agent(
        id=agent.id,
        display_name=agent.display_name,
        is_ai_agent=agent.is_ai_agent,
    )
    db.add(db_agent)
    db.commit()
    db.refresh(db_agent)
    
    return AgentInfo(
        id=db_agent.id,
        display_name=db_agent.display_name,
        created_at=db_agent.created_at,
        is_ai_agent=db_agent.is_ai_agent,
        submission_count=0,
        best_scores={},
    )


@router.get("/{agent_id}/submissions", response_model=list[SubmissionInfo])
async def get_agent_submissions(
    agent_id: str,
    challenge_id: str = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """Get submission history for an agent."""
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    
    query = db.query(Submission).filter(Submission.agent_id == agent_id)
    
    if challenge_id:
        query = query.filter(Submission.challenge_id == challenge_id)
    
    submissions = query.order_by(Submission.created_at.desc()).limit(limit).all()
    
    return submissions
