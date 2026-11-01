"""System/platform logs (live via WebSocket + recent history)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from ...core.db import get_db, utcnow
from ...models.user import User, UserSession
from ...services.log_hub import log_hub
from ..deps import SESSION_COOKIE, get_current_user, hash_token_ws_auth

router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get("/system")
def recent_system_logs(limit: int = 100, user: User = Depends(get_current_user)):
    return {"logs": log_hub.recent_system(min(limit, 500))}


@router.websocket("/system/stream")
async def system_logs_stream(websocket: WebSocket, db: Session = Depends(get_db)):
    token = websocket.cookies.get(SESSION_COOKIE)
    row = (db.query(UserSession)
           .filter(UserSession.token_hash == hash_token_ws_auth(token or ""),
                   UserSession.revoked_at.is_(None)).first() if token else None)
    if row is None or row.expires_at < utcnow():
        await websocket.close(code=4401)
        return
    await websocket.accept()
    # Replay recent events first
    for event in log_hub.recent_system(50):
        await websocket.send_json(event)
    subscriber = await log_hub.subscribe("system")
    try:
        while True:
            message = await subscriber.queue.get()
            await websocket.send_json(message)
    except WebSocketDisconnect:
        pass
    finally:
        await log_hub.unsubscribe(subscriber)
