from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.database import get_db
from app.db.models import Call, Transcript
from app.db.schemas import ConversationEventRead, MonitorCallSummary, WebRTCSessionRead
from app.services.realtime_service import get_realtime_service
from app.services.webrtc_service import get_webrtc_service


router = APIRouter(prefix="/webrtc", tags=["webrtc"])


class SessionCreateRequest(BaseModel):
    call_sid: str | None = None
    client_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionDescriptionRequest(BaseModel):
    type: str
    sdp: str


class IceCandidateRequest(BaseModel):
    candidate: str
    sdpMid: str | None = None
    sdpMLineIndex: int | None = None
    usernameFragment: str | None = None
    source: str = "client"


@router.get("/calls/recent", response_model=list[MonitorCallSummary])
async def list_recent_calls(session: AsyncSession = Depends(get_db)) -> list[MonitorCallSummary]:
    latest_transcript_subquery = (
        select(
            Transcript.call_id.label("call_id"),
            func.max(Transcript.id).label("latest_transcript_id"),
        )
        .group_by(Transcript.call_id)
        .subquery()
    )

    statement = (
        select(
            Call.id,
            Call.call_sid,
            Call.from_number,
            Call.to_number,
            Call.started_at,
            Call.status,
            Call.language,
            Call.final_outcome,
            Transcript.text.label("latest_transcript"),
        )
        .outerjoin(latest_transcript_subquery, latest_transcript_subquery.c.call_id == Call.id)
        .outerjoin(Transcript, Transcript.id == latest_transcript_subquery.c.latest_transcript_id)
        .order_by(Call.started_at.desc())
        .limit(20)
    )
    result = await session.execute(statement)
    rows = result.all()
    return [
        MonitorCallSummary(
            call_id=row.id,
            call_sid=row.call_sid,
            from_number=row.from_number,
            to_number=row.to_number,
            started_at=row.started_at,
            status=row.status,
            language=row.language,
            final_outcome=row.final_outcome,
            latest_transcript=row.latest_transcript,
        )
        for row in rows
    ]


@router.get("/calls/{call_sid}/conversation", response_model=list[ConversationEventRead])
async def get_call_conversation(
    call_sid: str,
    session: AsyncSession = Depends(get_db),
) -> list[ConversationEventRead]:
    statement = (
        select(Call.id, Call.call_sid, Transcript.speaker, Transcript.text, Transcript.created_at)
        .join(Transcript, Transcript.call_id == Call.id)
        .where(Call.call_sid == call_sid)
        .order_by(Transcript.created_at.asc(), Transcript.id.asc())
    )
    result = await session.execute(statement)
    rows = result.all()
    return [
        ConversationEventRead(
            call_sid=row.call_sid,
            call_id=row.id,
            speaker=row.speaker,
            text=row.text,
            timestamp=row.created_at,
        )
        for row in rows
    ]


@router.post("/sessions", response_model=WebRTCSessionRead, status_code=status.HTTP_201_CREATED)
async def create_webrtc_session(payload: SessionCreateRequest) -> WebRTCSessionRead:
    settings = get_settings()
    realtime_service = get_realtime_service()
    webrtc_service = get_webrtc_service(settings)
    session = await webrtc_service.create_session(
        call_sid=payload.call_sid,
        client_id=payload.client_id,
        metadata=payload.metadata,
    )
    session_payload = webrtc_service.serialize_session(session)
    await realtime_service.publish_webrtc_session(
        payload.call_sid,
        {
            "type": "webrtc_session",
            "session_id": session.session_id,
            "call_sid": payload.call_sid,
            "status": session.status,
            "bridge_status": session.bridge_status,
            "timestamp": session.updated_at.isoformat(),
        },
    )
    return WebRTCSessionRead(**session_payload)


