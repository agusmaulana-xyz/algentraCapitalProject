import pytest

from copytrade.protocol import SignalValidationError, encode_signal, parse_signal


def test_parse_valid_open_and_round_trip():
    data = {"v": 1, "id": "1760000000000-1", "ts": 1760000000.123, "aksi": "buka",
            "pos_id": 123, "simbol": "XAUUSD", "arah": "buy", "lot": 0.1,
            "harga": 2650.1, "sl": 2645.0, "tp": 2660.0, "komentar": ""}
    parsed = parse_signal(data)
    assert parsed.aksi == "buka"
    assert parse_signal(encode_signal(parsed)) == parsed


@pytest.mark.parametrize("payload", ["{broken", "[]", "{}", '{"v":1,"id":"x","ts":NaN,"aksi":"tutup","pos_id":3}'])
def test_rejects_malformed_signal(payload):
    with pytest.raises(SignalValidationError):
        parse_signal(payload)


def test_rejects_missing_action_fields_and_bad_values():
    base = {"v": 1, "id": "x", "ts": 1, "aksi": "buka", "pos_id": 1, "simbol": "XAUUSD", "arah": "buy", "lot": 0.1, "sl": 0, "tp": 0}
    with pytest.raises(SignalValidationError, match="simbol"):
        parse_signal({k: v for k, v in base.items() if k != "simbol"})
    with pytest.raises(SignalValidationError, match="arah"):
        parse_signal({**base, "arah": "long"})
    with pytest.raises(SignalValidationError):
        parse_signal({**base, "lot": -1})
