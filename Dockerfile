# syntax=docker/dockerfile:1
FROM python:3.12-slim

# Install Node.js
RUN apt-get update && apt-get install -y --no-install-recommends curl fonts-dejavu-core && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python: полный стек как в локале (requirements.txt = core + heavy).
# Включает Docling/PyTorch (CPU wheels) через extra-index-url внутри requirements.txt.
COPY backend/requirements.txt /app/backend/requirements.txt
COPY backend/requirements-core.txt /app/backend/requirements-core.txt
COPY backend/requirements-heavy.txt /app/backend/requirements-heavy.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip && \
    pip install -r backend/requirements.txt

# Build frontend
# --mount=type=cache keeps npm cache between builds → only changed packages are re-downloaded
COPY frontend/package*.json /app/frontend/
WORKDIR /app/frontend
RUN --mount=type=cache,target=/root/.npm \
    npm install --legacy-peer-deps --cache /root/.npm

COPY frontend/ /app/frontend/
# Vite envDir = /app (см. frontend/vite.config.ts). Файл кладёт vm-deploy-build-on-vm.sh
COPY .env.vite-build /app/.env
# Дублируем через ARG для совместимости с docker build --build-arg
ARG VITE_GOOGLE_CLIENT_ID=
ARG VITE_GOOGLE_API_KEY=
ENV VITE_GOOGLE_CLIENT_ID="${VITE_GOOGLE_CLIENT_ID}" \
    VITE_GOOGLE_API_KEY="${VITE_GOOGLE_API_KEY}"
ENV NODE_OPTIONS="--max_old_space_size=2048"
RUN npm run build

# Copy backend code
WORKDIR /app
COPY backend/ /app/backend/

# Expose port (App Platform port discovery needs a concrete number)
EXPOSE 8000

# Start backend server
WORKDIR /app/backend
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
