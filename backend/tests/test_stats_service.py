from types import SimpleNamespace

import pytest

from app.stats_service import calculate_trade_stats


@pytest.mark.parametrize(
    ("results", "wins", "losses", "winrate"),
    [
        (["WIN", "LOSS", "WIN"], 2, 1, 66.67),
        (["WIN", "WIN"], 2, 0, 100.0),
        (["LOSS", "LOSS"], 0, 2, 0.0),
        (["WIN", "LOSS", "BE", None], 1, 1, 50.0),
        ([], 0, 0, 0.0),
    ],
)
def test_trade_stats_win_loss_and_winrate(results, wins, losses, winrate):
    trades = [SimpleNamespace(result=result, profit=10.0 if result == "WIN" else -4.0) for result in results]

    stats = calculate_trade_stats(trades)

    assert stats["wins"] == wins
    assert stats["losses"] == losses
    assert stats["winrate"] == winrate


def test_winrate_excludes_break_even_and_open_trades():
    trades = [
        SimpleNamespace(result="WIN", profit=12),
        SimpleNamespace(result="LOSS", profit=-5),
        SimpleNamespace(result="BE", profit=0),
        SimpleNamespace(result=None, profit=0),
    ]

    stats = calculate_trade_stats(trades)

    assert stats["winrate"] == pytest.approx(50.0)
    assert stats["total_profit"] == pytest.approx(7.0)
