#!/bin/sh
set -eu

cd /app

CATALOG_REFRESH_IMPORTS="${CATALOG_REFRESH_IMPORTS:-1}"
SCRAPER_MODE="${SCRAPER_MODE:-resume}"
SCRAPER_DISCOVER="${SCRAPER_DISCOVER:-1}"
SCRAPER_CONCURRENCY="${SCRAPER_CONCURRENCY:-2}"
SCRAPER_REQUEST_DELAY_MS="${SCRAPER_REQUEST_DELAY_MS:-250}"
SCRAPER_LIMIT="${SCRAPER_LIMIT:-}"
SCRAPER_OFFSET="${SCRAPER_OFFSET:-}"
SCRAPER_SHARD_SIZE="${SCRAPER_SHARD_SIZE:-}"
SCRAPER_APPIDS="${SCRAPER_APPIDS:-}"
RUN_INTERVAL_SECONDS="${RUN_INTERVAL_SECONDS:-0}"

run_once() {
  if [ "$CATALOG_REFRESH_IMPORTS" = "1" ]; then
    python tools/python/build_component_catalogs.py --refresh-imports
  else
    python tools/python/build_component_catalogs.py
  fi

  set -- python tools/python/build_steam_data.py

  if [ "$SCRAPER_MODE" = "build-only" ]; then
    set -- "$@" --only-build
  elif [ "$SCRAPER_MODE" = "refresh" ]; then
    set -- "$@" --refresh
  fi

  if [ "$SCRAPER_DISCOVER" = "1" ]; then
    set -- "$@" --discover
  fi

  set -- "$@" --concurrency "$SCRAPER_CONCURRENCY" --request-delay-ms "$SCRAPER_REQUEST_DELAY_MS"

  if [ -n "$SCRAPER_LIMIT" ]; then
    set -- "$@" --limit "$SCRAPER_LIMIT"
  fi

  if [ -n "$SCRAPER_OFFSET" ]; then
    set -- "$@" --offset "$SCRAPER_OFFSET"
  fi

  if [ -n "$SCRAPER_SHARD_SIZE" ]; then
    set -- "$@" --shard-size "$SCRAPER_SHARD_SIZE"
  fi

  if [ -n "$SCRAPER_APPIDS" ]; then
    set -- "$@" --appids "$SCRAPER_APPIDS"
  fi

  "$@"
}

if [ "$RUN_INTERVAL_SECONDS" -gt 0 ] 2>/dev/null; then
  while true; do
    if ! run_once; then
      echo "Scrape cycle failed; retrying after ${RUN_INTERVAL_SECONDS}s" >&2
    fi
    sleep "$RUN_INTERVAL_SECONDS"
  done
else
  run_once
fi
