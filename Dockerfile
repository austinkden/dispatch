# Use official lightweight Python image
FROM python:3.11-slim

# Install system dependencies: ffmpeg and certificates
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code and default env file
COPY . .

# Run the 24/7 audio stream listener with unbuffered output
CMD ["python", "-u", "slicer.py"]
