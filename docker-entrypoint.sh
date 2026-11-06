#!/bin/sh
set -e

# A bind-mounted ./data is created by Docker as root the first time, while the
# app runs as uid 1001. Make it writable so imports and saves do not fail.
mkdir -p /app/data
chown -R app:app /app/data 2>/dev/null || true

exec gosu app "$@"
