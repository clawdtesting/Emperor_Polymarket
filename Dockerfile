FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# State and logs live on a mounted volume so they survive restarts.
VOLUME ["/app/data", "/app/logs"]

# Paper mode by default; override the command for live/backtest.
ENTRYPOINT ["python", "bot.py"]
CMD ["paper"]
