"""Symbol translation and startup availability checks."""

from __future__ import annotations

from typing import Any, Mapping


def map_symbol(master_symbol: str, config: Mapping[str, Any]) -> str:
    return str(config.get("map_simbol", {}).get(master_symbol, master_symbol))


def select_symbol(mt5: Any, symbol: str) -> bool:
    info = mt5.symbol_info(symbol)
    if info is None:
        raise ValueError(f"Simbol '{symbol}' tidak ditemukan di terminal follower")
    if not getattr(info, "visible", False) and not mt5.symbol_select(symbol, True):
        raise ValueError(f"Gagal menampilkan simbol '{symbol}' di Market Watch: {mt5.last_error()}")
    return True
