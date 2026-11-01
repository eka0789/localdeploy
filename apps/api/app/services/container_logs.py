"""Live container log streaming into the log hub (thread-per-container)."""
from __future__ import annotations

import threading
import time

from .docker_client import docker_service
from .log_hub import log_hub


class LogStreamManager:
    """Keeps one follower thread per application container."""

    def __init__(self) -> None:
        self._streams: dict[str, threading.Thread] = {}
        self._lock = threading.Lock()
        self._stop: dict[str, threading.Event] = {}

    def ensure_stream(self, app_id: str, container_ref: str) -> bool:
        """Start following logs for the app container. Returns True when active."""
        with self._lock:
            thread = self._streams.get(app_id)
            if thread and thread.is_alive():
                return True
            if not docker_service.available:
                return False
            stop_event = threading.Event()
            thread = threading.Thread(
                target=self._follow, args=(app_id, container_ref, stop_event), daemon=True
            )
            self._streams[app_id] = thread
            self._stop[app_id] = stop_event
            thread.start()
            return True

    def stop_stream(self, app_id: str) -> None:
        with self._lock:
            event = self._stop.get(app_id)
            if event:
                event.set()

    def _follow(self, app_id: str, container_ref: str, stop_event: threading.Event) -> None:
        container = docker_service.get_container(container_ref)
        if container is None:
            return
        channel = f"applogs:{app_id}"
        try:
            for line in container.logs(stream=True, follow=True, tail=200):
                if stop_event.is_set():
                    break
                text = line.decode(errors="replace").rstrip("\n")
                if text:
                    log_hub.publish_sync(channel, {
                        "application_id": app_id, "message": text, "stream": "stdout",
                    })
        except Exception:
            pass  # container stopped / engine went away


log_streams = LogStreamManager()
