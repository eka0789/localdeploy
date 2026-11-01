"""In-process pub/sub hub for WebSocket log streaming.

Channels:
  deploy:{deployment_id}   — deployment build logs
  applogs:{application_id} — live container logs
  system                   — platform-level events
  metrics                  — periodic monitor snapshots
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

MAX_QUEUE = 500


@dataclass
class Subscriber:
    queue: asyncio.Queue
    channel: str


class LogHub:
    def __init__(self) -> None:
        self._channels: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._lock = asyncio.Lock()
        self._ring: list[dict[str, Any]] = []
        self._ring_size = 500

    async def subscribe(self, channel: str) -> Subscriber:
        queue: asyncio.Queue = asyncio.Queue(maxsize=MAX_QUEUE)
        async with self._lock:
            self._channels[channel].add(queue)
        return Subscriber(queue=queue, channel=channel)

    async def unsubscribe(self, subscriber: Subscriber) -> None:
        async with self._lock:
            qs = self._channels.get(subscriber.channel)
            if qs:
                qs.discard(subscriber.queue)
                if not qs:
                    self._channels.pop(subscriber.channel, None)

    async def publish(self, channel: str, message: dict[str, Any]) -> None:
        async with self._lock:
            queues = list(self._channels.get(channel, ()))
        for queue in queues:
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:  # slow consumer — drop oldest-ish behavior
                pass
        if channel == "system":
            self._ring.append(message)
            if len(self._ring) > self._ring_size:
                del self._ring[: len(self._ring) - self._ring_size]

    def publish_sync(self, channel: str, message: dict[str, Any]) -> None:
        """Publish from sync code (worker threads) safely."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # no running loop yet; deployment logs are also persisted to DB
        loop.create_task(self.publish(channel, message))

    def recent_system(self, limit: int = 100) -> list[dict[str, Any]]:
        return list(self._ring[-limit:])


log_hub = LogHub()
