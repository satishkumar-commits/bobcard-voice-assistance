import asyncio
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.core.config import Settings


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class WebRTCSession:
    session_id: str
    call_sid: str | None
    client_id: str | None
    status: str
    created_at: datetime
    updated_at: datetime
    offer: dict[str, Any] | None = None
    answer: dict[str, Any] | None = None
    ice_candidates: list[dict[str, Any]] = field(default_factory=list)
    remote_ice_candidates: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    bridge_status: str = "pending-media-bridge"


class WebRTCService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._sessions: dict[str, WebRTCSession] = {}
        self._lock = asyncio.Lock()

    async def create_session(
        self,
        *,
        call_sid: str | None,
        client_id: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> WebRTCSession:
        now = utc_now()
        session = WebRTCSession(
            session_id=uuid4().hex,
            call_sid=call_sid,
            client_id=client_id,
            status="created",
            created_at=now,
            updated_at=now,
            metadata=metadata or {},
        )
        async with self._lock:
            self._sessions[session.session_id] = session
        return session

    async def list_sessions(self) -> list[WebRTCSession]:
        async with self._lock:
            return sorted(self._sessions.values(), key=lambda item: item.updated_at, reverse=True)

    async def get_session(self, session_id: str) -> WebRTCSession | None:
        async with self._lock:
            return self._sessions.get(session_id)

    async def attach_offer(self, session_id: str, offer: dict[str, Any]) -> WebRTCSession | None:
        async with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None
            session.offer = offer
            session.status = "offer-received"
            session.updated_at = utc_now()
            session.metadata.setdefault(
                "todo",
                "Attach aiortc or another media bridge here when browser audio should stream to backend services.",
            )
            return session

    async def attach_answer(self, session_id: str, answer: dict[str, Any]) -> WebRTCSession | None:
        async with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None
            session.answer = answer
            session.status = "answer-received"
            session.updated_at = utc_now()
            return session

    async def add_ice_candidate(
        self,
        session_id: str,
        candidate: dict[str, Any],
        source: str = "client",
    ) -> WebRTCSession | None:
        async with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None
            if source == "server":
                session.remote_ice_candidates.append(candidate)
            else:
                session.ice_candidates.append(candidate)
            session.updated_at = utc_now()
            return session

    async def close_session(self, session_id: str) -> WebRTCSession | None:
        async with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None
            session.status = "closed"
            session.updated_at = utc_now()
            return session

    def serialize_session(self, session: WebRTCSession) -> dict[str, Any]:
        payload = asdict(session)
        payload["created_at"] = session.created_at.isoformat()
        payload["updated_at"] = session.updated_at.isoformat()
        payload["ice_servers"] = self.settings.webrtc_ice_server_list
        return payload


_webrtc_service: WebRTCService | None = None


def get_webrtc_service(settings: Settings) -> WebRTCService:
    global _webrtc_service
    if _webrtc_service is None:
        _webrtc_service = WebRTCService(settings)
    return _webrtc_service
