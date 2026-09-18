# SAMAN as one container, for any host that runs a single image on a single
# port and keeps it running without a laptop: Render, Koyeb, Cloud Run, a VM.
# The frontend is built and served by Caddy, the API sits behind it on the
# loopback, and the demo database is generated at build time so the container
# answers the moment it starts and needs no volume. Anything written at runtime
# (decisions, uploads) lives only as long as the container does.
#
#   make image        # docker build -f deploy/single/Dockerfile -t saman-one .
#   make image-run    # on :7860
#
# The port is read from $PORT, which is how Render, Koyeb, Cloud Run and
# Hugging Face all say which port to listen on; 7860 when nothing says.
#
# The dependency layers repeat backend/Dockerfile and deploy/Dockerfile.web
# instruction for instruction on purpose: Docker then shares them between this
# image and the compose stack instead of downloading everything twice.

# --- web: the production frontend build (as deploy/Dockerfile.web) ---
FROM node:22-slim AS build
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- app: API + Caddy + baked demo data (as backend/Dockerfile) ---
FROM python:3.12-slim

WORKDIR /srv

# Dependencies first so the layer caches across code edits.
COPY backend/requirements.txt ./requirements.txt
# Patient on slow links: a read timeout mid-download is a retry, not a failed build.
RUN pip install --no-cache-dir --timeout 180 --retries 8 -r requirements.txt

# "voice" adds local speech recognition, synthesis and the OCR reader, with
# their model files fetched at build time: about 300 MB of image and rather
# more resident memory than a 512 MB free plan has. The default leaves them
# out; every screen still works on the browser's own engines and says so.
ARG SAMAN_EXTRAS=none
RUN if [ "$SAMAN_EXTRAS" = "voice" ]; then \
      apt-get update && apt-get install --no-install-recommends -y libxcb1 libglib2.0-0 libgl1 \
        && rm -rf /var/lib/apt/lists/* \
        && pip install --no-cache-dir --timeout 180 --retries 8 \
          faster-whisper==1.2.1 piper-tts==1.7.0 rapidocr-onnxruntime==1.4.4 ; \
    fi

COPY --from=caddy:2-alpine /usr/bin/caddy /usr/bin/caddy

# Hosts such as Hugging Face run the container as uid 1000; everything it must
# write is owned by that user from the start.
RUN useradd -m -u 1000 saman && mkdir -p /srv/data /srv/caddy /etc/caddy \
    && chown -R saman:saman /srv /etc/caddy

COPY --chown=saman:saman backend/ ./backend/
# The assistant answers from the project's own documents.
COPY --chown=saman:saman README.md KNOWN_GAPS.md SAMAN_CLAUDE_CODE_SPEC.md ./
COPY --chown=saman:saman docs/*.md ./docs/
COPY --from=build --chown=saman:saman /src/dist /srv/www
COPY --chown=saman:saman deploy/single/Caddyfile /etc/caddy/Caddyfile
COPY --chown=saman:saman deploy/single/start.sh /srv/start.sh
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
