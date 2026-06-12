"""
Root-level conftest — sets stub env vars before any child conftest is loaded.

``os.environ.setdefault`` never overrides values already present in the
environment (e.g., from docker-compose in CI).  Unit tests that mock all I/O
use these stubs; integration tests that need real services will fail correctly
if those services are not running.
"""
import os

os.environ.setdefault("SECRET_KEY", "test-secret-key-at-least-32-chars-long!")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("MONGODB_URL", "mongodb://localhost:27017")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")
