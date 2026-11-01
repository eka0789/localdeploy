"""Notification channels (Discord/Telegram/Slack/webhook) management."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...core.db import get_db
from ...core.security import encrypt_secret
from ...models.infrastructure import NotificationChannel
from ...models.user import User
from ...services import notify
from ..deps import get_current_user, record_audit, require_permission, verify_csrf

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


class ChannelPayload(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    type: str = Field(pattern="^(discord|telegram|slack|webhook)$")
    url: str | None = Field(default=None, max_length=1000)
    bot_token: str | None = Field(default=None, max_length=500)
    chat_id: str | None = Field(default=None, max_length=120)
    events: list[str] = Field(default_factory=lambda: [
        "deployment.success", "deployment.failed", "container.died",
    ])
    is_active: bool = True


def _view(channel: NotificationChannel) -> dict:
    return {
        "id": str(channel.id),
        "name": channel.name,
        "type": channel.type,
        "has_url": bool(channel.url_encrypted),
        "has_bot_token": bool(channel.bot_token_encrypted),
        "chat_id": channel.chat_id,
        "events": channel.events or [],
        "is_active": channel.is_active,
        "last_sent_at": channel.last_sent_at.isoformat() if channel.last_sent_at else None,
        "last_error": channel.last_error,
        "created_at": channel.created_at.isoformat(),
    }


def _get(db: Session, channel_id: uuid.UUID) -> NotificationChannel:
    channel = db.query(NotificationChannel).get(channel_id)
    if channel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Channel not found")
    return channel


@router.get("")
def list_channels(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    channels = db.query(NotificationChannel).order_by(NotificationChannel.created_at).all()
    return [_view(c) for c in channels]


@router.post("", status_code=201, dependencies=[Depends(verify_csrf)])
def create_channel(payload: ChannelPayload, request: Request,
                   user: User = Depends(require_permission("settings.write")),
                   db: Session = Depends(get_db)):
    if payload.type in ("discord", "slack", "webhook") and not payload.url:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{payload.type} requires a webhook URL")
    if payload.type == "telegram" and (not payload.bot_token or not payload.chat_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Telegram requires bot_token and chat_id")

    channel = NotificationChannel(
        name=payload.name, type=payload.type,
        url_encrypted=encrypt_secret(payload.url) if payload.url else None,
        bot_token_encrypted=encrypt_secret(payload.bot_token) if payload.bot_token else None,
        chat_id=payload.chat_id,
        events=payload.events, is_active=payload.is_active,
    )
    db.add(channel)
    db.commit()
    db.refresh(channel)
    record_audit(db, user, "notifications.create", "notification_channel", str(channel.id),
                 {"name": channel.name, "type": channel.type}, request)
    return _view(channel)


@router.put("/{channel_id}", dependencies=[Depends(verify_csrf)])
def update_channel(channel_id: uuid.UUID, payload: ChannelPayload, request: Request,
                   user: User = Depends(require_permission("settings.write")),
                   db: Session = Depends(get_db)):
    channel = _get(db, channel_id)
    channel.name = payload.name
    channel.type = payload.type
    if payload.url:
        channel.url_encrypted = encrypt_secret(payload.url)
    if payload.bot_token:
        channel.bot_token_encrypted = encrypt_secret(payload.bot_token)
    channel.chat_id = payload.chat_id
    channel.events = payload.events
    channel.is_active = payload.is_active
    db.commit()
    record_audit(db, user, "notifications.update", "notification_channel", str(channel.id), {}, request)
    return _view(channel)


@router.delete("/{channel_id}", dependencies=[Depends(verify_csrf)])
def delete_channel(channel_id: uuid.UUID, request: Request,
                   user: User = Depends(require_permission("settings.write")),
                   db: Session = Depends(get_db)):
    channel = _get(db, channel_id)
    db.delete(channel)
    db.commit()
    record_audit(db, user, "notifications.delete", "notification_channel", None,
                 {"name": channel.name}, request)
    return {"ok": True}


@router.post("/{channel_id}/test")
def test_channel(channel_id: uuid.UUID,
                 user: User = Depends(require_permission("settings.write")),
                 db: Session = Depends(get_db)):
    channel = _get(db, channel_id)
    ok, error = notify._send(channel, "🧪 LocalDeploy test notification — it works!")
    if not ok:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Test failed: {error}")
    channel.last_sent_at = __import__("app.core.db", fromlist=["utcnow"]).utcnow()
    channel.last_error = None
    db.commit()
    return {"ok": True}
