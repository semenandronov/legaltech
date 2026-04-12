# syntax=docker/dockerfile:1
FROM python:3.12-slim

# Install Node.js
RUN apt-get update && apt-get install -y --no-install-recommends curl fonts-dejavu-core && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python: только requirements-core (без Docling/PyTorch — быстрее сборка образа).
# Полный стек: скопировать requirements.txt + requirements-heavy.txt и поставить -r requirements.txt
COPY backend/requirements-core.txt /app/backend/requirements-core.txt
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r backend/requirements-core.txt

# Build frontend
# --mount=type=cache keeps npm cache between builds → only changed packages are re-downloaded
COPY frontend/package*.json /app/frontend/
WORKDIR /app/frontend
RUN --mount=type=cache,target=/root/.npm \
    npm install --legacy-peer-deps --cache /root/.npm

COPY frontend/ /app/frontend/
ENV NODE_OPTIONS="--max_old_space_size=2048"
RUN npm run build

# Copy backend code
WORKDIR /app
COPY backend/ /app/backend/

# Expose port
EXPOSE $PORT

# Start backend server
WORKDIR /app/backend
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
