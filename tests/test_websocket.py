import asyncio
import json
import queue

import pytest
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from server import BattleshipServer, health_check
from network_client import NetworkWorker
from tests.test_game import JAPAN_FLEET, US_FLEET


async def receive_type(websocket, expected_type):
    for _ in range(20):
        message = json.loads(await asyncio.wait_for(websocket.recv(), timeout=2))
        if message.get("type") == expected_type:
            return message
    raise AssertionError(f"Did not receive {expected_type}")


async def http_get(port, path):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(
        f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n".encode()
    )
    await writer.drain()
    response = await reader.read()
    writer.close()
    await writer.wait_closed()
    return response


@pytest.mark.asyncio
async def test_server_health_endpoint():
    application = BattleshipServer("test-token")
    async with serve(
        application.handler, "127.0.0.1", 0, process_request=health_check
    ) as websocket_server:
        port = websocket_server.sockets[0].getsockname()[1]
        response = await http_get(port, "/healthz")
        assert response.startswith(b"HTTP/1.1 200")
        assert response.endswith(b"OK\n")


@pytest.mark.asyncio
async def test_two_clients_can_join_place_and_attack():
    application = BattleshipServer("test-token")
    async with serve(
        application.handler, "127.0.0.1", 0, process_request=health_check
    ) as websocket_server:
        port = websocket_server.sockets[0].getsockname()[1]
        uri = f"ws://127.0.0.1:{port}/ws"
        async with connect(uri) as first, connect(uri) as second:
            assert json.loads(await first.recv())["type"] == "hello"
            assert json.loads(await second.recv())["type"] == "hello"
            await first.send(json.dumps({"type": "time_sync", "client_send_ms": 1000}))
            sync_reply = json.loads(await first.recv())
            assert sync_reply["type"] == "time_sync_reply"
            assert sync_reply["client_send_ms"] == 1000
            await first.send(
                json.dumps(
                    {
                        "type": "host_lobby",
                        "preferred_team": "US",
                        "token": "test-token",
                    }
                )
            )
            first_joined = await receive_type(first, "joined")
            assert first_joined["team"] == "US"
            assert first_joined["role"] == "host"
            assert first_joined["assignment"] == "chosen"
            lobby_code = first_joined["lobby_code"]
            assert len(lobby_code) == 6

            await second.send(
                json.dumps(
                    {
                        "type": "join_lobby",
                        "lobby_code": lobby_code.lower(),
                    }
                )
            )
            second_joined = await receive_type(second, "joined")
            assert second_joined["team"] == "Japan"
            assert second_joined["role"] == "guest"
            assert second_joined["assignment"] == "automatic"
            assert second_joined["lobby_code"] == lobby_code
            await receive_type(first, "action_required")
            await receive_type(second, "action_required")

            await first.send(json.dumps({"type": "place_fleet", "ships": US_FLEET}))
            await receive_type(first, "fleet_ready")
            await second.send(json.dumps({"type": "place_fleet", "ships": JAPAN_FLEET}))
            await receive_type(second, "fleet_ready")
            state = await receive_type(first, "state")
            assert len(state["own_fleet"]) == 5
            assert all(set(row) == {"."} for row in state["target_board"])
            assert "opponent_fleet" not in state
            action = await receive_type(first, "action_required")
            assert action["action"] == "attack"

            await first.send(json.dumps({"type": "attack", "coordinate": "A1"}))
            result_first = await receive_type(first, "attack_result")
            result_second = await receive_type(second, "attack_result")
            assert result_first["result"] == result_second["result"] == "hit"

            # A hit keeps the turn with the attacker.
            next_action = await receive_type(first, "action_required")
            assert next_action["action"] == "attack"

            await first.send(json.dumps({"type": "attack", "coordinate": "B1"}))
            miss_first = await receive_type(first, "attack_result")
            miss_second = await receive_type(second, "attack_result")
            assert miss_first["result"] == miss_second["result"] == "miss"

            # A miss passes the turn to the opponent.
            opponent_action = await receive_type(second, "action_required")
            assert opponent_action["action"] == "attack"


