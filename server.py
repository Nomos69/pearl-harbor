"""Authoritative two-player Pearl Harbor WebSocket server."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from http import HTTPStatus
import json
import logging
import os
import secrets
import ssl
import time
from typing import Any

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from game import BOARD_SIZE, TEAMS, Board, GameError, team_assets, team_fleet


LOGGER = logging.getLogger("battleship.server")
MAX_MESSAGE_SIZE = 16 * 1024


@dataclass(eq=False)
class Player:
    connection: ServerConnection
    name: str
    board: Board | None = None


class BattleshipServer:
    def __init__(self, token: str) -> None:
        self.token = token
        self.players: list[Player] = []
        self.phase = "waiting"
        self.turn: Player | None = None
        self.lock = asyncio.Lock()

    async def send(self, player: Player, payload: dict[str, Any]) -> None:
        try:
            await player.connection.send(json.dumps(payload))
        except ConnectionClosed:
            pass

    async def broadcast(self, payload: dict[str, Any]) -> None:
        await asyncio.gather(*(self.send(player, payload) for player in list(self.players)))

    async def broadcast_state(self) -> None:
        for player in list(self.players):
            opponent = next((item for item in self.players if item is not player), None)
            own_board = player.board
            opponent_board = opponent.board if opponent else None
            await self.send(
                player,
                {
                    "type": "state",
                    "phase": self.phase,
                    "current_turn": self.turn.name if self.turn else None,
                    "you": player.name,
                    "own_board": own_board.own_view() if own_board else None,
                    "own_fleet": own_board.own_fleet_view() if own_board else None,
                    "target_board": opponent_board.target_view() if opponent_board else None,
                    "own_ships_remaining": own_board.ships_remaining if own_board else None,
                    "opponent_ships_remaining": (
                        opponent_board.ships_remaining if opponent_board else None
                    ),
                    "server_time_ns": time.time_ns(),
                },
            )

    async def handle_join(self, connection: ServerConnection, message: dict[str, Any]) -> Player | None:
        supplied_token = str(message.get("token", ""))
        if not secrets.compare_digest(supplied_token, self.token):
            await connection.send(json.dumps({"type": "error", "message": "Invalid game token."}))
            await connection.close(code=1008, reason="invalid token")
            return None

        preferred_team = str(
            message.get("preferred_team", message.get("name", ""))
        ).strip()

        async with self.lock:
            if len(self.players) >= 2:
                await connection.send(
                    json.dumps({"type": "error", "message": "This game already has two players."})
                )
                await connection.close(code=1013, reason="game full")
                return None

            player_number = len(self.players) + 1
            if player_number == 1:
                if preferred_team not in TEAMS:
                    await connection.send(
                        json.dumps(
                            {
                                "type": "error",
                                "message": "The first player must choose US or Japan.",
                            }
                        )
                    )
                    await connection.close(code=1008, reason="invalid team")
                    return None
                assigned_team = preferred_team
                assignment = "chosen"
            else:
                claimed_teams = {player.name for player in self.players}
                assigned_team = next(team for team in TEAMS if team not in claimed_teams)
                assignment = "automatic"

            if any(player.name == assigned_team for player in self.players):
                await connection.send(
                    json.dumps(
                        {
                            "type": "error",
                            "message": "No unclaimed country is available.",
                        }
                    )
                )
                await connection.close(code=1013, reason="no available team")
                return None
            player = Player(connection=connection, name=assigned_team)
            self.players.append(player)
            if len(self.players) == 2:
                self.phase = "placement"

        await self.send(
            player,
            {
                "type": "joined",
                "player_number": player_number,
                "team": assigned_team,
                "assignment": assignment,
                "preferred_team": preferred_team or None,
                "board_size": BOARD_SIZE,
                "fleet": team_fleet(assigned_team),
                "fleet_assets": team_assets(assigned_team),
            },
        )
        LOGGER.info(
            "%s joined as player %d (%s assignment; preference=%s)",
            assigned_team,
            player_number,
            assignment,
            preferred_team or "none",
        )
        if len(self.players) == 1:
            await self.send(player, {"type": "waiting", "message": "Waiting for Player 2..."})
        else:
            await self.broadcast(
                {"type": "players_ready", "players": [item.name for item in self.players]}
            )
            await self.broadcast({"type": "action_required", "action": "place_fleet"})
        return player

    async def handle_place(self, player: Player, message: dict[str, Any]) -> None:
        if self.phase != "placement":
            raise GameError("Fleet placement is not available now.")
        if player.board is not None:
            raise GameError("Your fleet is already placed.")
        placements = message.get("ships")
        if not isinstance(placements, list):
            raise GameError("The ships field must be a list.")
        board = Board.from_placements(
            placements,
            fleet_spec=team_fleet(player.name),
            ship_assets=team_assets(player.name),
        )

        async with self.lock:
            player.board = board
            ready = all(item.board is not None for item in self.players) and len(self.players) == 2
            if ready:
                self.phase = "playing"
                self.turn = self.players[0]

        await self.send(player, {"type": "fleet_ready"})
        await self.broadcast(
            {"type": "player_ready", "player": player.name, "ready_count": sum(p.board is not None for p in self.players)}
        )
        if ready:
            await self.broadcast(
                {"type": "game_started", "first_player": self.turn.name, "server_time_ns": time.time_ns()}
            )
            await self.broadcast_state()
            await self.send(self.turn, {"type": "action_required", "action": "attack"})

    async def handle_attack(self, player: Player, message: dict[str, Any]) -> None:
        if self.phase != "playing":
            raise GameError("The game is not accepting attacks now.")
        if self.turn is not player:
            raise GameError("Wait for your turn.")
        opponent = next((item for item in self.players if item is not player), None)
        if opponent is None or opponent.board is None:
            raise GameError("The opponent is not ready.")

        result = opponent.board.fire(str(message.get("coordinate", "")))
        event = {
            "type": "attack_result",
            "attacker": player.name,
            **result,
            "server_time_ns": time.time_ns(),
        }
        await self.broadcast(event)

        if opponent.board.all_sunk:
            self.phase = "finished"
            self.turn = None
            await self.broadcast_state()
            await self.broadcast(
                {"type": "game_over", "winner": player.name, "server_time_ns": time.time_ns()}
            )
            LOGGER.info("Game over; winner=%s", player.name)
            return

        # House rule: a successful hit earns another shot; only a miss passes play.
        self.turn = player if result["result"] == "hit" else opponent
        await self.broadcast_state()
        await self.send(self.turn, {"type": "action_required", "action": "attack"})

    async def handle_message(self, player: Player, message: dict[str, Any]) -> None:
        message_type = message.get("type")
        try:
            if message_type == "place_fleet":
                await self.handle_place(player, message)
            elif message_type == "attack":
                await self.handle_attack(player, message)
            else:
                raise GameError("Unknown message type.")
        except GameError as exc:
            await self.send(player, {"type": "error", "message": str(exc)})
            if self.phase == "placement" and player.board is None:
                await self.send(player, {"type": "action_required", "action": "place_fleet"})
            elif self.phase == "playing" and self.turn is player:
                await self.send(player, {"type": "action_required", "action": "attack"})

    async def disconnect(self, player: Player) -> None:
        async with self.lock:
            if player not in self.players:
                return
            self.players.remove(player)
            for remaining in self.players:
                remaining.board = None
            self.phase = "waiting"
            self.turn = None
        LOGGER.info("%s disconnected", player.name)
        await self.broadcast(
            {
                "type": "opponent_left",
                "message": f"{player.name} disconnected. The room has been reset.",
            }
        )
        await self.broadcast({"type": "waiting", "message": "Waiting for Player 2..."})

    async def handler(self, connection: ServerConnection) -> None:
        player: Player | None = None
        await connection.send(
            json.dumps(
                {
                    "type": "hello",
                    "protocol": 1,
                    "server_time_ns": time.time_ns(),
                }
            )
        )
        try:
            async for raw_message in connection:
                try:
                    message = json.loads(raw_message)
                    if not isinstance(message, dict):
                        raise ValueError
                except (json.JSONDecodeError, ValueError, TypeError):
                    await connection.send(
                        json.dumps({"type": "error", "message": "Messages must be JSON objects."})
                    )
                    continue

                if message.get("type") == "time_sync":
                    if "client_send_ms" in message:
                        received_ms = time.time_ns() / 1_000_000
                        await connection.send(
                            json.dumps(
                                {
                                    "type": "time_sync_reply",
                                    "client_send_ms": message.get("client_send_ms"),
                                    "server_receive_ms": received_ms,
                                    "server_send_ms": time.time_ns() / 1_000_000,
                                }
                            )
                        )
                        continue
                    received_ns = time.time_ns()
                    await connection.send(
                        json.dumps(
                            {
                                "type": "time_sync_reply",
                                "client_send_ns": message.get("client_send_ns"),
                                "server_receive_ns": received_ns,
                                "server_send_ns": time.time_ns(),
                            }
                        )
                    )
                    continue
                if player is None:
                    if message.get("type") != "join":
                        await connection.send(
                            json.dumps({"type": "error", "message": "Join before playing."})
                        )
                        continue
                    player = await self.handle_join(connection, message)
                    if player is None:
                        return
                    continue
                await self.handle_message(player, message)
        except ConnectionClosed:
            pass
        finally:
            if player is not None:
                await self.disconnect(player)


def health_check(connection: ServerConnection, request: Any) -> Any:
    if request.path == "/healthz":
        return connection.respond(HTTPStatus.OK, "OK\n")
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pearl Harbor WebSocket server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", default=8765, type=int)
    parser.add_argument("--token", default=os.environ.get("BATTLESHIP_TOKEN"))
    parser.add_argument("--certfile", help="TLS certificate chain for wss://")
    parser.add_argument("--keyfile", help="TLS private key for wss://")
    return parser.parse_args()


async def run(args: argparse.Namespace) -> None:
    if not args.token:
        raise SystemExit("Set BATTLESHIP_TOKEN or pass --token. Refusing to start without a token.")
    if bool(args.certfile) != bool(args.keyfile):
        raise SystemExit("Provide both --certfile and --keyfile, or neither.")
    ssl_context = None
    if args.certfile:
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_context.load_cert_chain(args.certfile, args.keyfile)

    application = BattleshipServer(args.token)
    protocol = "wss" if ssl_context else "ws"
    LOGGER.info("Listening on %s://%s:%d", protocol, args.host, args.port)
    async with serve(
        application.handler,
        args.host,
        args.port,
        ssl=ssl_context,
        process_request=health_check,
        ping_interval=20,
        ping_timeout=20,
        max_size=MAX_MESSAGE_SIZE,
    ) as websocket_server:
        await websocket_server.serve_forever()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        asyncio.run(run(parse_args()))
    except KeyboardInterrupt:
        LOGGER.info("Server stopped")


if __name__ == "__main__":
    main()
