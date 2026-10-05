# Synthetic local pilot only. Never use this image for real clinical data.
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements-production.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements-production.lock
COPY pyproject.toml README.md ./
COPY jmoraIs ./jmoraIs
COPY evaluation ./evaluation
COPY services ./services
RUN pip install --no-cache-dir --no-deps -e . && pip install --no-cache-dir pytest==8.3.5
COPY alembic ./alembic
COPY alembic.ini ./
COPY tests ./tests
COPY deploy/local ./deploy/local
