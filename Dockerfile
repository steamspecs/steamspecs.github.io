FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY . /app

RUN mkdir -p /app/.cache/steam /app/data/shards /app/data/catalog/imports

ENTRYPOINT ["sh", "/app/tools/docker/run-scraper.sh"]
