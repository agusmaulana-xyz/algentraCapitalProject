from datetime import datetime, timedelta, timezone
import json

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.gemini_parser import SignalClassification
from app.main import app
from app.models import AppSetting, EAExecution, EAStatus, Signal, Trade, utc_now


API_KEY = "m4-test-ea-api-key-32-characters-long"


def set_controls(**values):
    with SessionLocal() as db:
        for key, value in values.items():
            db.merge(AppSetting(key=key, value=json.dumps(value)))
        db.commit()


def parsed_signal(symbol="XAUUSD"):
    return SignalClassification(
        is_signal=True, type="NEW_SIGNAL", action="BUY", order_type="MARKET", symbol=symbol,
        entry=None, tp=[2450.0], sl=2400.0, confidence=0.95, reason="test",
    ).model_dump_json()


def test_ea_api_key_heartbeat_claim_report_and_trade_result():
    with SessionLocal() as db:
        for key, value in {
            "demo_mode": "true", "kill_switch": "false", "max_daily_loss_money": "100.0",
            "max_lot": "5.0", "max_open_trades": "3", "max_signal_age_seconds": "120",
            "max_market_deviation_pct": "5.0", "allowed_symbols": "[]",
        }.items():
            db.merge(AppSetting(key=key, value=value))
        db.commit()

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

        with SessionLocal() as db:
            db.merge(AppSetting(key="demo_mode", value="false"))
            db.commit()

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
            db.merge(AppSetting(key="demo_mode", value="true"))
            db.commit()
        with SessionLocal() as db:
            db.query(EAExecution).filter_by(signal_id=signal_id).delete(synchronize_session=False)
            db.query(Trade).filter_by(ticket="98765").delete(synchronize_session=False)
            db.query(Signal).filter_by(id=signal_id).delete(synchronize_session=False)
            db.commit()


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


def test_ea_pending_enforces_kill_switch_signal_age_and_symbol_allowlist():
    set_controls(
        demo_mode=False, kill_switch=True, max_daily_loss_money=0, max_lot=1,
        max_open_trades=3, max_signal_age_seconds=120, max_market_deviation_pct=5,
        allowed_symbols=["EURUSD"],
    )
    now = utc_now()
    with SessionLocal() as db:
        stale = Signal(group_id="risk-test", message_id="stale", raw_text="old", parsed_json=parsed_signal("EURUSD"), status="PENDING", created_at=now - timedelta(minutes=5))
        forbidden = Signal(group_id="risk-test", message_id="forbidden", raw_text="wrong symbol", parsed_json=parsed_signal("XAUUSD"), status="PENDING", created_at=now)
        db.add_all([stale, forbidden])
        db.commit()
        stale_id, forbidden_id = stale.id, forbidden.id

    try:
        with TestClient(app) as client:
            headers = {"X-API-Key": API_KEY}
            paused = client.get("/api/ea/pending", headers=headers)
            assert paused.status_code == 200
            assert paused.json()["items"] == []
            assert paused.json()["kill_switch"] is True
            set_controls(kill_switch=False)
            filtered = client.get("/api/ea/pending?limit=10", headers=headers)
            assert filtered.status_code == 200
            assert filtered.json()["items"] == []
            with SessionLocal() as db:
                assert db.get(Signal, stale_id).status == "REJECTED"
                assert db.get(Signal, forbidden_id).status == "REJECTED"
    finally:
        with SessionLocal() as db:
            db.query(Signal).filter(Signal.id.in_([stale_id, forbidden_id])).delete(synchronize_session=False)
            db.commit()
        set_controls(demo_mode=True, kill_switch=False, max_daily_loss_money=100, max_lot=5, max_open_trades=3, max_signal_age_seconds=120, max_market_deviation_pct=5, allowed_symbols=[])


def test_ea_pending_pauses_after_realized_daily_loss_and_demo_blocks_live_report():
    set_controls(demo_mode=True, kill_switch=False, max_daily_loss_money=10, max_lot=5, max_open_trades=3, max_signal_age_seconds=120, max_market_deviation_pct=5, allowed_symbols=[])
    now = utc_now()
    with SessionLocal() as db:
        loss = Trade(ticket="risk-daily-loss", profit=-100, result="LOSS", opened_at=now - timedelta(minutes=2), closed_at=now)
        signal = Signal(group_id="risk-test", message_id="daily-loss", raw_text="BUY", parsed_json=parsed_signal(), status="PENDING", created_at=now)
        db.add_all([loss, signal])
        db.commit()
        loss_id, signal_id = loss.id, signal.id
    try:
        with TestClient(app) as client:
            headers = {"X-API-Key": API_KEY}
            response = client.get("/api/ea/pending", headers=headers)
            assert response.status_code == 200
            assert response.json()["daily_loss_reached"] is True
            assert response.json()["items"] == []
            with SessionLocal() as db:
                db.query(Trade).filter(Trade.id == loss_id).delete()
                db.commit()
            set_controls(max_daily_loss_money=100)
            claimed = client.get("/api/ea/pending", headers=headers)
            assert claimed.json()["items"][0]["signal_id"] == signal_id
            report = {"signal_id": signal_id, "status": "EXECUTED", "ticket": "risk-live-blocked", "symbol": "XAUUSD", "action": "BUY", "lots": 0.01, "exec_price": 2425}
            assert client.post("/api/ea/report", headers=headers, json=report).status_code == 409
    finally:
        with SessionLocal() as db:
            db.query(Signal).filter(Signal.id == signal_id).delete()
            db.query(Trade).filter(Trade.ticket == "risk-daily-loss").delete()
            db.commit()
        set_controls(demo_mode=True, kill_switch=False, max_daily_loss_money=100, max_lot=5, max_open_trades=3, max_signal_age_seconds=120, max_market_deviation_pct=5, allowed_symbols=[])
