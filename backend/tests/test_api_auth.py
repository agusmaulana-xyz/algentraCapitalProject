from fastapi.testclient import TestClient

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
