# ============================================================
#  Dockerfile for TeamFlow Backend (FastAPI + PostgreSQL)
# ============================================================

# --- Base image ---
FROM python:3.11-slim AS base

# --- Set work directory ---
WORKDIR /app

# --- Prevent Python from writing .pyc files & enable unbuffered logs ---
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# --- System dependencies ---
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# --- Copy dependency file ---
COPY requirements.txt .

# --- Install dependencies ---
RUN pip install --no-cache-dir -r requirements.txt

# --- Copy the backend code ---
COPY . .

# --- Expose the application port ---
EXPOSE 8000

# --- Set default environment variables ---
ENV ENVIRONMENT=production
ENV DEBUG=False

# --- Run the FastAPI app using Gunicorn + Uvicorn workers ---
CMD ["gunicorn", "main:app", "-k", "uvicorn.workers.UvicornWorker", "--workers", "3", "--bind", "0.0.0.0:8000"]

