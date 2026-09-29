from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.gemini_parser import SignalClassification
from app.main import app
from app.models import EAStatus, Signal, Trade, utc_now


API_KEY = "m4-test-ea-api-key-32-characters-long"


def test_ea_api_key_heartbeat_claim_report_and_trade_result():
    with TestClient(app) as client:
        assert client.get("/api/ea/pending").status_code == 401
        headers = {"X-API-Key": API_KEY}

        heartbeat = client.post("/api/ea/heartbeat", headers=headers, json={"active": True, "version": "test", "symbol": "XAUUSD"})
        assert heartbeat.status_code == 200
        assert heartbeat.json()["active"] is True

        parsed = SignalClassification(
            is_signal=True,
            type="NEW_SIGNAL",
            action="BUY",
            order_type="MARKET",
            symbol="XAUUSD",
            entry=None,
            tp=[2450.0],
            sl=2400.0,
            confidence=0.95,
            reason="mock signal",
        )
        with SessionLocal() as db:
            signal = Signal(
                group_id="-1001",
                group_name="Test group",
                message_id="101",
                raw_text="BUY XAUUSD",
                parsed_json=parsed.model_dump_json(),
                status="PENDING",
                created_at=utc_now(),
            )
            db.add(signal)
            db.commit()
            db.refresh(signal)
            signal_id = signal.id

        pending = client.get("/api/ea/pending?limit=1", headers=headers)
        assert pending.status_code == 200
        assert pending.json()["items"][0]["signal_id"] == signal_id
        assert pending.json()["demo_mode"] is True
        assert client.get("/api/ea/pending", headers=headers).json()["items"] == []

        report = {"signal_id": signal_id, "status": "EXECUTED", "ticket": "98765", "symbol": "XAUUSD", "action": "BUY", "lots": 0.02, "exec_price": 2425.0}
        assert client.post("/api/ea/report", headers=headers, json=report).status_code == 200
        duplicate = {**report, "status": "REJECTED"}
        assert client.post("/api/ea/report", headers=headers, json=duplicate).json()["duplicate"] is True

        result = {"ticket": "98765", "profit": 25.5, "result": "WIN", "closed_at": datetime.now(timezone.utc).isoformat()}
        assert client.post("/api/ea/result", headers=headers, json=result).status_code == 200
        assert client.post("/api/ea/result", headers=headers, json=result).json()["duplicate"] is True

        with SessionLocal() as db:
            stored_signal = db.get(Signal, signal_id)
            trade = db.query(Trade).filter_by(ticket="98765").one()
            ea_status = db.get(EAStatus, 1)
            assert stored_signal.status == "WIN"
            assert trade.profit == 25.5
            assert trade.result == "WIN"
            assert ea_status.active is True


def test_ea_report_rejects_profit_result_sign_mismatch():
    with SessionLocal() as db:
        db.add(Trade(ticket="sign-mismatch"))
        db.commit()
    with TestClient(app) as client:
        assert client.post(
            "/api/ea/result",
            headers={"X-API-Key": API_KEY},
            json={"ticket": "sign-mismatch", "profit": -1, "result": "WIN"},
        ).status_code == 422
