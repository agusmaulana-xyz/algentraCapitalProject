import os
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_SECRET_KEY", "m1-test-secret-key-at-least-thirty-two-characters")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "M1-Testing-Password-123")
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("EA_API_KEY", "m4-test-ea-api-key-32-characters-long")