@router.get("/sessions", response_model=list[WebRTCSessionRead])
async def list_webrtc_sessions() -> list[WebRTCSessionRead]:
    settings = get_settings()
    webrtc_service = get_webrtc_service(settings)
    sessions = await webrtc_service.list_sessions()
    return [WebRTCSessionRead(**webrtc_service.serialize_session(item)) for item in sessions]


@router.get("/sessions/{session_id}", response_model=WebRTCSessionRead)
async def get_webrtc_session(session_id: str) -> WebRTCSessionRead:
    settings = get_settings()
    webrtc_service = get_webrtc_service(settings)
    session = await webrtc_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="WebRTC session not found.")
    return WebRTCSessionRead(**webrtc_service.serialize_session(session))


@router.post("/sessions/{session_id}/offer", response_model=WebRTCSessionRead)
async def submit_offer(session_id: str, payload: SessionDescriptionRequest) -> WebRTCSessionRead:
    settings = get_settings()
    realtime_service = get_realtime_service()
    webrtc_service = get_webrtc_service(settings)
    session = await webrtc_service.attach_offer(session_id, payload.model_dump())
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="WebRTC session not found.")

    await realtime_service.publish_webrtc_session(
        session.call_sid,
        {
            "type": "webrtc_signal",
            "signal_type": "offer",
            "session_id": session.session_id,
            "call_sid": session.call_sid,
            "status": session.status,
            "bridge_status": session.bridge_status,
            "timestamp": session.updated_at.isoformat(),
        },
    )
    return WebRTCSessionRead(**webrtc_service.serialize_session(session))


@router.post("/sessions/{session_id}/answer", response_model=WebRTCSessionRead)
async def submit_answer(session_id: str, payload: SessionDescriptionRequest) -> WebRTCSessionRead:
    settings = get_settings()
    realtime_service = get_realtime_service()
    webrtc_service = get_webrtc_service(settings)
    session = await webrtc_service.attach_answer(session_id, payload.model_dump())
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="WebRTC session not found.")

    await realtime_service.publish_webrtc_session(
        session.call_sid,
        {
            "type": "webrtc_signal",
            "signal_type": "answer",
            "session_id": session.session_id,
            "call_sid": session.call_sid,
            "status": session.status,
            "bridge_status": session.bridge_status,
            "timestamp": session.updated_at.isoformat(),
        },
    )
    return WebRTCSessionRead(**webrtc_service.serialize_session(session))


@router.post("/sessions/{session_id}/ice", response_model=WebRTCSessionRead)
async def submit_ice_candidate(session_id: str, payload: IceCandidateRequest) -> WebRTCSessionRead:
    settings = get_settings()
    realtime_service = get_realtime_service()
    webrtc_service = get_webrtc_service(settings)
    session = await webrtc_service.add_ice_candidate(
        session_id,
        payload.model_dump(),
        source=payload.source,
    )
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="WebRTC session not found.")

    await realtime_service.publish_webrtc_session(
        session.call_sid,
        {
            "type": "webrtc_signal",
            "signal_type": "ice_candidate",
            "session_id": session.session_id,
            "call_sid": session.call_sid,
            "status": session.status,
            "source": payload.source,
            "timestamp": session.updated_at.isoformat(),
        },
    )
    return WebRTCSessionRead(**webrtc_service.serialize_session(session))


@router.post("/sessions/{session_id}/close", response_model=WebRTCSessionRead)
async def close_webrtc_session(session_id: str) -> WebRTCSessionRead:
    settings = get_settings()
    realtime_service = get_realtime_service()
    webrtc_service = get_webrtc_service(settings)
    session = await webrtc_service.close_session(session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="WebRTC session not found.")

    await realtime_service.publish_webrtc_session(
        session.call_sid,
        {
            "type": "webrtc_session",
            "session_id": session.session_id,
            "call_sid": session.call_sid,
            "status": session.status,
            "bridge_status": session.bridge_status,
            "timestamp": session.updated_at.isoformat(),
        },
    )
    return WebRTCSessionRead(**webrtc_service.serialize_session(session))
