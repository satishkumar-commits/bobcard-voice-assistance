import base64
import logging
from time import perf_counter
from xml.etree.ElementTree import Element, SubElement, tostring
from urllib.parse import urlencode

import httpx
from twilio.rest import Client
from twilio.twiml.voice_response import Play, Record, VoiceResponse

from app.core.config import Settings
from app.services.realtime_service import emit_latency_event
from app.utils.helpers import build_public_url, build_websocket_url, utc_now_iso


logger = logging.getLogger(__name__)
_processed_recordings: set[str] = set()


class TwilioService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def place_outbound_call(
        self,
        *,
        to_number: str,
        customer_name: str = "",
        language: str = "en-IN",
        public_url: str | None = None,
    ) -> str:
        resolved_public_url = (public_url or self.settings.public_url).strip().rstrip("/")
        if not resolved_public_url:
            raise ValueError("PUBLIC_URL is required to place outbound Twilio calls.")
        if not self.settings.twilio_account_sid or not self.settings.twilio_auth_token:
            raise ValueError("Twilio credentials are not configured.")
        if not self.settings.twilio_phone_number:
            raise ValueError("TWILIO_PHONE_NUMBER is not configured.")

        client = Client(self.settings.twilio_account_sid, self.settings.twilio_auth_token)
        query = urlencode(
            {
                "customer_name": customer_name,
                "language": language,
            }
        )
        
        voice_url = f"{build_public_url(resolved_public_url, f'{self.settings.api_prefix}/twilio/voice')}?{query}"
        status_callback_url = build_public_url(resolved_public_url, f"{self.settings.api_prefix}/twilio/status")

        request_sent_at = utc_now_iso()
        started_at = perf_counter()
        call = client.calls.create(
            to=to_number,
            from_=self.settings.twilio_phone_number,
            url=voice_url,
            method="POST",
            status_callback=status_callback_url,
            status_callback_method="POST",
        )
        logger.info(
            "Latency step=twilio_outbound_connect sid=%s to=%s request_sent_at=%s response_received_at=%s latency_ms=%s",
            call.sid,
            to_number,
            request_sent_at,
            utc_now_iso(),
            int((perf_counter() - started_at) * 1000),
        )
        emit_latency_event(
            {
                "step": "twilio_outbound_connect",
                "call_sid": call.sid,
                "to_number": to_number,
                "request_sent_at": request_sent_at,
                "response_received_at": utc_now_iso(),
                "latency_ms": int((perf_counter() - started_at) * 1000),
            }
        )
        return call.sid

    def build_intro_response(self, greeting_audio_url: str, action_path: str, public_url: str | None = None) -> str:
        resolved_public_url = (public_url or self.settings.public_url).strip().rstrip("/")
        response = VoiceResponse()
        response.append(Play(greeting_audio_url))
        response.append(
            Record(
                action=build_public_url(resolved_public_url, action_path),
                method="POST",
                timeout=self.settings.recording_timeout_seconds,
                max_length=self.settings.recording_max_length_seconds,
                play_beep=True,
                trim="trim-silence",
                action_on_empty_result=True,
            )
        )
        return str(response)

    def build_stream_response(
        self,
        *,
        stream_path: str,
        customer_name: str = "",
        language: str = "en-IN",
        customer_number: str = "",
        call_sid: str = "",
        public_url: str | None = None,
    ) -> str:
        resolved_public_url = (public_url or self.settings.public_url).strip().rstrip("/")
        response = Element("Response")
        connect = SubElement(response, "Connect")
        stream = SubElement(
            connect,
            "Stream",
            url=build_websocket_url(resolved_public_url, stream_path),
        )
        for name, value in {
            "customer_name": customer_name,
            "language": language,
            "customer_number": customer_number,
            "call_sid": call_sid,
        }.items():
            if value:
                SubElement(stream, "Parameter", name=name, value=value)
        return '<?xml version="1.0" encoding="UTF-8"?>' + tostring(response, encoding="unicode")

    def build_conversation_response(self, reply_audio_url: str, action_path: str, public_url: str | None = None) -> str:
        resolved_public_url = (public_url or self.settings.public_url).strip().rstrip("/")
        response = VoiceResponse()
        response.append(Play(reply_audio_url))
        response.append(
            Record(
                action=build_public_url(resolved_public_url, action_path),
                method="POST",
                timeout=self.settings.recording_timeout_seconds,
                max_length=self.settings.recording_max_length_seconds,
                play_beep=True,
                trim="trim-silence",
                action_on_empty_result=True,
            )
        )
        return str(response)

    def build_goodbye_response(self, reply_audio_url: str) -> str:
        response = VoiceResponse()
        response.append(Play(reply_audio_url))
        response.hangup()
        return str(response)

    def build_fallback_say_response(self, message: str) -> str:
        response = VoiceResponse()
        response.say(message, voice="Polly.Aditi")
        response.hangup()
        return str(response)

    def end_call(self, call_sid: str) -> None:
        if not self.settings.twilio_account_sid or not self.settings.twilio_auth_token:
            raise ValueError("Twilio credentials are not configured.")

        client = Client(self.settings.twilio_account_sid, self.settings.twilio_auth_token)
        client.calls(call_sid).update(status="completed")
        logger.info("Twilio call %s completed by API request", call_sid)

    @staticmethod
    def build_empty_response() -> str:
        return str(VoiceResponse())

    @staticmethod
    def has_processed_recording(recording_sid: str | None, recording_url: str | None) -> bool:
        token = (recording_sid or recording_url or "").strip()
        if not token:
            return False
        if token in _processed_recordings:
            return True
        _processed_recordings.add(token)
        return False

    async def download_recording(self, recording_url: str, call_sid: str = "") -> tuple[bytes, str]:
        media_url = recording_url if recording_url.endswith(".wav") else f"{recording_url}.wav"
        auth = None
        if self.settings.twilio_account_sid and self.settings.twilio_auth_token:
            auth = (self.settings.twilio_account_sid, self.settings.twilio_auth_token)

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, auth=auth) as client:
            request_sent_at = utc_now_iso()
            started_at = perf_counter()
            response = await client.get(media_url)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "audio/wav")
            logger.info(
                "Latency step=twilio_recording_download call=%s request_sent_at=%s response_received_at=%s latency_ms=%s url=%s",
                call_sid or "unknown",
                request_sent_at,
                utc_now_iso(),
                int((perf_counter() - started_at) * 1000),
                media_url,
            )
            emit_latency_event(
                {
                    "step": "twilio_recording_download",
                    "call_sid": call_sid,
                    "request_sent_at": request_sent_at,
                    "response_received_at": utc_now_iso(),
                    "latency_ms": int((perf_counter() - started_at) * 1000),
                    "url": media_url,
                }
            )
            return response.content, content_type

    @staticmethod
    def decode_recording_payload(recording_base64: str) -> bytes:
        return base64.b64decode(recording_base64)

    def resolve_customer_number(self, from_number: str | None, to_number: str | None) -> str | None:
        twilio_number = (self.settings.twilio_phone_number or "").strip()
        if from_number and from_number != twilio_number:
            return from_number
        if to_number and to_number != twilio_number:
            return to_number
        return from_number or to_number
