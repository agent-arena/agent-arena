"""Configuration for Agent Arena."""

import os
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = Path(os.getenv("ARENA_DATA_DIR", BASE_DIR / "data"))
DB_PATH = DATA_DIR / "arena.db"
CHALLENGES_DIR = DATA_DIR / "challenges"

# Sandbox limits
SANDBOX_TIMEOUT_SECONDS = int(os.getenv("SANDBOX_TIMEOUT", "60"))
SANDBOX_MEMORY_MB = int(os.getenv("SANDBOX_MEMORY_MB", "512"))
SANDBOX_MAX_OUTPUT_BYTES = int(os.getenv("SANDBOX_MAX_OUTPUT", str(10 * 1024 * 1024)))  # 10MB

# Rate limiting
SUBMISSIONS_PER_HOUR = int(os.getenv("SUBMISSIONS_PER_HOUR", "10"))

# API
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8000"))
