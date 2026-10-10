import json

import pytest

from copytrade.state import empty_state, load_state, save_state


def test_state_round_trip_uses_atomic_replace(tmp_path):
    path = tmp_path / "state" / "follower.json"
    state = empty_state()
    state["positions"]["12"] = {"ticket": 99, "volume_current": 0.1}
    state["processed"] = ["sig-1"]
    save_state(path, state)
    assert load_state(path) == state
    assert list(path.parent.iterdir()) == [path]


def test_missing_state_starts_empty_and_invalid_state_is_clear(tmp_path):
    path = tmp_path / "state.json"
    assert load_state(path) == empty_state()
    path.write_text(json.dumps({"positions": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="Format state"):
        load_state(path)
