# Synthetic local pilot only. Never use this image for real clinical data.
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# Local OCR for photographed/scanned reports (Portuguese); images never go to the AI.
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-por poppler-utils \
    && rm -rf /var/lib/apt/lists/*
COPY requirements-production.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements-production.lock
# Optional Claude SDK for the local evidence workbench (pinned; not in the production lock).
RUN pip install --no-cache-dir anthropic==1.11.0 pypdf==6.19.0 && pip check
COPY pyproject.toml README.md ./
COPY jmoraIs ./jmoraIs
COPY evaluation ./evaluation
COPY services ./services
RUN pip install --no-cache-dir --no-deps -e . && pip install --no-cache-dir pytest==8.3.5
COPY alembic ./alembic
COPY alembic.ini ./
COPY tests ./tests
COPY deploy/local ./deploy/local
# Least privilege: the application never runs as root inside the container.
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin jmorais
USER 10001
