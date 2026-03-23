import logging

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Response, WebSocket, status
from pydantic import BaseModel, Field
from requests.exceptions import ConnectionError as RequestsConnectionError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.conversation_prompts import CALL_BOOTSTRAP
from app.db.database import get_db
from app.services.audio_quality_service import get_audio_quality_service
from app.services.conversation_service import ConversationService
from app.services.gemini_service import GeminiService
from app.services.issue_resolution_service import get_issue_resolution_service
from app.services.realtime_service import emit_latency_event, get_realtime_service
from app.services.sarvam_stt_service import SarvamSTTService
from app.services.sarvam_tts_service import SarvamTTSService
from app.services.twilio_media_stream_service import get_twilio_media_stream_service
from app.services.twilio_service import TwilioService
from app.services.vad_service import get_vad_service
from app.utils.helpers import utc_now_iso


router = APIRouter(prefix="/twilio", tags=["twilio"])
logger = logging.getLogger(__name__)


class OutboundCallRequest(BaseModel):
    mobile_number: str = Field(min_length=8)
    customer_name: str = ""
    language: str = "en-IN"


class OutboundCallResponse(BaseModel):
    call_sid: str
    mobile_number: str
    customer_name: str
    status: str


def get_conversation_service(session: AsyncSession) -> ConversationService:
    settings = get_settings()
    twilio_service = TwilioService(settings)
    stt_service = SarvamSTTService(settings)
    gemini_service = GeminiService(settings)
    tts_service = SarvamTTSService(settings)
    realtime_service = get_realtime_service()
    audio_quality_service = get_audio_quality_service(settings)
    vad_service = get_vad_service(settings)
    issue_resolution_service = get_issue_resolution_service()
    return ConversationService(
        session=session,
        twilio_service=twilio_service,
        stt_service=stt_service,
        gemini_service=gemini_service,
        tts_service=tts_service,
        public_url=settings.public_url,
        audio_quality_service=audio_quality_service,
        vad_service=vad_service,
        issue_resolution_service=issue_resolution_service,
        realtime_service=realtime_service,
        max_turns=settings.max_conversation_turns,
    )


@router.post("/voice")
async def incoming_voice_call(
    CallSid: str = Form(...),
    From: str | None = Form(default=None),
    To: str | None = Form(default=None),
    CallStatus: str | None = Form(default="ringing"),
    customer_name: str = Query(default=""),
    language: str = Query(default="en-IN"),
    session: AsyncSession = Depends(get_db),
) -> Response:
    emit_latency_event(
        {
            "step": "twilio_voice_webhook_received",
            "call_sid": CallSid,
            "event_timestamp": utc_now_iso(),
            "status": CallStatus or "ringing",
            "from_number": From,
            "to_number": To,
        }
    )
    logger.info(
        "Latency step=twilio_voice_webhook_received call=%s timestamp=%s status=%s from=%s to=%s",
        CallSid,
        utc_now_iso(),
        CallStatus or "ringing",
        From,
        To,
    )
    settings = get_settings()
    twilio_service = TwilioService(settings)
    service = get_conversation_service(session)
    customer_number = twilio_service.resolve_customer_number(From, To)

    if not settings.public_url:
        twiml = twilio_service.build_fallback_say_response(
            "The voice assistant is not configured with a public URL yet. Please try again later."
        )
        return Response(content=twiml, media_type="application/xml")

    if await service.is_opted_out(customer_number):
        twiml = twilio_service.build_fallback_say_response(
            "This number is marked as opted out. We will not continue this automated call."
        )
        return Response(content=twiml, media_type="application/xml")

    try:
        call = await service.upsert_call(CallSid, From, To, status=CallStatus or "in-progress")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to initialize call %s: %s", CallSid, exc)
        twiml = twilio_service.build_fallback_say_response(
            "We are unable to start the assistant right now. Please try again later."
        )
        return Response(content=twiml, media_type="application/xml")

    await get_realtime_service().publish_call_phase(call.call_sid, CALL_BOOTSTRAP)
    twiml = twilio_service.build_stream_response(
        stream_path=f"{settings.api_prefix}/twilio/media-stream",
        customer_name=customer_name,
        language=language,
        customer_number=customer_number or "",
        call_sid=CallSid,
    )
    logger.info("Incoming call %s initialized", CallSid)
    return Response(content=twiml, media_type="application/xml")


