"""Interactive terminal client for Pearl Harbor."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from typing import Any

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from game import FLEET, TEAMS, Board, GameError, parse_coordinate


def draw_board(title: str, rows: list[str]) -> None:
    print(f"\n{title}")
    print("    " + " ".join("ABCDEFGHIJ"))
    for number, row in enumerate(rows, start=1):
        print(f"{number:>2}  " + " ".join(row))


def draw_state(message: dict[str, Any]) -> None:
    own_board = message.get("own_board")
    target_board = message.get("target_board")
    if own_board:
        draw_board("YOUR BOARD  (S=ship, X=hit, o=miss)", own_board)
    if target_board:
        draw_board("TARGET BOARD  (X=hit, o=miss)", target_board)
    print(
        f"\nTurn: {message.get('current_turn') or '-'} | "
        f"Ships remaining: you={message.get('own_ships_remaining')}, "
        f"opponent={message.get('opponent_ships_remaining')}"
    )


def read_fleet(fleet_spec: dict[str, int]) -> list[dict[str, str]]:
    print("\nPlace your fleet. Coordinates use A1 through J10.")
    print("Ships may be horizontal or vertical; for example A1 A5.")
    while True:
        placements: list[dict[str, str]] = []
        for name, length in fleet_spec.items():
            while True:
                entry = input(f"{name} (length {length}) start end: ").strip().split()
                if len(entry) != 2:
                    print("Enter exactly two coordinates, such as A1 A5.")
                    continue
                placements.append({"name": name, "start": entry[0], "end": entry[1]})
                break
        try:
            Board.from_placements(placements, fleet_spec=fleet_spec)
            return placements
        except GameError as exc:
            print(f"Placement error: {exc}\nPlease place the entire fleet again.")


def read_attack() -> str:
    while True:
        coordinate = input("\nYour turn. Attack coordinate: ").strip().upper()
        try:
            parse_coordinate(coordinate)
            return coordinate
        except GameError as exc:
            print(exc)


async def synchronize_clock(websocket: Any) -> None:
    """Estimate server offset using the four timestamps used by NTP."""
    client_send_ns = time.time_ns()
    await websocket.send(
        json.dumps({"type": "time_sync", "client_send_ns": client_send_ns})
    )
    reply = json.loads(await websocket.recv())
    client_receive_ns = time.time_ns()
    if reply.get("type") != "time_sync_reply":
        raise RuntimeError("Expected a time_sync_reply from the server.")
    server_receive_ns = int(reply["server_receive_ns"])
    server_send_ns = int(reply["server_send_ns"])
    offset_ns = (
        (server_receive_ns - client_send_ns)
        + (server_send_ns - client_receive_ns)
    ) / 2
    round_trip_ns = (
        (client_receive_ns - client_send_ns)
        - (server_send_ns - server_receive_ns)
    )
    print(
        f"Clock check: estimated server offset {offset_ns / 1_000_000:+.2f} ms; "
        f"WebSocket round trip {round_trip_ns / 1_000_000:.2f} ms"
    )


async def play(args: argparse.Namespace) -> None:
    token = args.token or os.environ.get("BATTLESHIP_TOKEN")
    if not token:
        raise SystemExit("Set BATTLESHIP_TOKEN or pass --token.")
    name = args.team or await asyncio.to_thread(input, "Team (US or Japan): ")
    if name not in TEAMS:
        raise SystemExit("Team must be exactly US or Japan.")
    fleet_spec = dict(FLEET)
    print(f"Connecting to {args.uri} ...")

    try:
        async with connect(args.uri, ping_interval=20, ping_timeout=20, max_size=16 * 1024) as websocket:
            hello = json.loads(await websocket.recv())
            if hello.get("type") != "hello":
                raise RuntimeError("The endpoint isn't a compatible Pearl Harbor server.")
            await synchronize_clock(websocket)
            await websocket.send(json.dumps({"type": "join", "name": name.strip(), "token": token}))

            async for raw_message in websocket:
                message = json.loads(raw_message)
                message_type = message.get("type")
                if message_type == "joined":
                    fleet_spec = {
                        str(ship_name): int(length)
                        for ship_name, length in message["fleet"].items()
                    }
                    print(f"Joined as Player {message['player_number']} ({name.strip()}).")
                elif message_type in {"waiting", "opponent_left"}:
                    print(message["message"])
                elif message_type == "players_ready":
                    print("Players: " + " vs ".join(message["players"]))
                elif message_type == "action_required":
                    if message["action"] == "place_fleet":
                        ships = await asyncio.to_thread(read_fleet, fleet_spec)
                        await websocket.send(json.dumps({"type": "place_fleet", "ships": ships}))
                    elif message["action"] == "attack":
                        coordinate = await asyncio.to_thread(read_attack)
                        await websocket.send(json.dumps({"type": "attack", "coordinate": coordinate}))
                elif message_type == "fleet_ready":
                    print("Your fleet is locked in and remains hidden from your opponent.")
                elif message_type == "player_ready":
                    print(f"{message['player']} is ready ({message['ready_count']}/2).")
                elif message_type == "game_started":
                    print(f"Game started. {message['first_player']} attacks first.")
                elif message_type == "state":
                    draw_state(message)
                elif message_type == "attack_result":
                    description = message["result"].upper()
                    if message.get("sunk"):
                        description += f" — sunk {message['ship']}"
                    print(f"\n{message['attacker']} attacked {message['coordinate']}: {description}")
                elif message_type == "error":
                    print(f"Server error: {message['message']}")
                elif message_type == "game_over":
                    print(f"\nGAME OVER — {message['winner']} wins!")
                    return
    except ConnectionClosed as exc:
        print(f"Connection closed ({exc.code}): {exc.reason or 'no reason supplied'}")
    except OSError as exc:
        raise SystemExit(f"Could not connect to {args.uri}: {exc}") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pearl Harbor terminal client")
    parser.add_argument("--uri", default="ws://127.0.0.1:8765")
    parser.add_argument("--team", choices=TEAMS)
    parser.add_argument("--token")
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(play(parse_args()))
