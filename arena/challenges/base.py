"""Base challenge interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class ChallengeResult:
    """Result of evaluating a submission."""
    success: bool
    score: Optional[float]  # Lower is better, None if failed
    breakdown: dict  # Score components
    error: Optional[str]
    error_code: Optional[str]  # Machine-readable error code
    execution_time_ms: int


class BaseChallenge(ABC):
    """Base class for all challenges."""
    
    @property
    @abstractmethod
    def id(self) -> str:
        """Unique identifier for this challenge."""
        pass
    
    @property
    @abstractmethod
    def title(self) -> str:
        """Human-readable title."""
        pass
    
    @property
    @abstractmethod
    def description(self) -> str:
        """Full description of the challenge."""
        pass
    
    @property
    @abstractmethod
    def scoring_description(self) -> str:
        """Explanation of how scoring works."""
        pass
    
    @abstractmethod
    def get_input_data(self) -> bytes:
        """Get the input data for this challenge."""
        pass
    
    @abstractmethod
    def evaluate(
        self,
        compressed_data: bytes,
        decompressor_code: str,
    ) -> ChallengeResult:
        """
        Evaluate a submission.
        
        Args:
            compressed_data: The compressed data submitted
            decompressor_code: Python code that defines a decompress() function
        
        Returns:
            ChallengeResult with score and details
        """
        pass
