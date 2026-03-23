from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TranscriptRead(BaseModel):
    id: int
    speaker: str
    text: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CallRead(BaseModel):
    id: int
    call_sid: str
    from_number: str | None
    to_number: str | None
    started_at: datetime
    ended_at: datetime | None
    status: str
    language: str | None
    final_outcome: str | None
    transcripts: list[TranscriptRead] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class HealthResponse(BaseModel):
    status: str
    app: str


class RealtimeEvent(BaseModel):
    type: str
    timestamp: datetime
    call_sid: str | None = None
    call_id: str | None = None
    payload: dict = Field(default_factory=dict)


class MonitorCallSummary(BaseModel):
    call_sid: str
    call_id: int
    from_number: str | None
    to_number: str | None
    started_at: datetime
    status: str
    language: str | None
    final_outcome: str | None
    latest_transcript: str | None = None


class ConversationEventRead(BaseModel):
    call_sid: str
    call_id: int
    speaker: str
    text: str
    timestamp: datetime


class WebRTCSessionRead(BaseModel):
    session_id: str
    call_sid: str | None
    client_id: str | None
    status: str
    created_at: datetime
    updated_at: datetime
    offer: dict | None = None
    answer: dict | None = None
    ice_candidates: list[dict] = Field(default_factory=list)
    remote_ice_candidates: list[dict] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
    bridge_status: str = "pending-media-bridge"
    ice_servers: list[str] = Field(default_factory=list)
