# Re-export so `celery -A src.workers.tasks` resolves the app without the
# full dotted path to celery_app.py.
from src.workers.tasks.celery_app import celery_app as celery_app
