# multi-stage (MEDI-IOT-EyeCare 와 동일 패턴)
FROM python:3.11-slim AS builder
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*
COPY shared-libs-requirements.txt .
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install \
    -r shared-libs-requirements.txt \
    -r requirements.txt

FROM python:3.11-slim AS runtime
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /install /usr/local
ENV PYTHONPATH="/app/shared-libraries:/app"
ENV PYTHONUNBUFFERED=1
COPY . .
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
