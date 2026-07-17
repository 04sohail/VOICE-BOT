FROM python:3.10-slim

# Install system dependencies (ffmpeg is required for Whisper/Audio processing)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir gunicorn uvicorn

# Copy all source code
COPY . .

# Expose port
EXPOSE 8000

# Command to run Gunicorn with 3 Uvicorn async workers
CMD ["gunicorn", "main:app", "-w", "3", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000"]
