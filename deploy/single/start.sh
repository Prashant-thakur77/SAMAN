#!/bin/bash
# One container, two processes: the API on the loopback and Caddy in front of
# it on $PORT. If either dies the script exits, so the host restarts the
# container instead of serving a site whose API has gone.
set -e
cd /srv/backend
uvicorn app.main:app --host 127.0.0.1 --port 8000 &
caddy run --config /etc/caddy/Caddyfile --adapter caddyfile &
trap 'kill 0' EXIT INT TERM
wait -n
