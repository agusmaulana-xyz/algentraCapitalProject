import json

import pytest

from copytrade.managed_worker import _resolve, load_config


def test_load_config_resolves_local_paths_and_accepts_https_worker_api(tmp_path):
    config_path = tmp_path / "managed.json"
    config_path.write_text(json.dumps({
        "api_base_url": "https://algentra.example",
        "worker_api_key_env": "COPIER_WORKER_API_KEY",
        "master_config": "config/master.json",
        "terminal_template_dir": "C:/MT5_Template",
        "runtime_dir": "runtime",
        "poll_seconds": 1,
    }), encoding="utf-8")

    config = load_config(config_path)

    assert config["_api_base"] == "https://algentra.example"
    assert config["_master_config"] == str((tmp_path / "config/master.json").resolve())
    assert config["_runtime_dir"] == str((tmp_path / "runtime").resolve())
    assert config["poll_seconds"] == 2


@pytest.mark.parametrize("api_base", [
    "http://algentra.example",
    "http://localhost.evil.example",
    "ftp://algentra.example",
    "https://user:password@algentra.example",
])
def test_load_config_rejects_untrusted_or_ambiguous_api_urls(tmp_path, api_base):
    path = tmp_path / "managed.json"
    path.write_text(json.dumps({
        "api_base_url": api_base,
        "worker_api_key_env": "COPIER_WORKER_API_KEY",
        "master_config": "master.json",
        "terminal_template_dir": "C:/MT5_Template",
        "runtime_dir": "runtime",
    }), encoding="utf-8")

    with pytest.raises(ValueError):
        load_config(path)


def test_resolve_keeps_absolute_paths_and_resolves_relative_paths(tmp_path):
    assert _resolve(tmp_path, "runtime") == (tmp_path / "runtime").resolve()
    assert _resolve(tmp_path, str((tmp_path / "absolute").resolve())) == (tmp_path / "absolute").resolve()
