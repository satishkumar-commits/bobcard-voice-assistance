import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from fastapi import WebSocket


logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@dataclass
class ConnectionState:
    websocket: WebSocket
    subscribed_calls: set[str] = field(default_factory=set)
    timer_tasks: dict[str, asyncio.Task] = field(default_factory=dict)


class RealtimeService:
    def __init__(self) -> None:
        self._connections: dict[int, ConnectionState] = {}
        self._call_state: dict[str, dict[str, Any]] = {}
        self._transcript_history: dict[str, list[dict[str, Any]]] = {}
        self._latency_history: dict[str, list[dict[str, Any]]] = {}
        self._global_latency_history: list[dict[str, Any]] = []
        self._speaking_state: dict[str, dict[str, bool]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        connection_id = id(websocket)
        async with self._lock:
            self._connections[connection_id] = ConnectionState(websocket=websocket)
        await self._send_json(
            websocket,
            {
                "type": "connected",
                "timestamp": utc_now().isoformat(),
                "message": "Realtime connection established.",
            },
        )

    async def disconnect(self, websocket: WebSocket) -> None:
        connection_id = id(websocket)
        async with self._lock:
            state = self._connections.pop(connection_id, None)
        if not state:
            return

        for task in state.timer_tasks.values():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def subscribe(self, websocket: WebSocket, call_sid: str) -> None:
        connection_id = id(websocket)
        async with self._lock:
            state = self._connections.get(connection_id)
            if state is None:
                return
            state.subscribed_calls.add(call_sid)
            if call_sid not in state.timer_tasks:
                state.timer_tasks[call_sid] = asyncio.create_task(self._timer_loop(websocket, call_sid))

        await self._send_json(
            websocket,
            {
                "type": "subscribed",
                "call_sid": call_sid,
                "timestamp": utc_now().isoformat(),
            },
        )
        await self._send_snapshot(websocket, call_sid)

    async def unsubscribe(self, websocket: WebSocket, call_sid: str) -> None:
        connection_id = id(websocket)
        async with self._lock:
            state = self._connections.get(connection_id)
            if state is None:
                return
            state.subscribed_calls.discard(call_sid)
            task = state.timer_tasks.pop(call_sid, None)

        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        await self._send_json(
            websocket,
            {
                "type": "unsubscribed",
                "call_sid": call_sid,
                "timestamp": utc_now().isoformat(),
            },
        )

    async def send_personal_event(self, websocket: WebSocket, event: dict[str, Any]) -> None:
        await self._send_json(websocket, event)

    async def publish_call_status(
        self,
        *,
        call_sid: str,
        call_id: int | None,
        status: str,
        started_at: datetime | None = None,
        ended_at: datetime | None = None,
        language: str | None = None,
        final_outcome: str | None = None,
        phase: str | None = None,
    ) -> None:
        snapshot = self._call_state.setdefault(call_sid, {})
        snapshot.update(
            {
                "call_sid": call_sid,
                "call_id": str(call_id) if call_id is not None else snapshot.get("call_id"),
                "status": status,
                "started_at": ensure_utc(started_at).isoformat()
                if isinstance(started_at, datetime)
                else snapshot.get("started_at", utc_now().isoformat()),
                "ended_at": ensure_utc(ended_at).isoformat() if isinstance(ended_at, datetime) else snapshot.get("ended_at"),
                "language": language or snapshot.get("language"),
                "final_outcome": final_outcome or snapshot.get("final_outcome"),
                "phase": phase or snapshot.get("phase"),
                "updated_at": utc_now().isoformat(),
            }
        )
        await self.broadcast_call_event(
            call_sid,
            {
                "type": "call_status",
                "call_sid": call_sid,
                "call_id": snapshot.get("call_id"),
                "status": status,
                "language": snapshot.get("language"),
                "final_outcome": snapshot.get("final_outcome"),
                "phase": snapshot.get("phase"),
                "started_at": snapshot.get("started_at"),
                "ended_at": snapshot.get("ended_at"),
                "timestamp": utc_now().isoformat(),
            },
        )
        if status in {"completed", "busy", "failed", "no-answer", "canceled", "stopped"}:
            await self.publish_call_summary(call_sid)

    async def publish_call_phase(self, call_sid: str, phase: str) -> None:
        snapshot = self._call_state.setdefault(call_sid, {})
        snapshot["call_sid"] = call_sid
        snapshot["phase"] = phase
        snapshot["updated_at"] = utc_now().isoformat()
        await self.broadcast_call_event(
            call_sid,
            {
                "type": "call_phase",
                "call_sid": call_sid,
                "phase": phase,
                "status": snapshot.get("status"),
                "timestamp": utc_now().isoformat(),
            },
        )

    async def publish_business_state(self, call_sid: str, business_state: str) -> None:
        snapshot = self._call_state.setdefault(call_sid, {})
        snapshot["call_sid"] = call_sid
        snapshot["business_state"] = business_state
        snapshot["updated_at"] = utc_now().isoformat()
        await self.broadcast_call_event(
            call_sid,
            {
                "type": "business_state",
                "call_sid": call_sid,
                "business_state": business_state,
                "phase": snapshot.get("phase"),
                "status": snapshot.get("status"),
                "timestamp": utc_now().isoformat(),
            },
        )

    async def publish_audio_quality(self, call_sid: str, quality_state: dict[str, Any]) -> None:
        snapshot = self._call_state.setdefault(call_sid, {})
        snapshot["audio_quality"] = quality_state
        await self.broadcast_call_event(
            call_sid,
            {
                "type": "audio_quality",
                "call_sid": call_sid,
                "audio_quality": quality_state,
                "timestamp": utc_now().isoformat(),
            },
        )

    async def publish_main_points(self, call_sid: str, main_points: dict[str, Any]) -> None:
        snapshot = self._call_state.setdefault(call_sid, {})
        snapshot["main_points"] = main_points
        snapshot["updated_at"] = utc_now().isoformat()
        await self.broadcast_call_event(
            call_sid,
            {
                "type": "main_points",
                "call_sid": call_sid,
                "main_points": main_points,
                "timestamp": utc_now().isoformat(),
            },
        )

    async def publish_response_plan(self, call_sid: str, response_plan: dict[str, Any]) -> None:
        snapshot = self._call_state.setdefault(call_sid, {})
        snapshot["response_plan"] = response_plan
        snapshot["updated_at"] = utc_now().isoformat()
        await self.broadcast_call_event(
            call_sid,
            {
                "type": "response_plan",
                "call_sid": call_sid,
                "response_plan": response_plan,
                "timestamp": utc_now().isoformat(),
            },
        )

    async def publish_gemini_decision(self, call_sid: str, gemini_decision: dict[str, Any]) -> None:
        snapshot = self._call_state.setdefault(call_sid, {})
        snapshot["gemini_decision"] = gemini_decision
        metrics = snapshot.setdefault("metrics", {})
        metrics["gemini_requests"] = int(metrics.get("gemini_requests", 0)) + 1
        if gemini_decision.get("used_fallback"):
            metrics["gemini_fallbacks"] = int(metrics.get("gemini_fallbacks", 0)) + 1
        snapshot["updated_at"] = utc_now().isoformat()
        await self.broadcast_call_event(
            call_sid,
            {
                "type": "gemini_decision",
                "call_sid": call_sid,
                "gemini_decision": gemini_decision,
                "timestamp": utc_now().isoformat(),
            },
        )

    async def publish_tts_status(self, call_sid: str, tts_status: dict[str, Any]) -> None:
        snapshot = self._call_state.setdefault(call_sid, {})
        snapshot["tts_status"] = tts_status
        metrics = snapshot.setdefault("metrics", {})
        stage = tts_status.get("stage")
        if stage == "tts_requested":
            metrics["tts_requests"] = int(metrics.get("tts_requests", 0)) + 1
        elif stage == "playback_started":
            metrics["playback_starts"] = int(metrics.get("playback_starts", 0)) + 1
        snapshot["updated_at"] = utc_now().isoformat()
        await self.broadcast_call_event(
            call_sid,
            {
                "type": "tts_status",
                "call_sid": call_sid,
                "tts_status": tts_status,
                "timestamp": utc_now().isoformat(),
            },
        )

    async def publish_interruption_status(self, call_sid: str, interruption_status: dict[str, Any]) -> None:
        snapshot = self._call_state.setdefault(call_sid, {})
        snapshot["interruption_status"] = interruption_status
        metrics = snapshot.setdefault("metrics", {})
        if interruption_status.get("stage") == "playback_interrupted":
            metrics["interruptions"] = int(interruption_status.get("count") or metrics.get("interruptions", 0))
        snapshot["updated_at"] = utc_now().isoformat()
        await self.broadcast_call_event(
            call_sid,
            {
                "type": "interruption_status",
                "call_sid": call_sid,
                "interruption_status": interruption_status,
                "timestamp": utc_now().isoformat(),
            },
        )

    async def publish_transcript(
        self,
        *,
        call_sid: str,
        call_id: int | None,
        speaker: str,
        text: str,
        created_at: datetime | None = None,
    ) -> None:
        snapshot = self._call_state.setdefault(call_sid, {})
        metrics = snapshot.setdefault("metrics", {})
        metrics["total_transcripts"] = int(metrics.get("total_transcripts", 0)) + 1
        if speaker == "customer":
            metrics["customer_turns"] = int(metrics.get("customer_turns", 0)) + 1
        elif speaker == "assistant":
            metrics["assistant_turns"] = int(metrics.get("assistant_turns", 0)) + 1
        timestamp = (created_at or utc_now()).isoformat()
        transcript_event = {
            "type": "transcript",
            "call_sid": call_sid,
            "call_id": str(call_id) if call_id is not None else None,
            "speaker": speaker,
            "text": text,
            "timestamp": timestamp,
        }
        self._transcript_history.setdefault(call_sid, []).append(transcript_event)
        self._transcript_history[call_sid] = self._transcript_history[call_sid][-50:]
        await self.broadcast_call_event(call_sid, transcript_event)

    async def publish_speaking_event(self, call_sid: str, role: str, is_speaking: bool) -> None:
        role_state = self._speaking_state.setdefault(call_sid, {"assistant": False, "customer": False})
        event_type = "speaking"
        if role in {"customer", "user"}:
            event_type = "user_speaking"
            if is_speaking and role_state.get("assistant"):
                await self.broadcast_call_event(
                    call_sid,
                    {
                        "type": "barge_in_detected",
                        "call_sid": call_sid,
                        "role": role,
                        "timestamp": utc_now().isoformat(),
                    },
                )
        elif role == "assistant":
            event_type = "ai_speaking"

        role_state[role if role in role_state else "customer"] = is_speaking
        await self.broadcast_call_event(
            call_sid,
            {
                "type": event_type,
                "call_sid": call_sid,
                "role": role,
                "is_speaking": is_speaking,
                "timestamp": utc_now().isoformat(),
            },
        )

    async def publish_latency(self, event: dict[str, Any]) -> None:
        latency_event = {
            "type": "latency",
            "timestamp": utc_now().isoformat(),
            **event,
        }
        self._global_latency_history.append(latency_event)
        self._global_latency_history = self._global_latency_history[-500:]

        call_sid = latency_event.get("call_sid")
        if isinstance(call_sid, str) and call_sid:
            self._latency_history.setdefault(call_sid, []).append(latency_event)
            self._latency_history[call_sid] = self._latency_history[call_sid][-200:]

        await self.broadcast_global_event(latency_event)

    async def publish_webrtc_session(self, call_sid: str | None, event: dict[str, Any]) -> None:
        if call_sid:
            await self.broadcast_call_event(call_sid, event)
            return
        await self.broadcast_global_event(event)

    async def broadcast_call_event(self, call_sid: str, event: dict[str, Any]) -> None:
        recipients = await self._subscribers_for_call(call_sid)
        await self._broadcast(recipients, event)

    async def broadcast_global_event(self, event: dict[str, Any]) -> None:
        async with self._lock:
            recipients = [state.websocket for state in self._connections.values()]
        await self._broadcast(recipients, event)

    async def publish_call_summary(self, call_sid: str) -> None:
        snapshot = self._call_state.setdefault(call_sid, {})
        summary = self._build_call_summary(call_sid)
        snapshot["call_summary"] = summary
        snapshot["updated_at"] = utc_now().isoformat()
        await self.broadcast_call_event(
            call_sid,
            {
                "type": "call_summary",
                "call_sid": call_sid,
                "call_summary": summary,
                "timestamp": utc_now().isoformat(),
            },
        )

    async def _send_snapshot(self, websocket: WebSocket, call_sid: str) -> None:
        snapshot = self._call_state.get(call_sid)
        if snapshot:
            if "call_summary" not in snapshot:
                snapshot["call_summary"] = self._build_call_summary(call_sid)
            await self._send_json(
                websocket,
                {
                    "type": "snapshot",
                    "call_sid": call_sid,
                    "call_state": snapshot,
                    "transcripts": self._transcript_history.get(call_sid, []),
                    "latency_events": self._latency_history.get(call_sid, []),
                    "timestamp": utc_now().isoformat(),
                },
            )

    def _build_call_summary(self, call_sid: str) -> dict[str, Any]:
        snapshot = self._call_state.get(call_sid, {})
        metrics = snapshot.get("metrics", {})
        started_at = snapshot.get("started_at")
        ended_at = snapshot.get("ended_at")
        duration_seconds: int | None = None

        if started_at:
            try:
                started_dt = ensure_utc(datetime.fromisoformat(started_at))
                end_dt = utc_now()
                if ended_at:
                    end_dt = ensure_utc(datetime.fromisoformat(ended_at))
                duration_seconds = max(0, int((end_dt - started_dt).total_seconds()))
            except ValueError:
                duration_seconds = None

        return {
            "status": snapshot.get("status"),
            "phase": snapshot.get("phase"),
            "business_state": snapshot.get("business_state"),
            "language": snapshot.get("language"),
            "final_outcome": snapshot.get("final_outcome"),
            "duration_seconds": duration_seconds,
            "customer_turns": int(metrics.get("customer_turns", 0)),
            "assistant_turns": int(metrics.get("assistant_turns", 0)),
            "total_transcripts": int(metrics.get("total_transcripts", 0)),
            "gemini_requests": int(metrics.get("gemini_requests", 0)),
            "gemini_fallbacks": int(metrics.get("gemini_fallbacks", 0)),
            "tts_requests": int(metrics.get("tts_requests", 0)),
            "playback_starts": int(metrics.get("playback_starts", 0)),
            "interruptions": int(metrics.get("interruptions", 0)),
        }

    async def _subscribers_for_call(self, call_sid: str) -> list[WebSocket]:
        async with self._lock:
            return [
                state.websocket
                for state in self._connections.values()
                if call_sid in state.subscribed_calls
            ]

    async def _broadcast(self, recipients: list[WebSocket], event: dict[str, Any]) -> None:
        for websocket in recipients:
            try:
                await self._send_json(websocket, event)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to broadcast realtime event: %s", exc)

    async def _send_json(self, websocket: WebSocket, payload: dict[str, Any]) -> None:
        await websocket.send_json(payload)

    async def _timer_loop(self, websocket: WebSocket, call_sid: str) -> None:
        while True:
            snapshot = self._call_state.get(call_sid)
            if not snapshot:
                await asyncio.sleep(1)
                continue

            started_at = snapshot.get("started_at")
            ended_at = snapshot.get("ended_at")
            if not started_at:
                await asyncio.sleep(1)
                continue

            try:
                started_dt = ensure_utc(datetime.fromisoformat(started_at))
            except ValueError:
                await asyncio.sleep(1)
                continue

            end_dt = utc_now()
            if ended_at:
                with contextlib.suppress(ValueError):
                    end_dt = ensure_utc(datetime.fromisoformat(ended_at))

            elapsed_seconds = max(0, int((end_dt - started_dt).total_seconds()))
            await self._send_json(
                websocket,
                {
                    "type": "timer",
                    "call_sid": call_sid,
                    "elapsed_seconds": elapsed_seconds,
                    "timestamp": utc_now().isoformat(),
                },
            )
            if ended_at:
                return
            await asyncio.sleep(1)


_realtime_service = RealtimeService()


def get_realtime_service() -> RealtimeService:
    return _realtime_service


def emit_latency_event(event: dict[str, Any]) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(_realtime_service.publish_latency(event))
