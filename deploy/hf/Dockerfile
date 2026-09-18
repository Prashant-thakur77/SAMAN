# SAMAN as one container, for hosts that run a single image on a single port
# and keep it running without a laptop: Hugging Face Spaces (Docker), Render,
# Koyeb, Fly. The frontend is built and served by Caddy, the API sits behind it
# on the loopback, and the demo database is generated at build time so the
# container answers the moment it starts and needs no volume. Anything written
# at runtime (decisions, uploads) lives only as long as the container does.
#
#   docker build -f deploy/hf/Dockerfile -t saman-one .        # from a clone
#   docker run --rm -p 7860:7860 -e SAMAN_SECURE_COOKIES=false saman-one
#
# On Hugging Face the Space repository holds only this file and deploy/hf/README.md;
# the source is then cloned from GitHub at build time (SAMAN_REPO / SAMAN_REF).

ARG SAMAN_REPO=https://github.com/Prashant-thakur77/SAMAN.git
ARG SAMAN_REF=main

# --- source: the build context when it is the repository, GitHub otherwise ---
FROM alpine/git:latest AS source
ARG SAMAN_REPO
ARG SAMAN_REF
COPY . /ctx
RUN if [ -f /ctx/backend/requirements.txt ]; then cp -r /ctx /src; \
    else git clone --depth 1 --branch "$SAMAN_REF" "$SAMAN_REPO" /src; fi

# --- web: the production frontend build ---
FROM node:22-slim AS web
WORKDIR /src
COPY --from=source /src/frontend/package.json /src/frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund
COPY --from=source /src/frontend/ ./
RUN npm run build

# --- app: API + Caddy + baked demo data ---
FROM python:3.12-slim

# "voice" adds local speech recognition, synthesis and the OCR reader, with
# their model files fetched at build time. "none" keeps the image small; every
# screen still works on the browser's engines.
ARG SAMAN_EXTRAS=voice

RUN apt-get update && apt-get install --no-install-recommends -y ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=caddy:2-alpine /usr/bin/caddy /usr/bin/caddy

# Hugging Face runs the container as uid 1000; everything it must write is
# owned by that user from the start.
RUN useradd -m -u 1000 saman && mkdir -p /srv/data /srv/caddy /etc/caddy \
    && chown -R saman:saman /srv /etc/caddy
WORKDIR /srv

COPY --from=source /src/backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --timeout 180 --retries 8 -r requirements.txt
RUN if [ "$SAMAN_EXTRAS" = "voice" ]; then \
      apt-get update && apt-get install --no-install-recommends -y libxcb1 libglib2.0-0 libgl1 \
        && rm -rf /var/lib/apt/lists/* \
        && pip install --no-cache-dir --timeout 180 --retries 8 \
          faster-whisper==1.2.1 piper-tts==1.7.0 rapidocr-onnxruntime==1.4.4 ; \
    fi

COPY --from=source --chown=saman:saman /src/backend/ ./backend/
# The assistant answers from the project's own documents.
COPY --from=source --chown=saman:saman /src/README.md /src/KNOWN_GAPS.md /src/SAMAN_CLAUDE_CODE_SPEC.md ./
COPY --from=source --chown=saman:saman /src/docs/*.md ./docs/
COPY --from=web --chown=saman:saman /src/dist /srv/www
COPY --from=source --chown=saman:saman /src/deploy/hf/Caddyfile /etc/caddy/Caddyfile
COPY --from=source --chown=saman:saman /src/deploy/hf/start.sh /srv/start.sh
RUN chmod +x /srv/start.sh

USER saman
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SAMAN_DB_PATH=/srv/data/app.db \
    SAMAN_TIER1_ENGINE=rapidfuzz \
    SAMAN_OLLAMA_AUTODETECT=false \
    SAMAN_SECURE_COOKIES=true \
    XDG_DATA_HOME=/srv/caddy \
    XDG_CONFIG_HOME=/srv/caddy \
    PORT=7860
WORKDIR /srv/backend

# Speech models beside the database, where the API looks for them.
RUN if [ "$SAMAN_EXTRAS" = "voice" ]; then \
      HF_HUB_DISABLE_XET=1 python -c "from huggingface_hub import snapshot_download; snapshot_download('Systran/faster-whisper-base', local_dir='/srv/data/models/whisper-base', allow_patterns=['*.bin','*.json','*.txt','*.model'])" \
      && python -m piper.download_voices --download-dir /srv/data/models/piper en_US-arctic-medium ; \
    fi

# The demo estate: seed, pipeline, registry activity, simulated labels, the
# learned model, and the held-out gate. A gate failure fails the build — a
# hosted demo that quietly ships a broken pipeline is worse than no demo.
RUN python -m app.cli demo --profile demo

EXPOSE 7860
CMD ["/srv/start.sh"]
