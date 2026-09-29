from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth import seed_admin, verify_password
from app.config import Settings
from app.database import Base, SessionLocal
from app.models import AdminUser, Signal, Trade
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
        assert client.get("/parser-test").status_code == 200
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


def test_dashboard_endpoints_csv_and_websocket_after_login():
    with TestClient(app) as client:
        assert client.get("/dashboard").status_code == 401
        assert client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "M1-Testing-Password-123"},
        ).status_code == 200
        assert client.get("/dashboard").status_code == 200

        stats = client.get("/api/stats")
        assert stats.status_code == 200
        assert {"telegram_connected", "gemini_configured", "ea_online", "winrate"} <= stats.json().keys()
        assert client.get("/api/signals?limit=10").status_code == 200
        assert client.get("/api/groups/stats").status_code == 200
        assert client.get("/api/logs?level=ERROR&search=missing").status_code == 200
        assert client.get("/api/trades?result=WIN").status_code == 200
        assert "id,created_at,level,source,message" in client.get("/api/logs/export.csv").text
        assert "ticket,group,symbol,action" in client.get("/api/trades/export.csv").text

        with client.websocket_connect("/ws") as websocket:
            event = websocket.receive_json()
            assert event["type"] == "dashboard_refresh"
            assert "stats" in event


def test_signal_endpoint_includes_execution_ticket_and_profit():
    with SessionLocal() as db:
        signal = Signal(
            group_id="dashboard-route-test",
            group_name="Dashboard Test",
            raw_text="BUY XAUUSD",
            status="EXECUTED",
        )
        db.add(signal)
        db.flush()
        db.add(Trade(signal_id=signal.id, ticket="dashboard-route-ticket", profit=12.5))
        db.commit()
        signal_id = signal.id

    try:
        with TestClient(app) as client:
            assert client.post(
                "/api/auth/login",
                json={"username": "admin", "password": "M1-Testing-Password-123"},
            ).status_code == 200
            response = client.get(f"/api/signals?group_id=dashboard-route-test")
            assert response.status_code == 200
            [item] = response.json()
            assert item["id"] == signal_id
            assert item["ticket"] == "dashboard-route-ticket"
            assert item["profit"] == 12.5
    finally:
        with SessionLocal() as db:
            trade = db.query(Trade).filter_by(ticket="dashboard-route-ticket").one_or_none()
            if trade:
                db.delete(trade)
            signal = db.get(Signal, signal_id)
            if signal:
                db.delete(signal)
            db.commit()
