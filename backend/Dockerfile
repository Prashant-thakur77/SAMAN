# SAMAN backend — Python 3.12 + FastAPI (spec §0.2)
FROM python:3.12-slim

WORKDIR /srv

# Dependencies first so the layer caches across code edits.
COPY backend/requirements.txt ./requirements.txt
# Patient on slow links: a read timeout mid-download is a retry, not a failed build.
RUN pip install --no-cache-dir --timeout 180 --retries 8 -r requirements.txt

# Optional engines. SAMAN_EXTRAS=voice adds local speech recognition, speech
# synthesis and the OCR reader (the same pins as `make deps-stt`, `deps-tts`
# and `deps-ocr`); their model files are read from the mounted data/models
# directory, downloaded once with those make targets. "none" keeps the image
# small and every screen still works on the browser's engines.
ARG SAMAN_EXTRAS=none
RUN if [ "$SAMAN_EXTRAS" = "voice" ]; then \
      apt-get update && apt-get install --no-install-recommends -y libxcb1 libglib2.0-0 libgl1 \
        && rm -rf /var/lib/apt/lists/* \
        && pip install --no-cache-dir --timeout 180 --retries 8 \
          faster-whisper==1.2.1 piper-tts==1.7.0 rapidocr-onnxruntime==1.4.4 ; \
    fi

COPY backend/ ./backend/
# The assistant answers questions from the project's own documents; without
# them in the image the grounded path has nothing to retrieve and says so.
COPY README.md KNOWN_GAPS.md SAMAN_CLAUDE_CODE_SPEC.md ./
COPY docs/*.md ./docs/
WORKDIR /srv/backend

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SAMAN_DB_PATH=/srv/data/app.db

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
