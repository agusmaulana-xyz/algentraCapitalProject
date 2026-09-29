from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth import seed_admin, verify_password
from app.config import Settings
from app.database import Base
from app.models import AdminUser
from app.main import app


def test_admin_login_protects_and_unlocks_dashboard_routes():
    with TestClient(app) as client:
        assert client.get("/api/stats").status_code == 401

        response = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "M1-Testing-Password-123"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "authenticated"
        assert client.get("/api/stats").json()["winrate"] == 0.0

        assert client.post("/api/auth/logout").status_code == 200
        assert client.get("/api/stats").status_code == 401


def test_settings_endpoint_reads_and_updates_values_after_login():
    with TestClient(app) as client:
        assert client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "M1-Testing-Password-123"},
        ).status_code == 200

        assert client.get("/api/settings").json()["demo_mode"] is True
        update = client.put("/api/settings", json={"values": {"confidence_threshold": 0.8}})
        assert update.status_code == 200
        assert client.get("/api/settings").json()["confidence_threshold"] == 0.8


def test_startup_syncs_changed_admin_password_from_environment():
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    old_config = Settings(
        _env_file=None,
        APP_SECRET_KEY="isolated-test-secret-key-longer-than-32-characters",
        ADMIN_USERNAME="admin",
        ADMIN_PASSWORD="Previous-test-password-123",
    )
    new_password = "Updated-test-password-456"
    new_config = Settings(
        _env_file=None,
        APP_SECRET_KEY="isolated-test-secret-key-longer-than-32-characters",
        ADMIN_USERNAME="admin",
        ADMIN_PASSWORD=new_password,
    )

    with Session(engine) as db:
        seed_admin(db, old_config)
        seed_admin(db, new_config)
        user = db.get(AdminUser, "admin")
        assert user is not None
        assert verify_password(new_password, user.password_hash)
        assert not verify_password("Previous-test-password-123", user.password_hash)

    engine.dispose()
