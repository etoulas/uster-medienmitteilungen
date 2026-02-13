"""Gunicorn entry point for the Flask application."""

from dotenv import load_dotenv

load_dotenv()

from database import init_db
from app import app, start_scheduler

init_db()
start_scheduler()

application = app
