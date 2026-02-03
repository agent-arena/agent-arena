"""Challenge API endpoints."""

from fastapi import APIRouter, HTTPException, Depends, Response
from sqlalchemy.orm import Session

from ..db import get_db, Challenge
from ..challenges import CompressionChallenge
from .schemas import ChallengeInfo, ChallengeListItem

router = APIRouter(prefix="/challenges", tags=["challenges"])

# Challenge registry
CHALLENGES = {
    "compression-v1": CompressionChallenge(),
}


def get_challenge(challenge_id: str):
    """Get challenge by ID or raise 404."""
    if challenge_id not in CHALLENGES:
        raise HTTPException(status_code=404, detail=f"Challenge '{challenge_id}' not found")
    return CHALLENGES[challenge_id]


@router.get("", response_model=list[ChallengeListItem])
async def list_challenges(db: Session = Depends(get_db)):
    """List all active challenges."""
    # Ensure challenges are in DB
    for challenge_id, challenge in CHALLENGES.items():
        existing = db.query(Challenge).filter(Challenge.id == challenge_id).first()
        if not existing:
            # Initialize challenge in DB
            db_challenge = Challenge(
                id=challenge.id,
                title=challenge.title,
                description=challenge.description,
                scoring_description=challenge.scoring_description,
                input_hash=challenge.get_input_hash(),
                input_size_bytes=len(challenge.get_input_data()),
                is_active=True,
            )
            db.add(db_challenge)
            db.commit()
    
    challenges = db.query(Challenge).filter(Challenge.is_active == True).all()
    return challenges


@router.get("/{challenge_id}", response_model=ChallengeInfo)
async def get_challenge_info(challenge_id: str, db: Session = Depends(get_db)):
    """Get detailed information about a challenge."""
    challenge = get_challenge(challenge_id)
    
    db_challenge = db.query(Challenge).filter(Challenge.id == challenge_id).first()
    if not db_challenge:
        # Create it
        db_challenge = Challenge(
            id=challenge.id,
            title=challenge.title,
            description=challenge.description,
            scoring_description=challenge.scoring_description,
            input_hash=challenge.get_input_hash(),
            input_size_bytes=len(challenge.get_input_data()),
            is_active=True,
        )
        db.add(db_challenge)
        db.commit()
        db.refresh(db_challenge)
    
    return db_challenge


@router.get("/{challenge_id}/input")
async def get_challenge_input(challenge_id: str):
    """Download the challenge input data."""
    challenge = get_challenge(challenge_id)
    data = challenge.get_input_data()
    
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename={challenge_id}-input.bin",
            "X-Input-Hash": challenge.get_input_hash(),
            "X-Input-Size": str(len(data)),
        }
    )


@router.get("/{challenge_id}/input/hash")
async def get_challenge_input_hash(challenge_id: str):
    """Get the hash of the challenge input (for verification)."""
    challenge = get_challenge(challenge_id)
    return {
        "challenge_id": challenge_id,
        "hash": challenge.get_input_hash(),
        "algorithm": "sha256",
        "size_bytes": len(challenge.get_input_data()),
    }
