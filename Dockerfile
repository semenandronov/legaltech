# Multi-stage build for Python backend + Node.js frontend
FROM python:3.12-slim as python-base

# Install Node.js
RUN apt-get update && apt-get install -y curl && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r backend/requirements.txt

# Build frontend
COPY frontend/package*.json /app/frontend/
WORKDIR /app/frontend
RUN npm install --legacy-peer-deps

COPY frontend/ /app/frontend/
RUN npm run type-check && npm run build

# Copy backend code
WORKDIR /app
COPY backend/ /app/backend/

# Expose port
EXPOSE $PORT

# Start backend server
WORKDIR /app/backend
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}

