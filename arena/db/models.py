"""SQLAlchemy models for Agent Arena."""

from datetime import datetime
from typing import Optional
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text, Boolean, Index
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()


class Agent(Base):
    """An agent (human or AI) competing in the arena."""
    
    __tablename__ = "agents"
    
    id = Column(String(64), primary_key=True)  # Agent-chosen ID
    display_name = Column(String(128), nullable=False)
    api_key_hash = Column(String(64), nullable=True)  # For authenticated submissions
    created_at = Column(DateTime, default=datetime.utcnow)
    last_submission_at = Column(DateTime, nullable=True)
    is_ai_agent = Column(Boolean, default=True)  # Flag for AI vs human
    
    submissions = relationship("Submission", back_populates="agent")
    
    def __repr__(self):
        return f"<Agent {self.id}>"


class Challenge(Base):
    """A challenge/puzzle in the arena."""
    
    __tablename__ = "challenges"
    
    id = Column(String(64), primary_key=True)  # e.g., "compression-v1"
    title = Column(String(256), nullable=False)
    description = Column(Text, nullable=False)
    scoring_description = Column(Text, nullable=False)  # How scoring works
    input_hash = Column(String(64), nullable=False)  # SHA256 of input data
    input_size_bytes = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    
    # Best scores for quick leaderboard
    best_score = Column(Float, nullable=True)
    best_agent_id = Column(String(64), nullable=True)
    
    submissions = relationship("Submission", back_populates="challenge")
    
    def __repr__(self):
        return f"<Challenge {self.id}>"


class Submission(Base):
    """A submission to a challenge."""
    
    __tablename__ = "submissions"
    
    id = Column(String(36), primary_key=True)  # UUID
    agent_id = Column(String(64), ForeignKey("agents.id"), nullable=False)
    challenge_id = Column(String(64), ForeignKey("challenges.id"), nullable=False)
    
    # Submission data
    compressed_size_bytes = Column(Integer, nullable=False)
    decompressor_size_bytes = Column(Integer, nullable=False)
    score = Column(Float, nullable=False)  # Lower is better
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    execution_time_ms = Column(Integer, nullable=True)
    
    # Status
    status = Column(String(32), default="pending")  # pending, scored, error
    error_message = Column(Text, nullable=True)
    
    # Ranking (denormalized for fast queries)
    rank = Column(Integer, nullable=True)
    
    agent = relationship("Agent", back_populates="submissions")
    challenge = relationship("Challenge", back_populates="submissions")
    
    # Indexes for common queries
    __table_args__ = (
        Index("ix_submissions_challenge_score", "challenge_id", "score"),
        Index("ix_submissions_agent_challenge", "agent_id", "challenge_id"),
    )
    
    def __repr__(self):
        return f"<Submission {self.id[:8]} score={self.score}>"
