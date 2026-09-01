# SAMAN backend — Python 3.12 + FastAPI (spec §0.2)
FROM python:3.12-slim

WORKDIR /srv

# Dependencies first so the layer caches across code edits.
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
WORKDIR /srv/backend

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SAMAN_DB_PATH=/srv/data/app.db

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
