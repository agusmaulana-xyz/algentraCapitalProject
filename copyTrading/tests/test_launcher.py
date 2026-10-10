import json

import pytest

from copytrade.launcher import Supervisor


class FakeProcess:
    next_pid = 100

    def __init__(self, command, **kwargs):
        self.command = command
        self.kwargs = kwargs
        self.return_code = None
        self.terminated = False
        FakeProcess.next_pid += 1
        self.pid = FakeProcess.next_pid

    def poll(self):
        return self.return_code

    def terminate(self):
        self.terminated = True
        self.return_code = 0

    def wait(self, timeout=None):
        return self.return_code

    def kill(self):
        self.return_code = -9


def build_supervisor(tmp_path, *, max_restarts=10, heartbeat_timeout=30):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "master.json").write_text(json.dumps({"terminal_path": "C:/MT5_MASTER/terminal64.exe",
                                                         "folder_sinyal": "C:/signals"}), encoding="utf-8")
    (config_dir / "f1.json").write_text(json.dumps({
        "nama": "f1", "aktif": True, "login": 101,
        "terminal_path": "C:/MT5_F1/terminal64.exe", "password_env": "F1_PASS",
        "server": "Demo", "folder_sinyal": "C:/signals", "max_posisi_terbuka": 10,
        "max_lot_total": 5, "max_lot_per_order": 1,
    }), encoding="utf-8")
    config_path = config_dir / "launcher.json"
    config_path.write_text("{}", encoding="utf-8")
    spawned = []

    def popen(command, **kwargs):
        process = FakeProcess(command, **kwargs)
        spawned.append(process)
        return process

    config = {"master_config": "master.json", "followers": ["f1.json"],
              "max_restarts_per_10_minutes": max_restarts,
              "heartbeat_timeout_seconds": heartbeat_timeout}
    supervisor = Supervisor(config_path, config, popen=popen, python="python-test", project_root=tmp_path)
    return supervisor, spawned


def test_starts_each_role_as_separate_process(tmp_path):
    supervisor, spawned = build_supervisor(tmp_path)
    supervisor.start_all()
    assert len(spawned) == 2
    assert "copytrade.master_publisher" in spawned[0].command
    assert "copytrade.follower" in spawned[1].command
    assert spawned[0].kwargs["cwd"] == tmp_path
    assert str(tmp_path / "src") in spawned[0].kwargs["env"]["PYTHONPATH"]
    supervisor.stop_all()


def test_restarts_dead_child_with_backoff_and_permanent_limit(tmp_path):
    supervisor, spawned = build_supervisor(tmp_path, max_restarts=1)
    supervisor.start_all()
    master = supervisor.children[0]
    first = master.process
    first.return_code = 7
    now = master.started_at + 1
    supervisor.tick(now=now)
    assert master.process is None
    assert master.next_start_at == now + 1
    supervisor.tick(now=master.next_start_at)
    assert master.process is not None
    master.process.return_code = 8
    supervisor.tick(now=master.started_at + 1)
    assert master.permanent_failure
    assert len(spawned) == 3
    supervisor.stop_all()


def test_restarts_follower_with_stale_or_missing_heartbeat(tmp_path):
    supervisor, spawned = build_supervisor(tmp_path, heartbeat_timeout=5)
    supervisor.start_all()
    follower = supervisor.children[1]
    old_process = follower.process
    supervisor.tick(now=follower.started_at + 6)
    assert old_process.terminated
    assert follower.process is None
    assert follower.next_start_at == follower.started_at + 7
    supervisor.stop_all()


def test_rejects_reusing_terminal_or_account(tmp_path):
    supervisor, _ = build_supervisor(tmp_path)
    duplicate_path = tmp_path / "config" / "f2.json"
    duplicate_path.write_text(json.dumps({**json.loads((tmp_path / "config" / "f1.json").read_text(encoding="utf-8")),
                                          "nama": "f2", "terminal_path": "C:/MT5_F2/terminal64.exe"}), encoding="utf-8")
    with pytest.raises(ValueError, match="login 101"):
        Supervisor(supervisor.config_path, {**supervisor.config, "followers": ["f1.json", "f2.json"]}, project_root=tmp_path)

    duplicate_path.write_text(json.dumps({**json.loads((tmp_path / "config" / "f1.json").read_text(encoding="utf-8")),
                                          "nama": "f2", "login": 102,
                                          "terminal_path": "C:/MT5_MASTER/terminal64.exe"}), encoding="utf-8")
    with pytest.raises(ValueError, match="terminal_path"):
        Supervisor(supervisor.config_path, {**supervisor.config, "followers": ["f2.json"]}, project_root=tmp_path)
