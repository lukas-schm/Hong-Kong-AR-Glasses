"""Realtime event bus over WebSockets.

A single hub the whole demo talks through:

  · the AR glasses (#glasses), the model monitor (#monitor) and the CDARS
    workbench (#cdars) each open a WebSocket and announce a role
  · HUD state / navigation / patient-selection messages are *relayed* between
    clients so the glasses and the monitor stay mirror-synced live
  · the server publishes plain-language *activity* events (voice → intent →
    tool → model → db-write → reply) which every monitor renders
  · *data-change* events tell clients a record was written and to refetch

Sync code (FastAPI threadpool endpoints, agent tools) publishes via the
thread-safe `publish()`, which hops back onto the event loop.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from fastapi import WebSocket

# Messages a client may send that the hub relays to the *other* clients.
RELAY_TYPES = {"hud", "nav", "select", "ping-presence"}


class Bus:
    def __init__(self) -> None:
        self._clients: Dict[WebSocket, str] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._seq = 0

    # ── lifecycle ────────────────────────────────────────────────────────────
    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def connect(self, ws: WebSocket, role: str) -> None:
        await ws.accept()
        self._clients[ws] = role
        await self._send(ws, {"type": "welcome", "role": role, "clients": self.roles()})
        await self.broadcast_presence()

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.pop(ws, None)

    def roles(self) -> List[str]:
        return sorted(self._clients.values())

    # ── sending ──────────────────────────────────────────────────────────────
    def _stamp(self, event: Dict[str, Any]) -> Dict[str, Any]:
        self._seq += 1
        event.setdefault("seq", self._seq)
        event.setdefault("ts", datetime.now(timezone.utc).isoformat(timespec="seconds"))
        return event

    async def _send(self, ws: WebSocket, event: Dict[str, Any]) -> None:
        try:
            await ws.send_json(event)
        except Exception:
            self.disconnect(ws)

    async def broadcast(self, event: Dict[str, Any], exclude: Optional[WebSocket] = None) -> None:
        event = self._stamp(event)
        for ws in list(self._clients):
            if ws is exclude:
                continue
            await self._send(ws, event)

    async def broadcast_presence(self) -> None:
        await self.broadcast({"type": "presence", "clients": self.roles()})

    # ── thread-safe publish from sync code ───────────────────────────────────
    def publish(self, event: Dict[str, Any]) -> None:
        """Publish from anywhere (including FastAPI threadpool threads)."""
        if self._loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(self.broadcast(event), self._loop)
        except RuntimeError:
            pass

    def activity(
        self,
        kind: str,
        text: str,
        *,
        text_zh: Optional[str] = None,
        detail: str = "",
        reference_key: Optional[str] = None,
        ok: Optional[bool] = None,
        source: str = "agent",
    ) -> None:
        """Publish one plain-language activity line for the monitors."""
        self.publish({
            "type": "activity",
            "kind": kind,                      # voice|intent|tool|model|db-write|reply|info
            "text": text,
            "textZh": text_zh,
            "detail": detail,
            "referenceKey": reference_key,
            "ok": ok,
            "source": source,
        })

    def data_change(self, reference_key: str, *, fields: Optional[List[str]] = None) -> None:
        self.publish({"type": "data-change", "referenceKey": reference_key, "fields": fields or []})


bus = Bus()
