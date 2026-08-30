# curl_cffi ships manylinux wheels, so the slim image needs no compiler toolchain.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Where the JSON store writes. Mount a volume here to keep the raw-page history (and so
# /reparse) across deploys; without one the cache simply rebuilds on demand.
ENV DATA_DIR=/data
RUN mkdir -p /data

EXPOSE 8000

# One worker process: the fetch queue and its pacing are in-process, so a second worker would
# mean two schedulers pacing the same LinkedIn session independently — which is exactly the
# behaviour that gets a session invalidated.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
