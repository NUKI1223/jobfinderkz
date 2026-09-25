FROM denoland/deno:bin-2.9.6 AS deno
FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY --from=deno /deno /usr/local/bin/deno
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements*.txt ./
RUN pip install --upgrade pip==26.2.1 && pip install -r requirements.txt -c requirements.lock.txt
COPY . .
RUN useradd --create-home worker && mkdir /storage && chown worker:worker /storage
USER worker
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
