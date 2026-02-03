# Agent Arena Dockerfile
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY arena/ arena/

# Create data directory
RUN mkdir -p /app/data

# Environment
ENV ARENA_DATA_DIR=/app/data
ENV API_HOST=0.0.0.0
ENV API_PORT=8000

# Expose port
EXPOSE 8000

# Run
CMD ["python", "-m", "uvicorn", "arena.main:app", "--host", "0.0.0.0", "--port", "8000"]
