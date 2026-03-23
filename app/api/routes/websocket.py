import json
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.realtime_service import get_realtime_service


router = APIRouter(tags=["realtime"])
logger = logging.getLogger(__name__)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


@router.websocket("/ws/realtime")
async def realtime_websocket(websocket: WebSocket) -> None:
    realtime_service = get_realtime_service()
    await realtime_service.connect(websocket)

    try:
        while True:
            raw_message = await websocket.receive_text()
            try:
                message = json.loads(raw_message)
            except json.JSONDecodeError:
                await realtime_service.send_personal_event(
                    websocket,
                    {
                        "type": "error",
                        "timestamp": now_iso(),
                        "message": "Expected a JSON payload.",
                    },
                )
                continue

            action = message.get("action")
            if action == "ping":
                await realtime_service.send_personal_event(
                    websocket,
                    {
                        "type": "pong",
                        "timestamp": now_iso(),
                    },
                )
                continue

            if action == "subscribe":
                call_sid = message.get("call_sid")
                if call_sid:
                    await realtime_service.subscribe(websocket, call_sid)
                continue

            if action == "unsubscribe":
                call_sid = message.get("call_sid")
                if call_sid:
                    await realtime_service.unsubscribe(websocket, call_sid)
                continue

            await realtime_service.send_personal_event(
                websocket,
                {
                    "type": "warning",
                    "timestamp": now_iso(),
                    "message": f"Unsupported websocket action: {action}",
                },
            )
    except WebSocketDisconnect:
        logger.info("Realtime websocket disconnected")
    finally:
        await realtime_service.disconnect(websocket)