@pytest.mark.asyncio
async def test_first_player_can_choose_japan_and_second_is_assigned_us():
    application = BattleshipServer("test-token")
    async with serve(
        application.handler, "127.0.0.1", 0, process_request=health_check
    ) as websocket_server:
        port = websocket_server.sockets[0].getsockname()[1]
        uri = f"ws://127.0.0.1:{port}/ws"
        async with connect(uri) as first, connect(uri) as second:
            await first.recv()
            await second.recv()
            await first.send(
                json.dumps(
                    {
                        "type": "host_lobby",
                        "preferred_team": "Japan",
                        "token": "test-token",
                    }
                )
            )
            first_joined = await receive_type(first, "joined")
            assert first_joined["team"] == "Japan"
            assert first_joined["role"] == "host"
            assert first_joined["assignment"] == "chosen"

            await second.send(
                json.dumps(
                    {
                        "type": "join_lobby",
                        "lobby_code": first_joined["lobby_code"],
                    }
                )
            )
            second_joined = await receive_type(second, "joined")
            assert second_joined["team"] == "US"
            assert second_joined["role"] == "guest"
            assert second_joined["assignment"] == "automatic"


@pytest.mark.asyncio
async def test_join_rejects_an_unknown_lobby_code():
    application = BattleshipServer("host-key")
    async with serve(
        application.handler, "127.0.0.1", 0, process_request=health_check
    ) as websocket_server:
        port = websocket_server.sockets[0].getsockname()[1]
        uri = f"ws://127.0.0.1:{port}/ws"
        async with connect(uri) as host, connect(uri) as guest:
            await host.recv()
            await guest.recv()
            await host.send(
                json.dumps(
                    {
                        "type": "host_lobby",
                        "preferred_team": "US",
                        "token": "host-key",
                    }
                )
            )
            await receive_type(host, "joined")

            await guest.send(
                json.dumps({"type": "join_lobby", "lobby_code": "WRONG2"})
            )
            error = await receive_type(guest, "error")
            assert error["message"] == "Lobby code not recognized."


@pytest.mark.asyncio
async def test_host_disconnect_closes_lobby_and_allows_a_new_host():
    application = BattleshipServer("host-key")
    async with serve(
        application.handler, "127.0.0.1", 0, process_request=health_check
    ) as websocket_server:
        port = websocket_server.sockets[0].getsockname()[1]
        uri = f"ws://127.0.0.1:{port}/ws"
        async with connect(uri) as host, connect(uri) as guest:
            await host.recv()
            await guest.recv()
            await host.send(
                json.dumps(
                    {
                        "type": "host_lobby",
                        "preferred_team": "Japan",
                        "token": "host-key",
                    }
                )
            )
            host_joined = await receive_type(host, "joined")
            await guest.send(
                json.dumps(
                    {
                        "type": "join_lobby",
                        "lobby_code": host_joined["lobby_code"],
                    }
                )
            )
            await receive_type(guest, "joined")
            await host.close()
            closed = await receive_type(guest, "lobby_closed")
            assert "host disconnected" in closed["message"].lower()

        async with connect(uri) as replacement:
            await replacement.recv()
            await replacement.send(
                json.dumps(
                    {
                        "type": "host_lobby",
                        "preferred_team": "US",
                        "token": "host-key",
                    }
                )
            )
            replacement_joined = await receive_type(replacement, "joined")
            assert replacement_joined["role"] == "host"
            assert replacement_joined["team"] == "US"


@pytest.mark.asyncio
async def test_native_client_network_worker_connects_and_synchronizes():
    application = BattleshipServer("desktop-token")
    async with serve(
        application.handler, "127.0.0.1", 0, process_request=health_check
    ) as websocket_server:
        port = websocket_server.sockets[0].getsockname()[1]
        incoming = queue.Queue()
        worker = NetworkWorker(
            f"ws://127.0.0.1:{port}/ws",
            incoming,
            mode="host",
            preferred_team="US",
            token="desktop-token",
        )
        worker.start()

        clock_message = await asyncio.to_thread(incoming.get, True, 2)
        joined_message = await asyncio.to_thread(incoming.get, True, 2)
        waiting_message = await asyncio.to_thread(incoming.get, True, 2)
        assert clock_message["type"] == "clock_sync"
        assert clock_message["round_trip_ms"] >= 0
        assert joined_message["type"] == "joined"
        assert joined_message["team"] == "US"
        assert joined_message["role"] == "host"
        assert joined_message["assignment"] == "chosen"
        assert len(joined_message["lobby_code"]) == 6
        assert waiting_message["type"] == "waiting"

        worker.close()
        await asyncio.to_thread(worker.join, 2)
        assert not worker.is_alive()
