from argparse import Namespace

import launch_host


class FakeProcess:
    def __init__(self, running: bool, wait_result: int = 0) -> None:
        self.running = running
        self.wait_result = wait_result
        self.terminated = False

    def poll(self):
        return None if self.running else self.wait_result

    def wait(self, timeout=None):
        self.running = False
        return self.wait_result

    def terminate(self):
        self.terminated = True
        self.running = False

    def kill(self):
        self.running = False


def test_combined_launcher_starts_server_then_host_gui(monkeypatch):
    server = FakeProcess(running=True)
    gui = FakeProcess(running=False)
    processes = iter((server, gui))
    commands = []

    def fake_popen(command, **_kwargs):
        commands.append(command)
        return next(processes)

    monkeypatch.setattr(
        launch_host,
        "parse_args",
        lambda: Namespace(
            listen_host="127.0.0.1", port=8765, startup_timeout=5.0
        ),
    )
    monkeypatch.setattr(launch_host, "server_is_ready", lambda _port: False)
    monkeypatch.setattr(launch_host, "wait_for_server", lambda *_args: None)
    monkeypatch.setattr(launch_host.subprocess, "Popen", fake_popen)

    assert launch_host.main() == 0
    assert commands[0][-4:] == ["--host", "127.0.0.1", "--port", "8765"]
    assert commands[1][-1] == "--host"
    assert "gui_client.py" in commands[1][1]
    assert server.terminated


def test_combined_launcher_reuses_an_existing_server(monkeypatch):
    gui = FakeProcess(running=False)
    commands = []

    def fake_popen(command, **_kwargs):
        commands.append(command)
        return gui

    monkeypatch.setattr(
        launch_host,
        "parse_args",
        lambda: Namespace(
            listen_host="127.0.0.1", port=8765, startup_timeout=5.0
        ),
    )
    monkeypatch.setattr(launch_host, "server_is_ready", lambda _port: True)
    monkeypatch.setattr(launch_host.subprocess, "Popen", fake_popen)

    assert launch_host.main() == 0
    assert len(commands) == 1
    assert "gui_client.py" in commands[0][1]
