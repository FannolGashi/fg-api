#!/bin/sh
set -e

# Ensure persistent data dirs exist before dropping privileges
mkdir -p /data/scripts /data/venvs /data/logs /data/db

# If started as root (bind-mount scenario), fix ownership then exec as appuser
if [ "$(id -u)" = "0" ]; then
    chown -R appuser:appgroup /data
    exec gosu appuser uvicorn app.main:app --host 0.0.0.0 --port 8000
else
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000
fi
