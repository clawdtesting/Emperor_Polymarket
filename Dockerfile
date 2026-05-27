FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# State and logs live on a mounted volume so they survive restarts.
VOLUME ["/app/data", "/app/logs"]

EXPOSE 8000

# Launch the web console (dashboard + trading loop) with a SINGLE worker —
# more workers would each spawn their own trading loop. Binds Render's $PORT.
# Override the command (e.g. `paper`, `backtest`) for terminal-only use.
CMD ["sh", "-c", "gunicorn --workers 1 --threads 4 --timeout 120 --bind 0.0.0.0:${PORT:-8000} src.web.wsgi:app"]