@router.post("/recording")
async def recording_callback(
    CallSid: str = Form(...),
    From: str | None = Form(default=None),
    To: str | None = Form(default=None),
    RecordingSid: str | None = Form(default=None),
    RecordingUrl: str | None = Form(default=None),
    RecordingStatus: str | None = Form(default=None),
    session: AsyncSession = Depends(get_db),
) -> Response:
    emit_latency_event(
        {
            "step": "twilio_recording_webhook_received",
            "call_sid": CallSid,
            "event_timestamp": utc_now_iso(),
            "recording_sid": RecordingSid,
            "recording_status": RecordingStatus,
        }
    )
    logger.info(
        "Latency step=twilio_recording_webhook_received call=%s timestamp=%s recording_sid=%s recording_status=%s",
        CallSid,
        utc_now_iso(),
        RecordingSid,
        RecordingStatus,
    )
    settings = get_settings()
    twilio_service = TwilioService(settings)
    if twilio_service.has_processed_recording(RecordingSid, RecordingUrl):
        logger.info("Skipping duplicate recording callback for call=%s recording=%s", CallSid, RecordingSid or RecordingUrl)
        return Response(content=twilio_service.build_empty_response(), media_type="application/xml")

    effective_recording_url = RecordingUrl if not RecordingStatus or RecordingStatus == "completed" else None

    service = get_conversation_service(session)
    try:
        turn = await service.handle_recording(
            call_sid=CallSid,
            recording_url=effective_recording_url,
            from_number=From,
            to_number=To,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to process call turn for %s: %s", CallSid, exc)
        twiml = twilio_service.build_fallback_say_response(
            "I am sorry, I am having trouble processing that right now. Please try again later."
        )
        return Response(content=twiml, media_type="application/xml")

    if turn.should_hangup:
        twiml = twilio_service.build_goodbye_response(turn.public_audio_url)
    else:
        twiml = twilio_service.build_conversation_response(
            reply_audio_url=turn.public_audio_url,
            action_path=f"{settings.api_prefix}/twilio/recording",
        )
    return Response(content=twiml, media_type="application/xml")


@router.post("/status", status_code=status.HTTP_204_NO_CONTENT)
async def call_status_callback(
    CallSid: str = Form(...),
    CallStatus: str = Form(...),
    session: AsyncSession = Depends(get_db),
) -> Response:
    service = get_conversation_service(session)
    await service.mark_call_status(CallSid, CallStatus)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

# connect with twilio
@router.post("/outbound-call", response_model=OutboundCallResponse, status_code=status.HTTP_201_CREATED)
async def create_outbound_call(payload: OutboundCallRequest) -> OutboundCallResponse:
    #send payload to the twilio
    emit_latency_event(
        {
            "step": "outbound_call_requested",
            "call_sid": "",
            "event_timestamp": utc_now_iso(),
            "to_number": payload.mobile_number,
            "language": payload.language,
        }
    )
    #added loggers
    logger.info(
        "Latency step=outbound_call_requested to=%s timestamp=%s language=%s",
        payload.mobile_number,
        utc_now_iso(),
        payload.language,
    )
    settings = get_settings()
    twilio_service = TwilioService(settings)

    try:
        call_sid = twilio_service.place_outbound_call(
            to_number=payload.mobile_number,
            customer_name=payload.customer_name,
            language=payload.language,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RequestsConnectionError as exc:
        logger.exception("Failed to resolve or reach Twilio API for outbound call to %s: %s", payload.mobile_number, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to reach Twilio from the container right now. Please check Docker DNS/network and try again.",
        ) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to place outbound call to %s: %s", payload.mobile_number, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to place outbound call right now.",
        ) from exc

    return OutboundCallResponse(
        call_sid=call_sid,
        mobile_number=payload.mobile_number,
        customer_name=payload.customer_name,
        status="queued",
    )


@router.websocket("/media-stream")
async def twilio_media_stream(websocket: WebSocket) -> None:
    media_stream_service = get_twilio_media_stream_service()
    await media_stream_service.handle_websocket(websocket)
