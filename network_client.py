"""Threaded WebSocket transport used by the native desktop client."""

from __future__ import annotations

import asyncio
import contextlib
import json
import queue
import threading
import time
from typing import Any

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed


class NetworkWorker(threading.Thread):
    """Run asyncio WebSocket I/O away from Tk's UI thread."""

    def __init__(
        self,
        uri: str,
        incoming: queue.Queue[dict[str, Any]],
        *,
        mode: str,
        preferred_team: str = "",
        token: str = "",
        lobby_code: str = "",
    ) -> None:
        super().__init__(daemon=True)
        if mode not in {"host", "join"}:
            raise ValueError("Network mode must be 'host' or 'join'.")
        self.uri = uri
        self.mode = mode
        self.preferred_team = preferred_team
        self.token = token
        self.lobby_code = lobby_code.strip().upper()
        self.incoming = incoming
        self.loop: asyncio.AbstractEventLoop | None = None
        self.outgoing: asyncio.Queue[dict[str, Any]] | None = None
        self.websocket: Any = None

    def send(self, message: dict[str, Any]) -> None:
        if self.loop and self.outgoing:
            self.loop.call_soon_threadsafe(self.outgoing.put_nowait, message)

    def close(self) -> None:
        if self.loop and self.websocket:
            self.loop.call_soon_threadsafe(
                lambda: asyncio.create_task(self.websocket.close(code=1000))
            )

    def run(self) -> None:
        try:
            asyncio.run(self._run())
        except Exception as exc:  # report failures to Tk instead of crashing the thread
            self.incoming.put({"type": "network_error", "message": str(exc)})

    async def _sender(self) -> None:
        assert self.outgoing is not None
        while True:
            message = await self.outgoing.get()
            await self.websocket.send(json.dumps(message))

    async def _run(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.outgoing = asyncio.Queue()
        try:
            async with connect(
                self.uri, ping_interval=20, ping_timeout=20, max_size=16 * 1024
            ) as websocket:
                self.websocket = websocket
                hello = json.loads(await websocket.recv())
                if hello.get("type") != "hello":
                    raise RuntimeError("This is not a compatible Pearl Harbor server.")

                client_send_ms = time.time_ns() / 1_000_000
                await websocket.send(
                    json.dumps({"type": "time_sync", "client_send_ms": client_send_ms})
                )
                reply = json.loads(await websocket.recv())
                client_receive_ms = time.time_ns() / 1_000_000
                if reply.get("type") != "time_sync_reply":
                    raise RuntimeError("The server did not complete clock synchronization.")
                server_receive_ms = float(reply["server_receive_ms"])
                server_send_ms = float(reply["server_send_ms"])
                offset_ms = (
                    (server_receive_ms - client_send_ms)
                    + (server_send_ms - client_receive_ms)
                ) / 2
                round_trip_ms = (
                    (client_receive_ms - client_send_ms)
                    - (server_send_ms - server_receive_ms)
                )
                self.incoming.put(
                    {
                        "type": "clock_sync",
                        "offset_ms": offset_ms,
                        "round_trip_ms": max(0, round_trip_ms),
                    }
                )
                if self.mode == "host":
                    entry_message = {
                        "type": "host_lobby",
                        "preferred_team": self.preferred_team,
                        "token": self.token,
                    }
                else:
                    entry_message = {
                        "type": "join_lobby",
                        "lobby_code": self.lobby_code,
                    }
                await websocket.send(json.dumps(entry_message))

                sender = asyncio.create_task(self._sender())
                try:
                    async for raw_message in websocket:
                        self.incoming.put(json.loads(raw_message))
                finally:
                    sender.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await sender
        except ConnectionClosed as exc:
            self.incoming.put(
                {
                    "type": "connection_closed",
                    "message": exc.reason or f"Connection closed with code {exc.code}.",
                }
            )
        except OSError as exc:
            self.incoming.put(
                {"type": "network_error", "message": f"Could not connect to {self.uri}: {exc}"}
            )
        finally:
            self.websocket = None
