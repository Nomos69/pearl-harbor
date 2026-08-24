import queue

import gui_client


class FakeProcess:
    pass


def bare_application() -> gui_client.BattleshipGUI:
    application = object.__new__(gui_client.BattleshipGUI)
    application.messages = queue.Queue()
    application.closing = False
    return application


def test_host_mode_starts_a_public_server_for_remote_guest(monkeypatch):
    application = bare_application()
    process = FakeProcess()
    received_args = []

    monkeypatch.setattr(gui_client, "server_is_ready", lambda _port: False)

    def fake_start_server(args):
        received_args.append(args)
        return process

    monkeypatch.setattr(gui_client, "start_server", fake_start_server)

    application._prepare_host_server(8765, "Japan")

    message = application.messages.get_nowait()
    assert message == {
        "type": "local_server_ready",
        "port": 8765,
        "preferred_team": "Japan",
        "process": process,
        "reused_server": False,
    }
    assert received_args[0].listen_host == "0.0.0.0"


def test_host_mode_reuses_an_existing_local_game_server(monkeypatch):
    application = bare_application()

    monkeypatch.setattr(gui_client, "server_is_ready", lambda _port: True)
    monkeypatch.setattr(
        gui_client,
        "start_server",
        lambda _args: (_ for _ in ()).throw(AssertionError("must not start twice")),
    )

    application._prepare_host_server(9000, "US")

    message = application.messages.get_nowait()
    assert message["type"] == "local_server_ready"
    assert message["process"] is None
    assert message["reused_server"] is True


def test_host_mode_reports_server_start_failure(monkeypatch):
    application = bare_application()

    monkeypatch.setattr(gui_client, "server_is_ready", lambda _port: False)
    monkeypatch.setattr(
        gui_client,
        "start_server",
        lambda _args: (_ for _ in ()).throw(RuntimeError("port unavailable")),
    )

    application._prepare_host_server(8765, "Japan")

    assert application.messages.get_nowait() == {
        "type": "local_server_error",
        "message": "port unavailable",
    }
