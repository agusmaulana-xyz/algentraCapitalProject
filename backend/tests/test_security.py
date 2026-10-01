from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.security import RateLimitMiddleware


def test_rate_limit_returns_429_after_configured_budget(monkeypatch):
    monkeypatch.setattr(RateLimitMiddleware, "_limit", staticmethod(lambda _path: (2, 60)))
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware)

    @app.get("/limited")
    def limited():
        return {"status": "ok"}

    with TestClient(app) as client:
        assert client.get("/limited").status_code == 200
        assert client.get("/limited").status_code == 200
        response = client.get("/limited")
        assert response.status_code == 429
        assert response.headers["retry-after"] == "60"
