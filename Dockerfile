FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DB_PATH=/data/gmail_bot.db

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY gmail_bot ./gmail_bot

# Root bo'lmagan foydalanuvchi; /data — SQLite baza uchun (volume)
RUN useradd --create-home --uid 1000 bot \
    && mkdir -p /data \
    && chown bot:bot /data
USER bot
VOLUME ["/data"]

CMD ["python", "-m", "gmail_bot"]
