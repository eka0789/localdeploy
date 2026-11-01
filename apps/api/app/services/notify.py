"""Outbound notifications (Discord / Telegram / Slack / generic webhook).

Dispatch is fire-and-forget: failures never block deployments and are only
recorded on the channel row + system log.
"""
from __future__ import annotations

import httpx

from ..core.db import utcnow
from ..core.security import decrypt_secret
from .log_hub import log_hub


def _render_message(event: str, context: dict) -> str:
    app = context.get("application_name", "unknown")
    status = context.get("status", event)
    commit = context.get("commit") or ""
    error = context.get("error") or ""
    duration = context.get("duration")
    parts = [f"🚀 LocalDeploy — {event}", f"App: {app}"]
    if status:
        parts.append(f"Status: {status}")
    if commit:
        parts.append(f"Commit: {commit}")
    if duration:
        parts.append(f"Duration: {duration}")
    if error:
        parts.append(f"Error: {error[:300]}")
    return "\n".join(parts)


def _send(channel, text: str) -> tuple[bool, str | None]:
    channel_type = channel.type
    try:
        if channel_type == "discord":
            url = decrypt_secret(channel.url_encrypted or "")
            resp = httpx.post(url, json={"content": text}, timeout=10)
        elif channel_type == "slack":
            url = decrypt_secret(channel.url_encrypted or "")
            resp = httpx.post(url, json={"text": text}, timeout=10)
        elif channel_type == "telegram":
            token = decrypt_secret(channel.bot_token_encrypted or "")
            resp = httpx.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": channel.chat_id, "text": text}, timeout=10,
            )
        elif channel_type == "webhook":
            url = decrypt_secret(channel.url_encrypted or "")
            resp = httpx.post(url, json={"event": text.splitlines()[0], "message": text}, timeout=10)
        else:
            return False, f"Unknown channel type: {channel_type}"
        if resp.status_code >= 400:
            return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
        return True, None
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"[:200]


def dispatch(session, event: str, context: dict) -> None:
    """Send `event` to every active channel subscribed to it. Sync (worker thread)."""
    from ..models.infrastructure import NotificationChannel

    if not (session.query(NotificationChannel).filter_by(is_active=True).count()):
        return
    text = _render_message(event, context)
    channels = (
        session.query(NotificationChannel)
        .filter_by(is_active=True)
        .all()
    )
    for channel in channels:
        events = channel.events or []
        if events and event not in events and "*" not in events:
            continue
        ok, error = _send(channel, text)
        channel.last_sent_at = utcnow()
        channel.last_error = error if not ok else None
        session.commit()
        if not ok:
            log_hub.publish_sync("system", {
                "type": "notification", "level": "error",
                "message": f"Notification '{channel.name}' failed: {error}",
            })
