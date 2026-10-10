from types import SimpleNamespace

import pytest

from copytrade.lot_calc import calculate_lot


@pytest.mark.parametrize(("step", "master", "expected"), [(0.01, 0.127, 0.12), (0.1, 1.29, 1.2)])
def test_rounds_down_to_volume_step(step, master, expected):
    info = SimpleNamespace(volume_step=step, volume_min=step, volume_max=20)
    result = calculate_lot(master, info, {"mode_lot": "rasio", "rasio_lot": 1, "max_lot_per_order": 10})
    assert result.volume == pytest.approx(expected)


def test_below_minimum_is_skipped_not_raised():
    info = SimpleNamespace(volume_step=0.01, volume_min=0.05, volume_max=10)
    result = calculate_lot(0.04, info, {"mode_lot": "rasio", "rasio_lot": 1})
    assert result.volume is None
    assert "di bawah" in result.reason


def test_capped_to_symbol_and_config_maximum():
    info = SimpleNamespace(volume_step=0.1, volume_min=0.1, volume_max=2.0)
    result = calculate_lot(10, info, {"mode_lot": "rasio", "rasio_lot": 1, "max_lot_per_order": 1.35})
    assert result.volume == pytest.approx(1.3)


def test_fixed_and_balance_modes():
    info = SimpleNamespace(volume_step=0.01, volume_min=0.01, volume_max=100)
    fixed = calculate_lot(1, info, {"mode_lot": "tetap", "lot_tetap": 0.25})
    balance = calculate_lot(0.2, info, {"mode_lot": "saldo", "saldo_master": 1000}, balance_follower=500)
    assert fixed.volume == pytest.approx(0.25)
    assert balance.volume == pytest.approx(0.1)
