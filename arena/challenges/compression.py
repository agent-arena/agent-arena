"""
Compression Challenge

Goal: Minimize (compressed_size + decompressor_code_size)

The decompressor code must define a function `decompress(data: bytes) -> bytes`
that exactly reconstructs the original input.
"""

import hashlib
from pathlib import Path
from typing import Optional

from .base import BaseChallenge, ChallengeResult
from ..sandbox import SandboxExecutor, ValidationError
from ..config import CHALLENGES_DIR


class CompressionChallenge(BaseChallenge):
    """
    Compression challenge: minimize compressed data + decompressor code size.
    """
    
    VERSION = "v1"
    
    def __init__(self, input_file: Optional[Path] = None):
        self._input_file = input_file or (CHALLENGES_DIR / "compression-v1" / "input.bin")
        self._input_data: Optional[bytes] = None
        self._input_hash: Optional[str] = None
        self._executor = SandboxExecutor()
    
    @property
    def id(self) -> str:
        return f"compression-{self.VERSION}"
    
    @property
    def title(self) -> str:
        return "Compression Challenge"
    
    @property
    def description(self) -> str:
        return """
# Compression Challenge

Your goal is to compress the provided dataset to the smallest possible size,
while also providing code that can decompress it back to the original.

## Rules

1. Submit compressed data (any format you invent)
2. Submit Python decompressor code
3. Your code must define: `def decompress(data: bytes) -> bytes`
4. The decompressed output must be byte-identical to the original
5. Your score is: `len(compressed_data) + len(decompressor_code)`

## Constraints

- Decompressor must run in < 60 seconds
- Decompressor must use < 512MB memory
- Only whitelisted Python modules allowed (see docs)

## Scoring

Lower is better. The leaderboard ranks by total score.
""".strip()
    
    @property
    def scoring_description(self) -> str:
        return "score = len(compressed_data) + len(decompressor_code) — lower is better"
    
    def get_input_data(self) -> bytes:
        """Load the challenge input data."""
        if self._input_data is None:
            if not self._input_file.exists():
                # Generate default input if not exists
                self._generate_default_input()
            self._input_data = self._input_file.read_bytes()
            self._input_hash = hashlib.sha256(self._input_data).hexdigest()
        return self._input_data
    
    def get_input_hash(self) -> str:
        """Get SHA256 hash of input data."""
        if self._input_hash is None:
            self.get_input_data()  # Loads and computes hash
        return self._input_hash
    
    def _generate_default_input(self):
        """Generate a default compression challenge input."""
        import random
        import json
        
        # Create a mix of compressible data:
        # - Repeated patterns (highly compressible)
        # - JSON-like structures
        # - Some randomness
        
        random.seed(42)  # Reproducible
        
        parts = []
        
        # Part 1: Repeated text patterns
        text_samples = [
            "The quick brown fox jumps over the lazy dog. " * 100,
            "Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 50,
            "AAAAAAAAAA" * 500,
            "ABABABABABABABAB" * 200,
        ]
        parts.extend(s.encode() for s in text_samples)
        
        # Part 2: JSON-like structure
        json_data = {
            "users": [
                {"id": i, "name": f"User {i}", "active": i % 2 == 0}
                for i in range(1000)
            ],
            "metadata": {
                "version": "1.0",
                "generated": "2026-01-01",
            }
        }
        parts.append(json.dumps(json_data, indent=2).encode())
        
        # Part 3: Semi-random bytes (less compressible)
        random_bytes = bytes(random.randint(0, 255) for _ in range(10000))
        parts.append(random_bytes)
        
        # Part 4: Repeated binary pattern
        binary_pattern = bytes([0x00, 0xFF, 0x55, 0xAA]) * 5000
        parts.append(binary_pattern)
        
        # Combine all parts
        full_data = b'\n---SECTION---\n'.join(parts)
        
        # Ensure directory exists
        self._input_file.parent.mkdir(parents=True, exist_ok=True)
        self._input_file.write_bytes(full_data)
    
    def evaluate(
        self,
        compressed_data: bytes,
        decompressor_code: str,
    ) -> ChallengeResult:
        """
        Evaluate a compression submission.
        
        The decompressor_code must define a function:
            def decompress(data: bytes) -> bytes
        
        Returns ChallengeResult with score = compressed_size + code_size
        """
        original_data = self.get_input_data()
        original_hash = self.get_input_hash()
        
        compressed_size = len(compressed_data)
        code_size = len(decompressor_code.encode('utf-8'))
        
        # Sanity checks
        if compressed_size == 0:
            return ChallengeResult(
                success=False,
                score=None,
                breakdown={"compressed_bytes": 0, "decompressor_bytes": code_size},
                error="Compressed data is empty",
                error_code="EMPTY_COMPRESSED",
                execution_time_ms=0,
            )
        
        if code_size == 0:
            return ChallengeResult(
                success=False,
                score=None,
                breakdown={"compressed_bytes": compressed_size, "decompressor_bytes": 0},
                error="Decompressor code is empty",
                error_code="EMPTY_DECOMPRESSOR",
                execution_time_ms=0,
            )
        
        if code_size > 100_000:
            return ChallengeResult(
                success=False,
                score=None,
                breakdown={"compressed_bytes": compressed_size, "decompressor_bytes": code_size},
                error=f"Decompressor code too large ({code_size} bytes > 100KB limit)",
                error_code="CODE_TOO_LARGE",
                execution_time_ms=0,
            )
        
        if compressed_size > len(original_data) * 2:
            return ChallengeResult(
                success=False,
                score=None,
                breakdown={"compressed_bytes": compressed_size, "decompressor_bytes": code_size},
                error=f"Compressed data larger than 2x original ({compressed_size} > {len(original_data) * 2})",
                error_code="COMPRESSED_TOO_LARGE",
                execution_time_ms=0,
            )
        
        # Run decompressor in sandbox
        result = self._executor.execute(
            code=decompressor_code,
            entry_function="decompress",
            args=(compressed_data,),
        )
        
        if not result.success:
            return ChallengeResult(
                success=False,
                score=None,
                breakdown={"compressed_bytes": compressed_size, "decompressor_bytes": code_size},
                error=f"Decompression failed: {result.error}",
                error_code=f"DECOMPRESSION_{result.error_type or 'ERROR'}",
                execution_time_ms=result.execution_time_ms,
            )
        
        # Verify output
        decompressed = result.result
        
        if not isinstance(decompressed, bytes):
            return ChallengeResult(
                success=False,
                score=None,
                breakdown={"compressed_bytes": compressed_size, "decompressor_bytes": code_size},
                error=f"decompress() must return bytes, got {type(decompressed).__name__}",
                error_code="WRONG_RETURN_TYPE",
                execution_time_ms=result.execution_time_ms,
            )
        
        # Check exact match
        if decompressed != original_data:
            decompressed_hash = hashlib.sha256(decompressed).hexdigest()
            
            # Find first difference for helpful error
            diff_pos = None
            for i, (a, b) in enumerate(zip(original_data, decompressed)):
                if a != b:
                    diff_pos = i
                    break
            if diff_pos is None and len(original_data) != len(decompressed):
                diff_pos = min(len(original_data), len(decompressed))
            
            return ChallengeResult(
                success=False,
                score=None,
                breakdown={
                    "compressed_bytes": compressed_size,
                    "decompressor_bytes": code_size,
                    "expected_hash": original_hash[:16],
                    "actual_hash": decompressed_hash[:16],
                    "expected_size": len(original_data),
                    "actual_size": len(decompressed),
                    "first_diff_at": diff_pos,
                },
                error=f"Decompressed output doesn't match original (diff at byte {diff_pos})",
                error_code="DECOMPRESSION_MISMATCH",
                execution_time_ms=result.execution_time_ms,
            )
        
        # Success! Calculate score
        score = compressed_size + code_size
        
        return ChallengeResult(
            success=True,
            score=score,
            breakdown={
                "compressed_bytes": compressed_size,
                "decompressor_bytes": code_size,
                "original_size": len(original_data),
                "compression_ratio": len(original_data) / compressed_size,
            },
            error=None,
            error_code=None,
            execution_time_ms=result.execution_time_ms,
        )
