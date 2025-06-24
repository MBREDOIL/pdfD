FROM python:3.9-slim-buster

WORKDIR /app

# Install required system dependencies
RUN apt-get update && \
    apt-get install -y \
    wget \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install FFmpeg for thumbnail handling
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements file first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create downloads directory
RUN mkdir -p downloads

# Start the bot
CMD ["python", "-u", "main.py"]
