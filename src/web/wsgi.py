"""WSGI entry point for production servers (gunicorn).

    gunicorn --workers 1 --threads 4 src.web.wsgi:app

IMPORTANT: run with exactly ONE worker. Each worker process would start its
own trading loop, which must never happen.
"""
from .app import create_app
from ..alerts.logger import setup_logging

setup_logging()
app = create_app()
