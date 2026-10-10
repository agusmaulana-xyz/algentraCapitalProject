from types import SimpleNamespace

from copytrade.follower import FollowerEngine
from copytrade.master_publisher import diff_snapshot
from copytrade.protocol import Signal


def test_master_events_are_applied_consistently_by_three_followers(tmp_path, fake_mt5):
    baseline = {}
    master_open = SimpleNamespace(identifier=77, ticket=99, symbol="EURUSD", type=0, volume=0.1,
                                  price_open=1.1, sl=1.0, tp=1.2, comment="", magic=42)
    events, baseline = diff_snapshot(baseline, [master_open])
    open_event = events[0]
    followers = [
        FollowerEngine({"nama": f"f{i}", "folder_sinyal": str(tmp_path), "dry_run": True,
                        "mode_lot": "rasio", "rasio_lot": 1, "max_lot_per_order": 5,
                        "map_simbol": {}, "max_posisi_terbuka": 10, "max_lot_total": 10},
                       fake_mt5, tmp_path / f"state{i}.json")
        for i in range(3)
    ]

    def signal(event, index):
        return Signal(1, f"{index}", 100, event["aksi"], event["pos_id"], event.get("simbol"),
                      event.get("arah"), event.get("lot"), event.get("harga"), event.get("sl"),
                      event.get("tp"), event.get("komentar", ""), event.get("lot_sisa"))

    for follower in followers:
        assert follower.process_signal(signal(open_event, 1), now=100) == "sukses_dry_run"
        assert set(follower.positions) == {"77"}
    changed = SimpleNamespace(**{**master_open.__dict__, "sl": 1.02})
    events, baseline = diff_snapshot(baseline, [changed])
    for follower in followers:
        assert follower.process_signal(signal(events[0], 2), now=100) == "sukses_dry_run"
    partial = SimpleNamespace(**{**changed.__dict__, "volume": 0.05})
    events, baseline = diff_snapshot(baseline, [partial])
    for follower in followers:
        assert follower.process_signal(signal(events[0], 3), now=100) == "sukses_dry_run"
        assert follower.positions["77"]["volume_current"] == 0.05
    events, baseline = diff_snapshot(baseline, [])
    for follower in followers:
        assert follower.process_signal(signal(events[0], 4), now=100) == "sukses_dry_run"
        assert follower.positions == {}
