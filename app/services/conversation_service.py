import asyncio
import contextlib
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.issue_guidance import (
    build_process_resume_context_reply,
    build_issue_help_reply,
    build_issue_follow_up_question,
    build_issue_resolution_reply,
    build_repair_prompt,
    collapse_repeated_acknowledgement,
    detect_issue_type,
    detect_issue_symptom,
    is_opening_response,
    is_simple_acknowledgement,
    looks_like_general_banking_question,
    looks_like_repair_request,
    looks_like_repeated_acknowledgement,
    normalize_issue_text,
)
from app.core.conversation_prompts import (
    BusinessState,
    CALL_SUMMARY_READY,
    CONFIRMATION_CLOSING,
    CONSENT_CHECK,
    CONTEXT_SETTING,
    GEMINI_FALLBACK_USED,
    GEMINI_REPLY_READY,
    GEMINI_REQUESTED,
    IDENTITY_VERIFICATION,
    MAIN_POINTS_READY,
    ISSUE_CAPTURE,
    LANGUAGE_SELECTION,
    OPENING,
    PLANNING_RESPONSE,
    RESOLUTION_ACTION,
    RESPONSE_PLAN_READY,
    SESSION_CLEANUP,
    TRANSCRIBING,
    build_callback_ack,
    build_application_not_started_reply,
    build_consent_reprompt,
    build_empty_input_reply,
    build_first_unclear_reply,
    build_goodbye_reply,
    build_human_handoff_reply,
    build_identity_mismatch_reply,
    build_identity_reprompt,
    build_identity_verification_prompt,
    build_issue_capture_prompt,
    build_general_capabilities_reply,
    build_context_setting_prompt,
    build_post_greeting_issue_prompt,
    build_language_preference_reprompt,
    build_language_prompt,
    build_language_selected_reply,
    build_noisy_fallback_reply,
    build_noisy_mode_acknowledgement,
    build_opening_greeting,
    build_opt_out_reply,
    build_opted_out_notice,
    build_resolution_completed_reply,
    build_resolution_follow_up_prompt,
    build_second_unclear_reply,
    build_short_choice_prompt,
    build_sms_link_ack,
    detect_language_preference,
    detect_auth_confirmation,
    detect_auth_denial,
    detect_escalation_request,
    detect_resolution_choice,
    detect_consent_choice,
    is_short_valid_intent,
    normalize_language,
    wants_goodbye,
)
from app.db.models import Call, OptOut, Transcript
from app.services.audio_quality_service import AudioQualityService
from app.services.gemini_service import GeminiReplyDecision, GeminiService
from app.services.issue_resolution_service import IssueResolutionService
from app.services.realtime_service import RealtimeService, emit_latency_event
from app.services.sarvam_stt_service import SarvamSTTService
from app.services.sarvam_tts_service import SarvamTTSService
from app.services.twilio_service import TwilioService
from app.services.vad_service import VADService
from app.utils.helpers import (
    apply_response_style,
    build_public_url,
    enforce_devanagari_hindi_reply,
    infer_language_code,
    sanitize_spoken_text,
    utc_now_iso,
)


logger = logging.getLogger(__name__)

TERMINAL_CALL_STATUSES = {"completed", "busy", "failed", "no-answer", "canceled"}


@dataclass
class ConversationTurn:
    text: str
    public_audio_url: str
    language_code: str
    should_hangup: bool = False


@dataclass
class ConversationReply:
    text: str
    language_code: str
    should_hangup: bool = False


class ConversationService:
    def __init__(
        self,
        session: AsyncSession,
        twilio_service: TwilioService,
        stt_service: SarvamSTTService,
        gemini_service: GeminiService,
        tts_service: SarvamTTSService,
        public_url: str,
        audio_quality_service: AudioQualityService,
        vad_service: VADService,
        issue_resolution_service: IssueResolutionService,
        realtime_service: RealtimeService | None = None,
        max_turns: int = 6,
    ) -> None:
        self.session = session
        self.twilio_service = twilio_service
        self.stt_service = stt_service
        self.gemini_service = gemini_service
        self.tts_service = tts_service
        self.public_url = public_url
        self.audio_quality_service = audio_quality_service
        self.vad_service = vad_service
        self.issue_resolution_service = issue_resolution_service
        self.realtime_service = realtime_service
        self.max_turns = max_turns
        self.max_post_resolution_prompts = 1
        self.max_repeat_suppression = 2

    async def upsert_call(
        self,
        call_sid: str,
        from_number: str | None,
        to_number: str | None,
        status: str = "in-progress",
    ) -> Call:
        result = await self.session.execute(select(Call).where(Call.call_sid == call_sid))
        call = result.scalar_one_or_none()
        if call is None:
            call = Call(
                call_sid=call_sid,
                from_number=from_number,
                to_number=to_number,
                status=status,
            )
            self.session.add(call)
            await self.session.flush()
        else:
            call.from_number = from_number or call.from_number
            call.to_number = to_number or call.to_number
            if call.status not in TERMINAL_CALL_STATUSES or status in TERMINAL_CALL_STATUSES:
                call.status = status

        await self.session.commit()
        await self.session.refresh(call)
        await self._publish_call_status(call)
        return call

    async def mark_call_status(self, call_sid: str, status: str, final_outcome: str | None = None) -> None:
        result = await self.session.execute(select(Call).where(Call.call_sid == call_sid))
        call = result.scalar_one_or_none()
        if call is None:
            return

        call.status = status
        if status in TERMINAL_CALL_STATUSES:
            call.ended_at = datetime.now(UTC)
        if final_outcome:
            call.final_outcome = final_outcome
        await self.session.commit()
        await self._publish_call_status(call)
        if status in TERMINAL_CALL_STATUSES:
            await self._publish_call_phase(call.call_sid, CALL_SUMMARY_READY)
            await self._publish_call_summary(call.call_sid)
            await self._publish_call_phase(call.call_sid, SESSION_CLEANUP)

    async def is_opted_out(self, phone_number: str | None) -> bool:
        if not phone_number:
            return False
        result = await self.session.execute(select(OptOut).where(OptOut.phone_number == phone_number))
        return result.scalar_one_or_none() is not None

    async def create_greeting_turn(self, call: Call) -> ConversationTurn:
        reply = await self.create_greeting_reply(call)
        return await self._synthesize_reply(call, reply)

    async def create_greeting_reply(self, call: Call) -> ConversationReply:
        language_code = self._prompt_language(call)
        if call.language != language_code:
            call.language = language_code
            await self.session.commit()
            await self._publish_call_status(call)
        await self._set_business_state(call.call_sid, OPENING)
        greeting_text = build_opening_greeting(language=language_code)
        reply = await self._build_text_turn(call, greeting_text)
        await self._set_business_state(call.call_sid, CONSENT_CHECK)
        return reply

    async def create_personalized_greeting_turn(
        self,
        call: Call,
        customer_name: str = "",
        language: str | None = None,
    ) -> ConversationTurn:
        reply = await self.create_personalized_greeting_reply(
            call,
            customer_name=customer_name,
            language=language,
        )
        return await self._synthesize_reply(call, reply)

    async def create_personalized_greeting_reply(
        self,
        call: Call,
        customer_name: str = "",
        language: str | None = None,
    ) -> ConversationReply:
        language_code = "hi-IN"
        if call.language != language_code:
            call.language = language_code
            await self.session.commit()
            await self._publish_call_status(call)
        await self._set_business_state(call.call_sid, OPENING)
        greeting_text = build_opening_greeting(name=customer_name, language=language_code)
        reply = await self._build_text_turn(call, greeting_text)
        await self._set_business_state(call.call_sid, CONSENT_CHECK)
        return reply

    async def _synthesize_turn_audio(
        self,
        call: Call,
        text: str,
        language_code: str,
    ):
        audio_path = await self.tts_service.synthesize(
            text=text,
            language_code=language_code,
            call_sid=call.call_sid,
        )
        return audio_path

    async def handle_recording(
        self,
        call_sid: str,
        recording_url: str | None,
        from_number: str | None,
        to_number: str | None,
    ) -> ConversationTurn:
        turn_started_at = perf_counter()
        turn_received_at = utc_now_iso()
        call = await self.upsert_call(call_sid, from_number, to_number, status="in-progress")
        prompt_language = self._prompt_language(call)
        logger.info(
            "Latency step=customer_audio_received call=%s mode=recording timestamp=%s recording_url_present=%s",
            call_sid,
            turn_received_at,
            bool(recording_url),
        )
        emit_latency_event(
            {
                "step": "customer_audio_received",
                "call_sid": call_sid,
                "mode": "recording",
                "event_timestamp": turn_received_at,
                "recording_url_present": bool(recording_url),
            }
        )

        if await self.is_opted_out(from_number):
            text = build_opted_out_notice(prompt_language)
            reply = await self._build_text_turn(call, text, should_hangup=True, outcome="opted-out")
            return await self._synthesize_reply(call, reply)

        if not recording_url:
            reply = await self._handle_unclear_audio(
                call,
                transcript="",
                confidence=0.0,
                confidence_source="none",
                speech_detected=False,
            )
            return await self._synthesize_reply(call, reply)

        await self._publish_speaking(call.call_sid, "customer", True)
        audio_bytes, content_type = await self.twilio_service.download_recording(recording_url, call_sid=call.call_sid)
        await self._publish_call_phase(call.call_sid, TRANSCRIBING)
        stt_result = await self.stt_service.transcribe(
            audio_bytes=audio_bytes,
            content_type=content_type,
            language_code=call.language or "unknown",
            call_sid=call.call_sid,
        )
        await self._publish_speaking(call.call_sid, "customer", False)
        reply = await self._handle_transcript_for_call(
            call=call,
            transcript=stt_result.transcript,
            customer_name=None,
            from_number=from_number,
            audio_bytes=audio_bytes,
            detected_language=stt_result.language_code,
            confidence=stt_result.confidence,
            confidence_source=stt_result.confidence_source,
            speech_detected=stt_result.speech_detected,
            on_assistant_sentence=None,
            llm_streaming_enabled=None,
        )
        turn = await self._synthesize_reply(call, reply)
        logger.info(
            "Latency step=turn_roundtrip call=%s mode=recording started_at=%s completed_at=%s total_ms=%s",
            call.call_sid,
            turn_received_at,
            utc_now_iso(),
            int((perf_counter() - turn_started_at) * 1000),
        )
        emit_latency_event(
            {
                "step": "turn_roundtrip",
                "call_sid": call.call_sid,
                "mode": "recording",
                "started_at": turn_received_at,
                "completed_at": utc_now_iso(),
                "latency_ms": int((perf_counter() - turn_started_at) * 1000),
            }
        )
        return turn

    async def handle_live_transcript(
        self,
        *,
        call_sid: str,
        transcript: str,
        customer_name: str | None = None,
        from_number: str | None,
        to_number: str | None,
        audio_bytes: bytes | None = None,
        detected_language: str | None = None,
        confidence: float | None = None,
        confidence_source: str = "unknown",
        speech_detected: bool | None = None,
        on_assistant_sentence: Callable[[str, str], Awaitable[None]] | None = None,
        llm_streaming_enabled: bool | None = None,
    ) -> ConversationReply:
        logger.info(
            "Latency step=customer_transcript_received call=%s mode=stream timestamp=%s transcript_preview=%s",
            call_sid,
            utc_now_iso(),
            sanitize_spoken_text(transcript)[:80],
        )
        emit_latency_event(
            {
                "step": "customer_transcript_received",
                "call_sid": call_sid,
                "mode": "stream",
                "event_timestamp": utc_now_iso(),
                "transcript_preview": sanitize_spoken_text(transcript)[:80],
            }
        )
        call = await self.upsert_call(call_sid, from_number, to_number, status="in-progress")
        return await self._handle_transcript_for_call(
            call=call,
            transcript=transcript,
            customer_name=customer_name,
            from_number=from_number,
            audio_bytes=audio_bytes,
            detected_language=detected_language,
            confidence=confidence,
            confidence_source=confidence_source,
            speech_detected=speech_detected,
            on_assistant_sentence=on_assistant_sentence,
            llm_streaming_enabled=llm_streaming_enabled,
        )

    async def _handle_transcript_for_call(
        self,
        *,
        call: Call,
        transcript: str,
        customer_name: str | None,
        from_number: str | None,
        audio_bytes: bytes | None,
        detected_language: str | None,
        confidence: float | None,
        confidence_source: str,
        speech_detected: bool | None,
        on_assistant_sentence: Callable[[str, str], Awaitable[None]] | None,
        llm_streaming_enabled: bool | None,
    ) -> ConversationReply:
        current_language = self._prompt_language(call)
        resolved_customer_name = (customer_name or "").strip()
        transcript = sanitize_spoken_text(
            collapse_repeated_acknowledgement(transcript, current_language)
        )
        issue_state = self.issue_resolution_service.get_state(call.call_sid)
        turn_language = infer_language_code(
            transcript,
            stt_language=detected_language,
            preferred_language=call.language,
        )
        prompt_language = self._prompt_language(call)
        history = await self.get_recent_history(call.id)
        customer_turns = [item for item in history if item["speaker"] == "customer"]
        last_customer_text = customer_turns[-1]["text"] if customer_turns else ""
        consent_choice = detect_consent_choice(transcript)
        selected_language = detect_language_preference(transcript)
        response_style = "default"
        self.issue_resolution_service.set_response_style(call.call_sid, response_style)
        low_signal_transcript = self._is_low_signal_transcript(transcript)

        if (
            not selected_language
            and not low_signal_transcript
            and self._should_auto_detect_language(
                transcript=transcript,
                customer_turn_count=len(customer_turns),
                current_language=call.language,
                detected_turn_language=turn_language,
                consent_choice=consent_choice,
            )
        ):
            call.language = turn_language
            await self.session.commit()
            await self._publish_call_status(call)
            prompt_language = self._prompt_language(call)

        _, vad_decision = self.vad_service.evaluate_turn(
            call_sid=call.call_sid,
            audio_bytes=audio_bytes,
            transcript=transcript,
            provider_speech_detected=speech_detected,
        )

        quality_state, quality_assessment = self.audio_quality_service.assess_turn(
            call_sid=call.call_sid,
            transcript=transcript,
            confidence=confidence,
            confidence_source=confidence_source,
            speech_detected=vad_decision.speech_detected,
        )
        if low_signal_transcript:
            quality_state.last_reason = "empty-transcript-guard"
            quality_assessment.transcript_reliable = False
            quality_assessment.reason = "empty-transcript-guard"
            emit_latency_event(
                {
                    "step": "empty_transcript_guard_applied",
                    "call_sid": call.call_sid,
                    "event_timestamp": utc_now_iso(),
                    "transcript_preview": sanitize_spoken_text(transcript)[:80],
                    "min_chars": max(1, int(self.audio_quality_service.settings.empty_transcript_min_chars)),
                }
            )
        await self._publish_audio_quality(call.call_sid, quality_state.as_payload())

        if quality_assessment.transcript_reliable:
            early_state_reply = await self._handle_business_state_transition(
                call=call,
                transcript=transcript,
                customer_name=resolved_customer_name,
                from_number=from_number,
                prompt_language=prompt_language,
                turn_language=turn_language,
                selected_language=selected_language,
                consent_choice=consent_choice,
                issue_state=issue_state,
                last_customer_text=last_customer_text,
            )
            if early_state_reply is not None:
                return early_state_reply

        main_points = self._build_turn_main_points(
            call=call,
            transcript=transcript,
            detected_language=detected_language,
            prompt_language=prompt_language,
            selected_language=selected_language,
            consent_choice=consent_choice,
            issue_state=issue_state,
            customer_turn_count=len(customer_turns),
            confidence=quality_assessment.confidence,
            confidence_source=quality_assessment.confidence_source,
            speech_detected=quality_assessment.speech_detected,
            transcript_reliable=quality_assessment.transcript_reliable,
            response_style=response_style,
        )
        await self._publish_main_points(call.call_sid, main_points)
        await self._publish_call_phase(call.call_sid, MAIN_POINTS_READY)
        await self._publish_call_phase(call.call_sid, PLANNING_RESPONSE)
        response_plan = self._build_response_plan(
            call=call,
            transcript=transcript,
            from_number=from_number,
            prompt_language=prompt_language,
            selected_language=selected_language,
            consent_choice=consent_choice,
            issue_state=issue_state,
            history=history,
            customer_turn_count=len(customer_turns),
            quality_state=quality_state,
            quality_assessment=quality_assessment,
            main_points=main_points,
        )
        logger.info(
            "Decision call=%s primary_intent=%s route=%s issue_type=%s symptom=%s response_source=%s",
            call.call_sid,
            main_points.get("primary_intent"),
            response_plan.get("route"),
            response_plan.get("issue_type"),
            response_plan.get("symptom"),
            response_plan.get("response_source"),
        )
        await self._publish_response_plan(call.call_sid, response_plan)
        await self._publish_call_phase(call.call_sid, RESPONSE_PLAN_READY)

        if not quality_assessment.transcript_reliable:
            return await self._handle_unclear_audio(
                call,
                transcript=transcript,
                confidence=quality_assessment.confidence,
                confidence_source=quality_assessment.confidence_source,
                speech_detected=quality_assessment.speech_detected,
            )

        if self._looks_like_call_purpose_question(transcript):
            await self.add_transcript(call, "customer", transcript)
            self.audio_quality_service.register_success(call.call_sid, transcript)
            await self._publish_audio_quality(call.call_sid, self.audio_quality_service.get_state(call.call_sid).as_payload())
            self.issue_resolution_service.clear_issue(call.call_sid)
            await self._set_business_state(call.call_sid, ISSUE_CAPTURE)
            optional_customer_name = await self._pick_customer_name(call, resolved_customer_name)
            reply_text = (
                f"{build_process_resume_context_reply(language=prompt_language)} "
                f"{build_issue_capture_prompt(prompt_language, name=optional_customer_name)}"
            )
            return await self._build_text_turn(call, reply_text, outcome="context-recap")

        response_language = prompt_language
        if call.language != response_language:
            call.language = response_language
            await self.session.commit()
            await self._publish_call_status(call)
        prompt_language = self._prompt_language(call)

        self.audio_quality_service.register_success(call.call_sid, transcript)
        await self._publish_audio_quality(call.call_sid, quality_state.as_payload())
        await self.add_transcript(call, "customer", transcript)
        optional_customer_name = await self._pick_customer_name(call, resolved_customer_name)

        if response_plan["route"] == "opt_out_close" and from_number:
            await self._record_opt_out(from_number, "caller-requested-opt-out")
            await self._set_business_state(call.call_sid, CONFIRMATION_CLOSING)
            reply_text = build_opt_out_reply(prompt_language)
            return await self._build_text_turn(call, reply_text, should_hangup=True, outcome="opted-out")

        if response_plan["route"] == "application_not_started_close":
            await self._set_business_state(call.call_sid, CONFIRMATION_CLOSING)
            reply_text = build_application_not_started_reply(prompt_language)
            return await self._build_text_turn(call, reply_text, should_hangup=True, outcome="application-not-started")

        if issue_state.post_resolution_check_pending:
            resolution_choice = detect_resolution_choice(transcript)
            if resolution_choice == "no_more_help" or self._looks_like_call_termination_intent(transcript):
                self.issue_resolution_service.clear_post_resolution_check(call.call_sid)
                await self._set_business_state(call.call_sid, CONFIRMATION_CLOSING)
                reply_text = build_resolution_completed_reply(prompt_language)
                return await self._build_text_turn(call, reply_text, should_hangup=True, outcome="resolution-complete")
            if response_plan["route"] == "general_capabilities":
                self.issue_resolution_service.clear_post_resolution_check(call.call_sid)
            elif resolution_choice == "more_help":
                self.issue_resolution_service.clear_post_resolution_check(call.call_sid)
                if len(normalize_issue_text(transcript).split()) <= 5:
                    await self._set_business_state(call.call_sid, ISSUE_CAPTURE)
                    return await self._build_text_turn(
                        call,
                        build_issue_capture_prompt(prompt_language, name=optional_customer_name),
                        outcome="awaiting-new-issue",
                    )
            elif response_plan["route"] == "resolution_complete_close":
                self.issue_resolution_service.clear_post_resolution_check(call.call_sid)
                await self._set_business_state(call.call_sid, CONFIRMATION_CLOSING)
                reply_text = build_resolution_completed_reply(prompt_language)
                return await self._build_text_turn(call, reply_text, should_hangup=True, outcome="resolution-complete")

        if response_plan["route"] == "resolution_follow_up":
            if not issue_state.post_resolution_check_pending:
                self.issue_resolution_service.mark_issue_resolved(call.call_sid)
            else:
                issue_state = self.issue_resolution_service.register_post_resolution_prompt(call.call_sid)
                if issue_state.post_resolution_prompt_count > self.max_post_resolution_prompts:
                    self.issue_resolution_service.clear_post_resolution_check(call.call_sid)
                    await self._set_business_state(call.call_sid, CONFIRMATION_CLOSING)
                    reply_text = build_resolution_completed_reply(prompt_language)
                    return await self._build_text_turn(call, reply_text, should_hangup=True, outcome="resolution-complete")
            if response_plan.get("close_after_resolution"):
                self.issue_resolution_service.clear_post_resolution_check(call.call_sid)
                await self._set_business_state(call.call_sid, CONFIRMATION_CLOSING)
                reply_text = build_resolution_completed_reply(prompt_language)
                return await self._build_text_turn(call, reply_text, should_hangup=True, outcome="resolution-complete")
            await self._set_business_state(call.call_sid, CONFIRMATION_CLOSING)
            reply_text = build_resolution_follow_up_prompt(prompt_language)
            return await self._build_text_turn(call, reply_text, outcome="issue-resolved")

        if response_plan["route"] == "handoff_close":
            await self._set_business_state(call.call_sid, CONFIRMATION_CLOSING)
            reply_text = build_human_handoff_reply(prompt_language)
            return await self._build_text_turn(call, reply_text, should_hangup=True, outcome="escalation-requested")

        if response_plan["route"] == "goodbye_close":
            await self._set_business_state(call.call_sid, CONFIRMATION_CLOSING)
            reply_text = build_goodbye_reply(prompt_language)
            return await self._build_text_turn(call, reply_text, should_hangup=True, outcome="customer-ended")

        history = await self.get_recent_history(call.id)
        customer_turns = [item for item in history if item["speaker"] == "customer"]
        if response_plan["route"] == "post_greeting_issue_capture":
            await self._set_business_state(call.call_sid, ISSUE_CAPTURE)
            return await self._build_text_turn(
                call,
                build_post_greeting_issue_prompt(prompt_language, name=optional_customer_name),
            )

        if response_plan["route"] == "repair_guidance":
            await self._set_business_state(call.call_sid, ISSUE_CAPTURE)
            if issue_state.issue_type:
                reply_text = (
                    f"{build_repair_prompt(prompt_language)} "
                    f"{build_issue_follow_up_question(issue_state.issue_type, prompt_language, follow_up_count=issue_state.follow_up_count)}"
                )
            else:
                reply_text = (
                    f"{build_repair_prompt(prompt_language)} "
                    f"{build_issue_capture_prompt(prompt_language, name=optional_customer_name)}"
                )
            return await self._build_text_turn(call, reply_text, outcome="repair-guidance")

        if response_plan["route"] == "short_ack_reprompt":
            await self._set_business_state(call.call_sid, ISSUE_CAPTURE)
            if issue_state.issue_type:
                reply_text = (
                    "जी, मैं सुन रही हूँ। "
                    f"{build_issue_follow_up_question(issue_state.issue_type, prompt_language, follow_up_count=issue_state.follow_up_count)}"
                )
            else:
                if prompt_language == "hi-IN":
                    name_prefix = f"{optional_customer_name} जी, " if optional_customer_name else ""
                    reply_text = f"{name_prefix}समझ गई। दिक्कत OTP, दस्तावेज़ अपलोड, लॉगिन, या किसी और चरण में है?"
                else:
                    reply_text = "I understand. Is the issue with OTP, document upload, login, or something else?"
            return await self._build_text_turn(call, reply_text, outcome="short-ack-reprompt")

        if response_plan["route"] == "general_capabilities":
            await self._set_business_state(call.call_sid, RESOLUTION_ACTION)
            reply_text = build_general_capabilities_reply(prompt_language, response_style=issue_state.response_style)
            reply_text = self._apply_voice_guardrail(
                reply_text,
                language_code=prompt_language,
                route="general_capabilities",
            )
            return await self._build_text_turn(call, reply_text, outcome="general-capabilities")

        issue_type = response_plan.get("issue_type") or detect_issue_type(transcript)
        if issue_type:
            self.issue_resolution_service.register_issue(call.call_sid, issue_type)
            symptom = response_plan.get("symptom") or detect_issue_symptom(transcript)
            if response_plan["route"] == "rule_guidance" and symptom and symptom != "unknown":
                await self._set_business_state(call.call_sid, RESOLUTION_ACTION)
                self.issue_resolution_service.register_symptom(call.call_sid, symptom)
                reply_text = build_issue_resolution_reply(issue_type, symptom, prompt_language)
                if response_plan.get("use_gemini"):
                    reply_text = await self._generate_gemini_reply(
                        history=history,
                        latest_user_text=transcript,
                        response_mode="normal",
                        language_code=prompt_language,
                        response_style=issue_state.response_style,
                        active_issue_type=issue_type,
                        call_sid=call.call_sid,
                        on_assistant_sentence=on_assistant_sentence,
                        llm_streaming_enabled=llm_streaming_enabled,
                    )
                    return await self._build_text_turn(call, reply_text, outcome=f"guided-{issue_type}-{symptom}-gemini")
                return await self._build_text_turn(call, reply_text, outcome=f"guided-{issue_type}-{symptom}")
            if response_plan["route"] == "issue_follow_up":
                await self._set_business_state(call.call_sid, ISSUE_CAPTURE)
                issue_state = self.issue_resolution_service.register_follow_up_prompt(call.call_sid)
                reply_text = build_issue_follow_up_question(
                    issue_type,
                    prompt_language,
                    follow_up_count=issue_state.follow_up_count,
                )
                if response_plan.get("use_gemini"):
                    reply_text = await self._generate_gemini_reply(
                        history=history,
                        latest_user_text=transcript,
                        response_mode="normal",
                        language_code=prompt_language,
                        response_style=issue_state.response_style,
                        active_issue_type=issue_type,
                        call_sid=call.call_sid,
                        on_assistant_sentence=on_assistant_sentence,
                        llm_streaming_enabled=llm_streaming_enabled,
                    )
                    return await self._build_text_turn(call, reply_text, outcome=f"guided-{issue_type}-gemini")
                return await self._build_text_turn(call, reply_text, outcome=f"guided-{issue_type}")
            if response_plan["route"] == "guided_clarify":
                await self._set_business_state(call.call_sid, ISSUE_CAPTURE)
                reply_text = await self._generate_gemini_reply(
                    history=history,
                    latest_user_text=transcript,
                    response_mode="normal",
                    language_code=prompt_language,
                    response_style=issue_state.response_style,
                    active_issue_type=issue_type,
                    call_sid=call.call_sid,
                    on_assistant_sentence=on_assistant_sentence,
                    llm_streaming_enabled=llm_streaming_enabled,
                )
                return await self._build_text_turn(call, reply_text, outcome=f"guided-{issue_type}-clarify")

        if issue_state.issue_type:
            symptom = response_plan.get("symptom") or detect_issue_symptom(transcript)
            if response_plan["route"] == "rule_guidance" and symptom:
                await self._set_business_state(call.call_sid, RESOLUTION_ACTION)
                self.issue_resolution_service.register_symptom(call.call_sid, symptom)
                if symptom == "unknown":
                    reply_text = await self._generate_gemini_reply(
                        history=history,
                        latest_user_text=transcript,
                        response_mode="normal",
                        language_code=prompt_language,
                        response_style=issue_state.response_style,
                        active_issue_type=issue_state.issue_type,
                        call_sid=call.call_sid,
                        on_assistant_sentence=on_assistant_sentence,
                        llm_streaming_enabled=llm_streaming_enabled,
                    )
                    return await self._build_text_turn(call, reply_text, outcome=f"guided-{issue_state.issue_type}-clarify")
                reply_text = build_issue_resolution_reply(issue_state.issue_type, symptom, prompt_language)
                if response_plan.get("use_gemini"):
                    reply_text = await self._generate_gemini_reply(
                        history=history,
                        latest_user_text=transcript,
                        response_mode="normal",
                        language_code=prompt_language,
                        response_style=issue_state.response_style,
                        active_issue_type=issue_state.issue_type,
                        call_sid=call.call_sid,
                        on_assistant_sentence=on_assistant_sentence,
                        llm_streaming_enabled=llm_streaming_enabled,
                    )
                    return await self._build_text_turn(call, reply_text, outcome=f"guided-{issue_state.issue_type}-{symptom}-gemini")
                return await self._build_text_turn(call, reply_text, outcome=f"guided-{issue_state.issue_type}-{symptom}")
            if response_plan["route"] == "guided_followup":
                await self._set_business_state(call.call_sid, RESOLUTION_ACTION)
                reply_text = await self._generate_gemini_reply(
                    history=history,
                    latest_user_text=transcript,
                    response_mode="normal",
                    language_code=prompt_language,
                    response_style=issue_state.response_style,
                    active_issue_type=issue_type,
                    call_sid=call.call_sid,
                    on_assistant_sentence=on_assistant_sentence,
                    llm_streaming_enabled=llm_streaming_enabled,
                )
                return await self._build_text_turn(call, reply_text, outcome=f"guided-{issue_state.issue_type}-followup")

        if response_plan["route"] == "max_turns_handoff":
            await self._set_business_state(call.call_sid, CONFIRMATION_CLOSING)
            return await self._build_text_turn(
                call,
                build_human_handoff_reply(prompt_language),
                should_hangup=True,
                outcome="max-turns",
            )

        quality_state = self.audio_quality_service.get_state(call.call_sid)
        noisy_intent = None
        if response_plan["route"] in {"noisy_fallback", "noisy_intent"}:
            await self._set_business_state(call.call_sid, ISSUE_CAPTURE)
            noisy_intent = self.audio_quality_service.normalize_noisy_intent(transcript)
            if noisy_intent:
                quality_state.last_intent = noisy_intent
                await self._publish_audio_quality(call.call_sid, quality_state.as_payload())
                fallback_turn = await self._handle_fallback_intent(call, noisy_intent, from_number)
                if fallback_turn:
                    return fallback_turn
                return await self._build_text_turn(call, build_noisy_fallback_reply(prompt_language))
            return await self._build_text_turn(call, build_noisy_fallback_reply(prompt_language))

        await self._publish_speaking(call.call_sid, "assistant", True)
        await self._set_business_state(call.call_sid, RESOLUTION_ACTION)
        response_mode = response_plan.get("reply_mode") or (
            "noisy" if self.audio_quality_service.should_use_short_responses(quality_state) else "normal"
        )
        reply_text = await self._generate_gemini_reply(
            history=history,
            latest_user_text=transcript,
            response_mode=response_mode,
            language_code=prompt_language,
            response_style=issue_state.response_style,
            active_issue_type=issue_state.issue_type,
            call_sid=call.call_sid,
            on_assistant_sentence=on_assistant_sentence,
            llm_streaming_enabled=llm_streaming_enabled,
        )
        noisy_ack = build_noisy_mode_acknowledgement(prompt_language)
        if response_mode == "noisy" and noisy_ack.lower() not in reply_text.lower():
            reply_text = f"{noisy_ack} {reply_text}"
        reply_text = self._apply_voice_guardrail(
            reply_text,
            language_code=prompt_language,
            route=str(response_plan.get("route") or "gemini_response"),
        )
        reply = await self._build_text_turn(call, reply_text)
        await self._publish_speaking(call.call_sid, "assistant", False)
        return reply

    async def add_transcript(self, call: Call, speaker: str, text: str) -> None:
        cleaned_text = sanitize_spoken_text(text)
        transcript = Transcript(call_id=call.id, speaker=speaker, text=cleaned_text)
        self.session.add(transcript)
        await self.session.commit()
        logger.info(
            "Call %s %s transcript stored chars=%s",
            call.call_sid,
            speaker,
            len(cleaned_text),
        )
        await self._publish_transcript(call, speaker, cleaned_text, transcript.created_at)

    async def get_recent_history(self, call_id: int) -> list[dict[str, str]]:
        statement: Select[tuple[Transcript]] = (
            select(Transcript)
            .where(Transcript.call_id == call_id)
            .order_by(Transcript.created_at.asc(), Transcript.id.asc())
        )
        result = await self.session.execute(statement)
        transcripts = result.scalars().all()
        return [{"speaker": item.speaker, "text": item.text} for item in transcripts[-self.max_turns :]]

    async def _record_opt_out(self, phone_number: str, reason: str) -> None:
        result = await self.session.execute(select(OptOut).where(OptOut.phone_number == phone_number))
        existing = result.scalar_one_or_none()
        if existing is None:
            self.session.add(OptOut(phone_number=phone_number, reason=reason))
            await self.session.commit()

    async def _build_text_turn(
        self,
        call: Call,
        text: str,
        should_hangup: bool = False,
        outcome: str | None = None,
    ) -> ConversationReply:
        max_spoken_chars = max(80, int(self.gemini_service.settings.assistant_tts_max_chars))
        language_code = self._prompt_language(call)
        base_text = sanitize_spoken_text(text, max_length=max_spoken_chars)
        response_style = self.issue_resolution_service.get_state(call.call_sid).response_style
        styled_text = apply_response_style(base_text, language_code, response_style)
        if language_code == "hi-IN":
            cleaned_text = enforce_devanagari_hindi_reply(styled_text)
        else:
            cleaned_text = sanitize_spoken_text(styled_text, max_length=max_spoken_chars)
        cleaned_text = self._optimize_voice_reply_for_latency(cleaned_text, language_code=language_code, outcome=outcome)
        cleaned_text = self._normalize_brand_phrase(cleaned_text)
        cleaned_text = await self._suppress_repetitive_assistant_reply(call, cleaned_text)
        logger.info(
            "Latency step=assistant_text_ready call=%s timestamp=%s language=%s text_preview=%s",
            call.call_sid,
            utc_now_iso(),
            language_code,
            cleaned_text[:80],
        )
        emit_latency_event(
            {
                "step": "assistant_text_ready",
                "call_sid": call.call_sid,
                "event_timestamp": utc_now_iso(),
                "language": language_code,
                "text_preview": cleaned_text[:80],
            }
        )
        if outcome:
            logger.info(
                "Assistant outcome call=%s outcome=%s language=%s text_preview=%s",
                call.call_sid,
                outcome,
                language_code,
                cleaned_text[:80],
            )
        await self.add_transcript(call, "assistant", cleaned_text)
        call.language = language_code
        if outcome:
            call.final_outcome = outcome
        if should_hangup:
            call.status = "completed"
            call.ended_at = datetime.now(UTC)
        await self.session.commit()
        await self._publish_call_status(call)
        if should_hangup:
            await self._publish_call_phase(call.call_sid, CALL_SUMMARY_READY)
            await self._publish_call_summary(call.call_sid)

        return ConversationReply(
            text=cleaned_text,
            language_code=language_code,
            should_hangup=should_hangup,
        )

    async def _synthesize_reply(self, call: Call, reply: ConversationReply) -> ConversationTurn:
        audio_path = await self.tts_service.synthesize(
            text=reply.text,
            language_code=reply.language_code,
            call_sid=call.call_sid,
        )
        logger.info(
            "Latency step=assistant_audio_ready call=%s mode=recording timestamp=%s audio_path=%s",
            call.call_sid,
            utc_now_iso(),
            audio_path,
        )
        emit_latency_event(
            {
                "step": "assistant_audio_ready",
                "call_sid": call.call_sid,
                "mode": "recording",
                "event_timestamp": utc_now_iso(),
                "audio_path": str(audio_path),
            }
        )
        return ConversationTurn(
            text=reply.text,
            public_audio_url=build_public_url(self.public_url, f"/static/generated_audio/{audio_path.name}"),
            language_code=reply.language_code,
            should_hangup=reply.should_hangup,
        )

    async def _handle_unclear_audio(
        self,
        call: Call,
        transcript: str,
        confidence: float,
        confidence_source: str,
        speech_detected: bool,
    ) -> ConversationReply:
        quality_state = self.audio_quality_service.get_state(call.call_sid)
        prompt_language = self._prompt_language(call)
        await self._publish_audio_quality(call.call_sid, quality_state.as_payload())

        if transcript.strip():
            await self.add_transcript(call, "customer", transcript)

        if not transcript.strip():
            if quality_state.fallback_mode:
                reply = "आवाज़ साफ़ नहीं आ रही है। कृपया हाँ, नहीं, कॉलबैक, या लिंक बोलिए।"
            elif quality_state.consecutive_unclear_count >= self.audio_quality_service.settings.noisy_call_retry_prompt_trigger:
                reply = "आवाज़ साफ़ नहीं आई। कृपया छोटा जवाब दें: हाँ, नहीं, कॉलबैक, या लिंक।"
            elif quality_state.consecutive_unclear_count == 1:
                reply = build_empty_input_reply(prompt_language)
            else:
                reply = build_first_unclear_reply(prompt_language)
        else:
            if quality_state.fallback_mode:
                reply = build_noisy_fallback_reply(prompt_language)
            elif quality_state.consecutive_unclear_count >= self.audio_quality_service.settings.noisy_call_retry_prompt_trigger:
                reply = build_second_unclear_reply(prompt_language)
            elif quality_state.consecutive_unclear_count == 1:
                reply = build_first_unclear_reply(prompt_language)
            else:
                reply = build_empty_input_reply(prompt_language)

        logger.info(
            "Unclear audio for %s confidence=%.2f source=%s speech=%s retry=%s fallback=%s",
            call.call_sid,
            confidence,
            confidence_source,
            speech_detected,
            quality_state.retry_count,
            quality_state.fallback_mode,
        )
        return await self._build_text_turn(call, reply, should_hangup=False)

    async def _handle_fallback_intent(
        self,
        call: Call,
        intent: str,
        from_number: str | None,
    ) -> ConversationReply | None:
        prompt_language = self._prompt_language(call)
        if intent in {"no", "not_interested"}:
            if from_number:
                await self._record_opt_out(from_number, "caller-declined-noisy-fallback")
            return await self._build_text_turn(
                call,
                build_opt_out_reply(prompt_language),
                should_hangup=True,
                outcome="noisy-declined",
            )

        if intent in {"callback", "busy"}:
            return await self._build_text_turn(
                call,
                build_callback_ack(prompt_language),
                should_hangup=True,
                outcome="callback-requested",
            )

        if intent == "send_link":
            return await self._build_text_turn(
                call,
                build_sms_link_ack(prompt_language),
                should_hangup=True,
                outcome="sms-link-requested",
            )

        if intent == "yes":
            return await self._build_text_turn(
                call,
                build_short_choice_prompt(prompt_language),
                should_hangup=False,
            )

        if intent == "repeat":
            return await self._build_text_turn(call, build_noisy_fallback_reply(prompt_language))

        return None

    async def _handle_business_state_transition(
        self,
        *,
        call: Call,
        transcript: str,
        customer_name: str,
        from_number: str | None,
        prompt_language: str,
        turn_language: str,
        selected_language: str | None,
        consent_choice: str,
        issue_state,
        last_customer_text: str,
    ) -> ConversationReply | None:
        business_state = issue_state.business_state
        forced_customer_name = (customer_name or "").strip()
        optional_customer_name = await self._pick_customer_name(call, forced_customer_name)
        normalized_transcript = normalize_issue_text(transcript)
        transcript_has_issue = bool(detect_issue_type(transcript) or detect_issue_symptom(transcript))

        if business_state in {OPENING, CONSENT_CHECK}:
            await self.add_transcript(call, "customer", transcript)
            self.audio_quality_service.register_success(call.call_sid, transcript)
            await self._publish_audio_quality(call.call_sid, self.audio_quality_service.get_state(call.call_sid).as_payload())

            if self._looks_like_call_purpose_question(transcript):
                await self._set_business_state(call.call_sid, CONSENT_CHECK)
                reply_text = (
                    f"{build_process_resume_context_reply(language=prompt_language)} "
                    f"{build_consent_reprompt(prompt_language, name=optional_customer_name)}"
                )
                return await self._build_text_turn(call, reply_text, outcome="context-recap")

            if consent_choice == "granted":
                if call.language != "hi-IN":
                    call.language = "hi-IN"
                    await self.session.commit()
                    await self._publish_call_status(call)
                await self._set_business_state(call.call_sid, IDENTITY_VERIFICATION)
                return await self._build_text_turn(
                    call,
                    build_identity_verification_prompt(name=forced_customer_name, language="hi-IN"),
                )

            if consent_choice == "callback":
                await self._set_business_state(call.call_sid, CONFIRMATION_CLOSING)
                return await self._build_text_turn(
                    call,
                    build_callback_ack(prompt_language),
                    should_hangup=True,
                    outcome="callback-requested",
                )

            if consent_choice == "send_link":
                await self._set_business_state(call.call_sid, CONFIRMATION_CLOSING)
                return await self._build_text_turn(
                    call,
                    build_sms_link_ack(prompt_language),
                    should_hangup=True,
                    outcome="sms-link-requested",
                )

            if consent_choice == "opt_out":
                if from_number:
                    await self._record_opt_out(from_number, "caller-requested-opt-out")
                await self._set_business_state(call.call_sid, CONFIRMATION_CLOSING)
                return await self._build_text_turn(
                    call,
                    build_opt_out_reply(prompt_language),
                    should_hangup=True,
                    outcome="opted-out",
                )

            await self._set_business_state(call.call_sid, CONSENT_CHECK)
            return await self._build_text_turn(
                call,
                build_consent_reprompt(prompt_language, name=optional_customer_name),
            )

        if business_state == LANGUAGE_SELECTION:
            await self.add_transcript(call, "customer", transcript)
            self.audio_quality_service.register_success(call.call_sid, transcript)
            await self._publish_audio_quality(call.call_sid, self.audio_quality_service.get_state(call.call_sid).as_payload())

            target_language = selected_language or turn_language or self._prompt_language(call)
            if target_language != call.language:
                call.language = target_language
                await self.session.commit()
                await self._publish_call_status(call)
            prompt_language = self._prompt_language(call)

            if not selected_language and not normalized_transcript:
                return await self._build_text_turn(
                    call,
                    build_language_preference_reprompt(name=optional_customer_name),
                )

            await self._set_business_state(call.call_sid, IDENTITY_VERIFICATION)
            if selected_language:
                reply_text = (
                    f"{build_language_selected_reply(language=prompt_language)} "
                    f"{build_identity_verification_prompt(name=forced_customer_name, language=prompt_language)}"
                )
            else:
                reply_text = build_identity_verification_prompt(name=forced_customer_name, language=prompt_language)
            return await self._build_text_turn(call, reply_text)

        if business_state == IDENTITY_VERIFICATION:
            await self.add_transcript(call, "customer", transcript)
            self.audio_quality_service.register_success(call.call_sid, transcript)
            await self._publish_audio_quality(call.call_sid, self.audio_quality_service.get_state(call.call_sid).as_payload())

            if detect_auth_confirmation(transcript):
                self.issue_resolution_service.mark_identity_verified(call.call_sid)
                await self._set_business_state(call.call_sid, CONTEXT_SETTING)
                return await self._build_text_turn(
                    call,
                    build_context_setting_prompt(language=prompt_language, name=optional_customer_name),
                )

            if detect_auth_denial(transcript):
                await self._set_business_state(call.call_sid, CONFIRMATION_CLOSING)
                return await self._build_text_turn(
                    call,
                    build_identity_mismatch_reply(prompt_language),
                    should_hangup=True,
                    outcome="identity-mismatch",
                )

            return await self._build_text_turn(
                call,
                build_identity_reprompt(name=optional_customer_name, language=prompt_language),
            )

        if business_state == CONTEXT_SETTING:
            if transcript_has_issue:
                await self._set_business_state(call.call_sid, ISSUE_CAPTURE)
                return None

            await self.add_transcript(call, "customer", transcript)
            self.audio_quality_service.register_success(call.call_sid, transcript)
            await self._publish_audio_quality(call.call_sid, self.audio_quality_service.get_state(call.call_sid).as_payload())

            if self._is_duplicate_short_acknowledgement(transcript, last_customer_text) or is_simple_acknowledgement(transcript):
                await self._set_business_state(call.call_sid, ISSUE_CAPTURE)
                return await self._build_text_turn(
                    call,
                    build_issue_capture_prompt(prompt_language, name=optional_customer_name),
                )

            await self._set_business_state(call.call_sid, ISSUE_CAPTURE)
            return await self._build_text_turn(
                call,
                build_post_greeting_issue_prompt(prompt_language, name=optional_customer_name),
            )

        return None

    @staticmethod
    def _wants_to_end_call(text: str) -> bool:
        return wants_goodbye(text) or ConversationService._looks_like_call_termination_intent(text)

    @staticmethod
    def _looks_like_call_termination_intent(text: str) -> bool:
        normalized = normalize_issue_text(text)
        if not normalized:
            return False
        hard_end_markers = (
            "फोन रख दो",
            "phone rakh do",
            "call kaat do",
            "कॉल काट दो",
            "disconnect",
            "hang up",
            "बस फोन रखो",
        )
        return any(marker in normalized for marker in hard_end_markers)

    @staticmethod
    def _looks_like_no_issue_statement(text: str) -> bool:
        normalized = normalize_issue_text(text)
        if not normalized:
            return False
        markers = (
            "कोई समस्या नहीं",
            "समस्या नहीं",
            "समस्या कुछ नहीं",
            "कोई दिक्कत नहीं",
            "दिक्कत नहीं",
            "problem nahi",
            "no issue",
            "no problem",
        )
        blockers = ("क्या", "kya", "why", "क्यों")
        if any(blocker in normalized for blocker in blockers):
            return False
        return any(marker in normalized for marker in markers)

    @staticmethod
    def _looks_like_capability_query(text: str) -> bool:
        normalized = normalize_issue_text(text)
        if not normalized:
            return False
        markers = (
            "feature",
            "features",
            "fees",
            "charges",
            "eligibility",
            "benefit",
            "benefits",
            "card limit",
            "reward",
            "फीचर",
            "फीचर्स",
            "फीस",
            "चार्ज",
            "शुल्क",
            "पात्रता",
            "लिमिट",
            "बेनिफिट",
        )
        return any(marker in normalized for marker in markers)

    @staticmethod
    def _looks_like_call_purpose_question(text: str) -> bool:
        normalized = normalize_issue_text(text)
        if not normalized:
            return False
        markers = (
            "why are you calling",
            "why did you call",
            "reason for call",
            "purpose of call",
            "what is this call about",
            "why this call",
            "call kyun",
            "call kyu",
            "kis liye call",
            "kisliye call",
            "कॉल क्यों",
            "क्यों कॉल",
            "किस लिए कॉल",
            "किसलिए कॉल",
            "किस लिए फोन",
            "क्यों फोन",
            "कॉल किस लिए",
            "आपने कॉल क्यों किया",
            "आपने किस लिए कॉल किया",
        )
        return any(marker in normalized for marker in markers)

    @staticmethod
    def _looks_like_issue_resolved(text: str) -> bool:
        normalized = normalize_issue_text(text)
        if not normalized:
            return False

        strong_completion_phrases = (
            "issue resolved",
            "problem solved",
            "resolved",
            "resolve ho gaya",
            "resolve ho gya",
            "all set",
            "registration complete",
            "registration completed",
            "process complete",
            "process completed",
            "register ho gaya",
            "application complete",
            "application completed",
            "application ho gaya",
            "upload ho gaya",
            "upload ho gaya hai",
            "file upload ho gaya",
            "file upload ho gaya hai",
            "document upload ho gaya",
            "document upload ho gaya hai",
            "document submitted",
            "all done thank you",
            "done thank you",
            "everything done",
            "sab ho gaya",
            "sab ho gaya hai",
            "thank you for calling",
            "रजिस्ट्रेशन कंप्लीट",
            "रजिस्ट्रेशन complete",
            "रजिस्ट्रेशन पूरा",
            "प्रोसेस कंप्लीट",
            "प्रोसेस पूरा",
            "कंप्लीटेड",
            "अपलोड हो गया",
            "अपलोड हो गया है",
            "फाइल अपलोड हो गया",
            "फाइल अपलोड हो गया है",
            "डॉक्यूमेंट अपलोड हो गया",
            "डॉक्यूमेंट अपलोड हो गया है",
            "डॉक्यूमेंट सबमिट हो गया",
            "सब चीज हो गया",
            "सब चीज़ हो गया",
            "सब चीज हो गया है",
            "सब चीज़ हो गया है",
            "समस्या हल हो गई",
            "दिक्कत हल हो गई",
            "ठीक हो गया",
            "रिजॉल्वड",
            "रिज़ॉल्वड",
            "रिजोल्व",
            "सॉल्व हो गया",
            "कोई दिक्कत नहीं",
            "कोई दिक्कत ही नहीं",
            "दिक्कत नहीं आ रही",
            "दिक्कत ही नहीं आ रही",
            "कोई समस्या नहीं",
            "कोई समस्या ही नहीं",
        )
        completion_markers = (
            "done",
            "resolved",
            "complete",
            "completed",
            "solve",
            "solved",
            "ho gaya",
            "ho gaya",
            "ho gya",
            "hogaya",
            "resolve",
            "रिजॉल्वड",
            "रिज़ॉल्वड",
            "सॉल्व",
            "पूरा",
            "कंप्लीट",
            "कंप्लीटेड",
            "हल",
            "ठीक",
        )
        scope_keywords = (
            "registration",
            "register",
            "process",
            "application",
            "upload",
            "document",
            "file",
            "submit",
            "issue",
            "problem",
            "dikkat",
            "samasya",
            "kyc",
            "verification",
            "रजिस्ट्रेशन",
            "प्रोसेस",
            "एप्लिकेशन",
            "आवेदन",
            "अपलोड",
            "डॉक्यूमेंट",
            "फाइल",
            "सबमिट",
            "दिक्कत",
            "समस्या",
            "केवाईसी",
            "वेरिफिकेशन",
        )

        if any(phrase in normalized for phrase in strong_completion_phrases):
            strong_match = True
        else:
            strong_match = False

        contextual_completion = any(marker in normalized for marker in completion_markers) and any(
            keyword in normalized for keyword in scope_keywords
        )
        if not (strong_match or contextual_completion):
            return False

        negated_completion_phrases = (
            "नहीं हुआ",
            "नहीं हो गया",
            "नहीं हुआ है",
            "complete nahi",
            "complete nahi hua",
            "completed nahi",
            "not complete",
            "not completed",
            "not resolved",
            "resolve nahi",
            "रिजॉल्व नहीं",
            "solve nahi",
            "हल नहीं",
        )
        if any(phrase in normalized for phrase in negated_completion_phrases):
            return False

        blocking_markers = ("pending", "stuck", "error", "failed", "problem hai", "issue hai", "दिक्कत है", "समस्या है")
        return not any(marker in normalized for marker in blocking_markers)

    @staticmethod
    def _should_fallback_to_gemini_for_guidance(history: list[dict[str, str]], reply_text: str) -> bool:
        normalized_reply = normalize_issue_text(reply_text)
        if not normalized_reply:
            return False

        recent_assistant_turns = [
            normalize_issue_text(item["text"])
            for item in history[-4:]
            if item.get("speaker") == "assistant" and item.get("text")
        ]
        if not recent_assistant_turns:
            return False

        return any(previous_reply == normalized_reply for previous_reply in recent_assistant_turns[-2:])

    @staticmethod
    def _looks_like_resolution_closure(text: str) -> bool:
        normalized = normalize_issue_text(text)
        if not normalized:
            return False

        closure_markers = (
            "thank you",
            "thanks",
            "thanks bye",
            "thank you bye",
            "for the calling",
            "goodbye",
            "bye",
            "dhanyawad",
            "shukriya",
            "धन्यवाद",
            "शुक्रिया",
            "थैंक यू",
            "बस",
            "that is all",
            "that s all",
            "nothing else",
            "no more",
        )
        return any(marker in normalized for marker in closure_markers)

    @staticmethod
    def _is_opt_out_request(text: str) -> bool:
        normalized = text.lower()
        return any(
            phrase in normalized
            for phrase in [
                "not interested",
                "do not call",
                "don't call",
                "unsubscribe",
                "mat call karo",
            ]
        )

    @staticmethod
    def _looks_like_application_not_started(text: str) -> bool:
        normalized = normalize_issue_text(text)
        if not normalized:
            return False
        markers = (
            "i did not apply",
            "i didnt apply",
            "i did not submit",
            "never applied",
            "not applied",
            "no application",
            "did not fill form",
            "didnt fill form",
            "i have not applied",
            "main ne apply nahi kiya",
            "maine apply nahi kiya",
            "maine apply hi nahi kiya",
            "application nahi kiya",
            "application hi nahi kiya",
            "maine aavedan nahi kiya",
            "maine aavedan hi nahi kiya",
            "मैंने आवेदन नहीं किया",
            "मैंने आवेदन ही नहीं किया",
            "आवेदन नहीं किया",
            "आवेदन ही नहीं किया",
            "मैंने अप्लाई नहीं किया",
            "मैंने अप्लाई ही नहीं किया",
            "अप्लाई नहीं किया",
            "अप्लाई ही नहीं किया",
            "मैंने फॉर्म नहीं भरा",
            "मैंने कोई फॉर्म नहीं डाला",
            "कोई फॉर्म नहीं डाला",
            "फॉर्म नहीं भरा",
        )
        return any(marker in normalized for marker in markers)

    @staticmethod
    def _is_duplicate_short_acknowledgement(current_text: str, previous_text: str) -> bool:
        if not current_text or not previous_text:
            return False
        if not (is_simple_acknowledgement(current_text) or looks_like_repeated_acknowledgement(current_text)):
            return False
        if not (is_simple_acknowledgement(previous_text) or looks_like_repeated_acknowledgement(previous_text)):
            return False
        return normalize_issue_text(current_text) == normalize_issue_text(previous_text)

    async def _pick_customer_name(self, call: Call, customer_name: str, *, force: bool = False) -> str:
        cleaned_name = (customer_name or "").strip()
        if not cleaned_name:
            return ""
        if force:
            return cleaned_name
        history = await self.get_recent_history(call.id)
        recent_assistant_turns = [
            item["text"]
            for item in history[-4:]
            if item.get("speaker") == "assistant" and item.get("text")
        ]
        if any(self._assistant_mentions_name(text, cleaned_name) for text in recent_assistant_turns[-2:]):
            return ""
        return cleaned_name

    @staticmethod
    def _assistant_mentions_name(text: str, customer_name: str) -> bool:
        normalized_text = normalize_issue_text(text)
        normalized_name = normalize_issue_text(customer_name)
        if not normalized_text or not normalized_name:
            return False
        if normalized_name in normalized_text:
            return True
        name_tokens = [token for token in normalized_name.split() if len(token) >= 2]
        if len(name_tokens) < 2:
            return False
        text_tokens = set(normalized_text.split())
        return all(token in text_tokens for token in name_tokens[:2])

    def _is_low_signal_transcript(self, transcript: str) -> bool:
        if is_short_valid_intent(transcript):
            return False
        normalized = normalize_issue_text(transcript)
        meaningful_chars = sum(1 for char in normalized if char.isalnum())
        min_chars = max(1, int(self.audio_quality_service.settings.empty_transcript_min_chars))
        return meaningful_chars < min_chars

    @staticmethod
    def _normalize_brand_phrase(text: str) -> str:
        normalized = re.sub(r"\bBOBCards\b", "BOB Card", text, flags=re.IGNORECASE)
        normalized = normalized.replace("बीओबी कार्ड्स", "BOB Card").replace("बीओबी कार्ड", "BOB Card")
        normalized = normalized.replace("BOB Cards", "BOB Card")
        return sanitize_spoken_text(normalized)

    async def _suppress_repetitive_assistant_reply(self, call: Call, candidate_text: str) -> str:
        if not candidate_text.strip():
            return candidate_text

        history = await self.get_recent_history(call.id)
        recent_assistant = [item["text"] for item in history if item.get("speaker") == "assistant" and item.get("text")]
        if not recent_assistant:
            return candidate_text

        business_state = self.issue_resolution_service.get_state(call.call_sid).business_state
        if business_state == RESOLUTION_ACTION:
            return candidate_text
        guidance_states = {ISSUE_CAPTURE, RESOLUTION_ACTION}
        suppress_near_duplicate_questions = business_state not in guidance_states
        recent_window = recent_assistant[-3:]
        repeated_reference = next(
            (
                item
                for item in reversed(recent_window)
                if self._is_repeated_assistant_text(candidate_text, item)
                or (
                    suppress_near_duplicate_questions
                    and self._is_near_duplicate_question(candidate_text, item)
                )
            ),
            "",
        )
        if repeated_reference:
            issue_state = self.issue_resolution_service.register_repeat_suppression(call.call_sid)
            repeat_count = issue_state.repeat_suppression_count
            if repeat_count > self.max_repeat_suppression and business_state in {ISSUE_CAPTURE, RESOLUTION_ACTION, CONFIRMATION_CLOSING}:
                replacement = build_resolution_follow_up_prompt(self._prompt_language(call))
            else:
                replacement = self._short_reprompt_for_business_state(
                    business_state,
                    self._prompt_language(call),
                    variant_index=repeat_count,
                )
            logger.info(
                "Assistant repeat suppressed for call=%s business_state=%s repeat_count=%s old_preview=%s replacement_preview=%s",
                call.call_sid,
                business_state,
                repeat_count,
                candidate_text[:80],
                replacement[:80],
            )
            emit_latency_event(
                {
                    "step": "assistant_repeat_suppressed",
                    "call_sid": call.call_sid,
                    "event_timestamp": utc_now_iso(),
                    "business_state": business_state,
                    "repeat_count": repeat_count,
                    "old_preview": candidate_text[:80],
                    "replacement_preview": replacement[:80],
                }
            )
            return replacement
        self.issue_resolution_service.clear_repeat_suppression(call.call_sid)

        last_assistant_text = recent_assistant[-1]
        if last_assistant_text.startswith("नमस्ते") and candidate_text.startswith("नमस्ते"):
            without_repeat_salutation = re.sub(r"^नमस्ते[।,\s]*", "", candidate_text).strip()
            if without_repeat_salutation:
                return without_repeat_salutation
        return candidate_text

    @staticmethod
    def _is_repeated_assistant_text(candidate_text: str, reference_text: str) -> bool:
        if not candidate_text or not reference_text:
            return False
        normalized_candidate = normalize_issue_text(candidate_text)
        normalized_reference = normalize_issue_text(reference_text)
        if not normalized_candidate or not normalized_reference:
            return False
        return (
            normalized_candidate == normalized_reference
            or (
                min(len(normalized_candidate), len(normalized_reference)) >= 18
                and (
                    normalized_candidate in normalized_reference
                    or normalized_reference in normalized_candidate
                )
            )
        )

    @staticmethod
    def _is_near_duplicate_question(candidate_text: str, reference_text: str) -> bool:
        if not candidate_text or not reference_text:
            return False
        question_markers = ("?", "कृपया", "बताइए", "कहिए", "please", "tell", "say")
        candidate_norm = normalize_issue_text(candidate_text)
        reference_norm = normalize_issue_text(reference_text)
        if not any(marker in candidate_text for marker in question_markers):
            return False
        if not any(marker in reference_text for marker in question_markers):
            return False
        candidate_tokens = {token for token in re.findall(r"\w+", candidate_norm) if len(token) > 2}
        reference_tokens = {token for token in re.findall(r"\w+", reference_norm) if len(token) > 2}
        if min(len(candidate_tokens), len(reference_tokens)) < 4:
            return False
        overlap = len(candidate_tokens & reference_tokens) / max(1, min(len(candidate_tokens), len(reference_tokens)))
        return overlap >= 0.72

    @staticmethod
    def _short_reprompt_for_business_state(
        business_state: BusinessState,
        language: str = "hi-IN",
        variant_index: int = 0,
    ) -> str:
        if language == "en-IN":
            if business_state in {OPENING, CONSENT_CHECK}:
                return "Is this a good time for a quick two-minute call?"
            if business_state == LANGUAGE_SELECTION:
                return "Please say Hindi or English."
            if business_state == IDENTITY_VERIFICATION:
                return "Am I speaking with the correct customer? Please say yes or no."
            if business_state in {CONTEXT_SETTING, ISSUE_CAPTURE, RESOLUTION_ACTION}:
                variants = (
                    "Please share your issue briefly.",
                    "Please tell me the exact step where you are blocked.",
                    "Please say what is visible on your screen right now.",
                )
                return variants[variant_index % len(variants)]
            return "Please repeat that briefly once."
        if business_state in {OPENING, CONSENT_CHECK}:
            return "क्या अभी दो मिनट बात करना ठीक रहेगा?"
        if business_state == LANGUAGE_SELECTION:
            return "कृपया हिंदी या अंग्रेज़ी कहिए।"
        if business_state == IDENTITY_VERIFICATION:
            return "क्या मैं सही ग्राहक से बात कर रही हूँ? हाँ या नहीं कहिए।"
        if business_state in {CONTEXT_SETTING, ISSUE_CAPTURE, RESOLUTION_ACTION}:
            variants = (
                "कृपया समस्या संक्षेप में बताइए।",
                "कृपया बताइए आप किस चरण पर रुके हैं।",
                "अभी स्क्रीन पर क्या दिख रहा है, वही बताइए।",
            )
            return variants[variant_index % len(variants)]
        return "कृपया एक बार फिर संक्षेप में बताइए।"

    @staticmethod
    def _optimize_voice_reply_for_latency(text: str, *, language_code: str, outcome: str | None) -> str:
        cleaned = sanitize_spoken_text(text)
        if not cleaned:
            return text

        max_chars = 170
        if outcome in {"resolution-complete", "issue-resolved", "customer-ended", "general-capabilities"}:
            max_chars = 125

        sentence_limit = 2
        if outcome in {"resolution-complete", "issue-resolved", "customer-ended"}:
            sentence_limit = 1

        sentences = [part.strip() for part in re.split(r"[।.!?]+", cleaned) if part.strip()]
        if sentences:
            trimmed = "। ".join(sentences[:sentence_limit]).strip()
            if language_code == "hi-IN" and trimmed and not trimmed.endswith("।"):
                trimmed = f"{trimmed}।"
        else:
            trimmed = cleaned

        return sanitize_spoken_text(trimmed, max_length=max_chars)

    @staticmethod
    def _should_auto_detect_language(
        *,
        transcript: str,
        customer_turn_count: int,
        current_language: str | None,
        detected_turn_language: str,
        consent_choice: str,
    ) -> bool:
        if not transcript.strip():
            return False
        if normalize_language(current_language) == normalize_language(detected_turn_language):
            return False
        if customer_turn_count > 1:
            return False
        if looks_like_repeated_acknowledgement(transcript):
            return False
        if is_simple_acknowledgement(transcript):
            return False
        if consent_choice in {"callback", "send_link", "opt_out"}:
            return False
        if is_opening_response(transcript) and consent_choice != "granted":
            return False
        return True

    async def _publish_call_status(self, call: Call) -> None:
        if not self.realtime_service:
            return
        await self.realtime_service.publish_call_status(
            call_sid=call.call_sid,
            call_id=call.id,
            status=call.status,
            started_at=call.started_at,
            ended_at=call.ended_at,
            language=call.language,
            final_outcome=call.final_outcome,
        )

    async def _publish_transcript(
        self,
        call: Call,
        speaker: str,
        text: str,
        created_at: datetime | None,
    ) -> None:
        if not self.realtime_service:
            return
        await self.realtime_service.publish_transcript(
            call_sid=call.call_sid,
            call_id=call.id,
            speaker=speaker,
            text=text,
            created_at=created_at,
        )

    async def _publish_speaking(self, call_sid: str, role: str, is_speaking: bool) -> None:
        if not self.realtime_service:
            return
        await self.realtime_service.publish_speaking_event(call_sid, role, is_speaking)

    async def _publish_audio_quality(self, call_sid: str, quality_payload: dict) -> None:
        if not self.realtime_service:
            return
        await self.realtime_service.publish_audio_quality(call_sid, quality_payload)

    async def _publish_main_points(self, call_sid: str, main_points: dict) -> None:
        if not self.realtime_service:
            return
        await self.realtime_service.publish_main_points(call_sid, main_points)

    async def _publish_response_plan(self, call_sid: str, response_plan: dict) -> None:
        if not self.realtime_service:
            return
        await self.realtime_service.publish_response_plan(call_sid, response_plan)

    async def _publish_call_summary(self, call_sid: str) -> None:
        if not self.realtime_service:
            return
        await self.realtime_service.publish_call_summary(call_sid)

    async def _publish_gemini_decision(self, call_sid: str, gemini_decision: dict) -> None:
        if not self.realtime_service:
            return
        await self.realtime_service.publish_gemini_decision(call_sid, gemini_decision)

    async def _publish_call_phase(self, call_sid: str, phase: str) -> None:
        if not self.realtime_service:
            return
        await self.realtime_service.publish_call_phase(call_sid, phase)

    async def _publish_business_state(self, call_sid: str, business_state: BusinessState) -> None:
        if not self.realtime_service:
            return
        await self.realtime_service.publish_business_state(call_sid, business_state)

    async def _set_business_state(self, call_sid: str, business_state: BusinessState) -> None:
        self.issue_resolution_service.set_business_state(call_sid, business_state)
        await self._publish_business_state(call_sid, business_state)

    async def _generate_gemini_reply(
        self,
        *,
        history: list[dict[str, str]],
        latest_user_text: str,
        response_mode: str,
        language_code: str,
        response_style: str,
        active_issue_type: str | None,
        call_sid: str,
        on_assistant_sentence: Callable[[str, str], Awaitable[None]] | None,
        llm_streaming_enabled: bool | None = None,
    ) -> str:
        await self._publish_call_phase(call_sid, GEMINI_REQUESTED)
        stream_buffer = ""
        streamed_sentence_count = 0
        last_assistant_text = ""
        sentence_max_chars = max(80, int(self.gemini_service.settings.assistant_tts_sentence_max_chars))
        flush_timeout_ms = max(180, int(self.gemini_service.settings.assistant_stream_flush_timeout_ms))
        partial_min_chars = max(8, int(self.gemini_service.settings.assistant_stream_partial_min_chars))
        stream_buffer_lock = asyncio.Lock()
        stream_flush_task: asyncio.Task | None = None
        for item in reversed(history):
            if item.get("speaker") == "assistant" and item.get("text"):
                last_assistant_text = item["text"]
                break

        async def _emit_sentence(cleaned_sentence: str, reason: str) -> None:
            nonlocal streamed_sentence_count, last_assistant_text
            if self._is_repeated_assistant_text(cleaned_sentence, last_assistant_text):
                emit_latency_event(
                    {
                        "step": "assistant_stream_sentence_suppressed",
                        "call_sid": call_sid,
                        "event_timestamp": utc_now_iso(),
                        "reason": f"repeat_vs_last_assistant_{reason}",
                        "text_preview": cleaned_sentence[:80],
                    }
                )
                return
            streamed_sentence_count += 1
            last_assistant_text = cleaned_sentence
            emit_latency_event(
                {
                    "step": "assistant_sentence_ready",
                    "call_sid": call_sid,
                    "event_timestamp": utc_now_iso(),
                    "sentence_index": streamed_sentence_count,
                    "language": language_code,
                    "text_preview": cleaned_sentence[:80],
                }
            )
            await on_assistant_sentence(cleaned_sentence, language_code)

        async def _flush_partial_buffer(reason: str) -> None:
            nonlocal stream_buffer
            async with stream_buffer_lock:
                partial = sanitize_spoken_text(stream_buffer.strip(), max_length=sentence_max_chars)
                if not partial:
                    return
                if len(normalize_issue_text(partial)) < partial_min_chars:
                    return
                stream_buffer = ""
            if partial[-1] not in {"।", ".", "!", "?"}:
                partial = f"{partial}{'।' if language_code == 'hi-IN' else '.'}"
            await _emit_sentence(partial, reason)

        async def _schedule_partial_flush() -> None:
            await asyncio.sleep(flush_timeout_ms / 1000)
            await _flush_partial_buffer(reason="timeout")

        async def on_stream_chunk(chunk: str) -> None:
            nonlocal stream_buffer, stream_flush_task
            if on_assistant_sentence is None:
                return
            if not chunk:
                return
            async with stream_buffer_lock:
                stream_buffer += chunk
                sentences, stream_buffer = self._extract_completed_sentences(stream_buffer)
            for sentence in sentences:
                cleaned_sentence = sanitize_spoken_text(sentence, max_length=sentence_max_chars)
                if not cleaned_sentence:
                    continue
                await _emit_sentence(cleaned_sentence, reason="punct")
            if stream_flush_task and not stream_flush_task.done():
                stream_flush_task.cancel()
            if stream_buffer.strip():
                stream_flush_task = asyncio.create_task(_schedule_partial_flush())
            else:
                stream_flush_task = None

        use_streaming = self.gemini_service.settings.llm_streaming if llm_streaming_enabled is None else llm_streaming_enabled
        if use_streaming:
            decision = await self.gemini_service.generate_reply_decision_streaming(
                history=history,
                latest_user_text=latest_user_text,
                response_mode=response_mode,
                language_code=language_code,
                response_style=response_style,
                active_issue_type=active_issue_type,
                call_sid=call_sid,
                on_text_chunk=on_stream_chunk if on_assistant_sentence is not None else None,
            )
        else:
            decision = await self.gemini_service.generate_reply_decision(
                history=history,
                latest_user_text=latest_user_text,
                response_mode=response_mode,
                language_code=language_code,
                response_style=response_style,
                active_issue_type=active_issue_type,
                call_sid=call_sid,
            )

        if on_assistant_sentence is not None and not decision.used_fallback:
            if use_streaming:
                if stream_flush_task and not stream_flush_task.done():
                    stream_flush_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await stream_flush_task
                trailing = sanitize_spoken_text(stream_buffer.strip(), max_length=sentence_max_chars)
                if trailing:
                    await _emit_sentence(trailing, reason="trailing")
            else:
                full_text = sanitize_spoken_text(decision.text, max_length=sentence_max_chars * 3)
                if full_text:
                    sentence_parts, remainder = self._extract_completed_sentences(full_text)
                    if remainder:
                        sentence_parts.append(remainder)
                    if not sentence_parts:
                        sentence_parts = [full_text]

                    for raw_sentence in sentence_parts:
                        cleaned_sentence = sanitize_spoken_text(raw_sentence, max_length=sentence_max_chars)
                        if cleaned_sentence:
                            await _emit_sentence(cleaned_sentence, reason="non_stream")

        await self._publish_gemini_decision(call_sid, self._serialize_gemini_decision(decision))
        await self._publish_call_phase(
            call_sid,
            GEMINI_FALLBACK_USED if decision.used_fallback else GEMINI_REPLY_READY,
        )
        return decision.text

    @staticmethod
    def _extract_completed_sentences(buffer: str) -> tuple[list[str], str]:
        if not buffer:
            return [], ""
        ready: list[str] = []
        start = 0
        boundaries = {"।", ".", "?", "!"}
        for index, char in enumerate(buffer):
            if char not in boundaries:
                continue
            sentence = buffer[start : index + 1].strip()
            if sentence:
                ready.append(sentence)
            start = index + 1
        remainder = buffer[start:].strip()
        return ready, remainder

    @staticmethod
    def _serialize_gemini_decision(decision: GeminiReplyDecision) -> dict[str, object]:
        return {
            "source": decision.source,
            "used_fallback": decision.used_fallback,
            "fallback_reason": decision.fallback_reason,
            "provider_success": decision.provider_success,
            "model": decision.model,
            "language_code": decision.language_code,
            "response_mode": decision.response_mode,
            "response_style": decision.response_style,
            "active_issue_type": decision.active_issue_type,
            "text_preview": decision.text[:120],
        }

    def _build_turn_main_points(
        self,
        *,
        call: Call,
        transcript: str,
        detected_language: str | None,
        prompt_language: str,
        selected_language: str | None,
        consent_choice: str,
        issue_state,
        customer_turn_count: int,
        confidence: float,
        confidence_source: str,
        speech_detected: bool,
        transcript_reliable: bool,
        response_style: str,
    ) -> dict[str, object]:
        issue_type = self._resolve_issue_type_for_turn(transcript, issue_state.issue_type)
        symptom = detect_issue_symptom(transcript)
        escalation_requested = detect_escalation_request(transcript)
        goodbye_requested = self._wants_to_end_call(transcript)
        resolution_signal = self._looks_like_issue_resolved(transcript)
        no_issue_signal = self._looks_like_no_issue_statement(transcript)
        capability_query = self._looks_like_capability_query(transcript)
        audio_state = self.audio_quality_service.get_state(call.call_sid)
        if consent_choice == "opt_out":
            primary_intent = "opt_out"
        elif consent_choice == "send_link":
            primary_intent = "send_link"
        elif consent_choice == "callback":
            primary_intent = "callback"
        elif escalation_requested:
            primary_intent = "escalation"
        elif goodbye_requested:
            primary_intent = "goodbye"
        elif no_issue_signal:
            primary_intent = "resolution_closure"
        elif issue_type and symptom and symptom != "unknown":
            primary_intent = "issue_resolution"
        elif looks_like_general_banking_question(transcript) or capability_query:
            primary_intent = "general_banking_query"
        elif issue_type:
            primary_intent = "issue_follow_up"
        elif resolution_signal:
            primary_intent = "resolution_closure"
        elif is_opening_response(transcript) or is_simple_acknowledgement(transcript):
            primary_intent = "opening_ack"
        elif not transcript.strip():
            primary_intent = "unclear"
        else:
            primary_intent = "general_query"

        return {
            "transcript_preview": transcript[:120],
            "business_state": issue_state.business_state,
            "primary_intent": primary_intent,
            "consent_choice": consent_choice,
            "issue_type": issue_type,
            "symptom": symptom,
            "language": prompt_language,
            "detected_language": detected_language,
            "selected_language": selected_language,
            "response_style": response_style,
            "transcript_reliable": transcript_reliable,
            "speech_detected": speech_detected,
            "confidence": round(confidence, 3),
            "confidence_source": confidence_source,
            "customer_turn_count": customer_turn_count,
            "escalation_requested": escalation_requested,
            "goodbye_requested": goodbye_requested,
            "resolution_signal": resolution_signal,
            "no_issue_signal": no_issue_signal,
            "capability_query": capability_query,
            "noisy_call": audio_state.noise_flag,
            "fallback_mode": audio_state.fallback_mode,
        }

    def _resolve_issue_type_for_turn(self, transcript: str, active_issue_type: str | None) -> str | None:
        detected_issue_type = detect_issue_type(transcript)
        if detected_issue_type:
            # Keep specific active issue sticky unless user clearly switches context.
            if (
                active_issue_type
                and active_issue_type not in {"generic_process_help", "document_upload"}
                and detected_issue_type in {"generic_process_help", "document_upload"}
                and not self._looks_like_explicit_issue_switch(transcript)
            ):
                return active_issue_type
            return detected_issue_type

        if not active_issue_type:
            return None

        normalized = normalize_issue_text(transcript)
        if not normalized:
            return active_issue_type
        if self._looks_like_no_issue_statement(transcript):
            return None
        if self._looks_like_call_purpose_question(transcript):
            return None

        if detect_issue_symptom(transcript):
            return active_issue_type
        if is_simple_acknowledgement(transcript) or looks_like_repeated_acknowledgement(transcript):
            return active_issue_type

        continuation_markers = (
            "same issue",
            "same problem",
            "same error",
            "same one",
            "same thing",
            "वही दिक्कत",
            "वही समस्या",
            "वही issue",
            "उसी में",
        )
        if any(marker in normalized for marker in continuation_markers):
            return active_issue_type
        if len(normalized.split()) <= 6:
            return active_issue_type
        return None

    def _build_response_plan(
        self,
        *,
        call: Call,
        transcript: str,
        from_number: str | None,
        prompt_language: str,
        selected_language: str | None,
        consent_choice: str,
        issue_state,
        history: list[dict[str, str]],
        customer_turn_count: int,
        quality_state,
        quality_assessment,
        main_points: dict[str, object],
    ) -> dict[str, object]:
        issue_type = main_points.get("issue_type")
        symptom = main_points.get("symptom")
        route = "gemini_response"
        objective = "Generate the next best spoken reply."
        response_source = "gemini"
        reply_mode = "noisy" if self.audio_quality_service.should_use_short_responses(quality_state) else "normal"
        should_hangup = False
        close_after_resolution = False
        use_gemini = False
        primary_intent = str(main_points.get("primary_intent") or "")

        if not quality_assessment.transcript_reliable:
            route = "unclear_audio"
            objective = "Ask the caller to repeat or switch to noisy-call fallback guidance."
            response_source = "system"
        elif customer_turn_count <= 1 and consent_choice == "granted":
            route = "post_greeting_issue_capture"
            objective = "Move from greeting consent into issue capture."
            response_source = "prompt"
        elif customer_turn_count <= 1 and consent_choice == "callback":
            route = "callback_close"
            objective = "Acknowledge callback request and end the call."
            response_source = "prompt"
            should_hangup = True
        elif selected_language and call.language != selected_language:
            route = "language_switch"
            objective = "Acknowledge the requested language and continue issue capture."
            response_source = "prompt"
        elif self._is_opt_out_request(transcript) and from_number:
            route = "opt_out_close"
            objective = "Honor opt-out request and end the call."
            response_source = "prompt"
            should_hangup = True
        elif self._looks_like_application_not_started(transcript):
            route = "application_not_started_close"
            objective = "Close the call when the customer says no application was started."
            response_source = "prompt"
            should_hangup = True
        elif issue_state.post_resolution_check_pending:
            resolution_choice = detect_resolution_choice(transcript)
            if primary_intent == "general_banking_query":
                route = "general_capabilities"
                objective = "Answer product or service information queries with concise options."
                response_source = "prompt"
            elif resolution_choice == "no_more_help" or self._looks_like_call_termination_intent(transcript):
                route = "resolution_complete_close"
                objective = "Confirm no more help is needed and end the call."
                response_source = "prompt"
                should_hangup = True
            elif resolution_choice == "more_help" and len(normalize_issue_text(transcript).split()) <= 5:
                route = "new_issue_capture"
                objective = "Start collecting the next issue after resolving the previous one."
                response_source = "prompt"
            elif issue_state.post_resolution_prompt_count >= self.max_post_resolution_prompts:
                route = "resolution_complete_close"
                objective = "Close politely after a repeated unresolved closure check."
                response_source = "prompt"
                should_hangup = True
            else:
                route = "resolution_follow_up"
                objective = "Ask one short closure check and avoid reopening troubleshooting."
                response_source = "prompt"
        elif self._looks_like_issue_resolved(transcript):
            route = "resolution_follow_up"
            objective = "Confirm the issue is resolved and check whether more help is needed."
            response_source = "prompt"
            close_after_resolution = self._looks_like_resolution_closure(transcript) or self._looks_like_call_termination_intent(transcript)
        elif detect_escalation_request(transcript):
            route = "handoff_close"
            objective = "Acknowledge escalation request and end the automated turn."
            response_source = "prompt"
            should_hangup = True
        elif self._wants_to_end_call(transcript):
            route = "goodbye_close"
            objective = "Close the call politely."
            response_source = "prompt"
            should_hangup = True
        elif (
            is_simple_acknowledgement(transcript)
            or looks_like_repeated_acknowledgement(transcript)
            or is_opening_response(transcript)
        ):
            route = "short_ack_reprompt"
            objective = "Acknowledge briefly and ask the customer for the exact blocked step."
            response_source = "prompt"
            use_gemini = False
        elif looks_like_repair_request(transcript):
            route = "repair_guidance"
            objective = "Repair the conversation by narrowing the issue with a short clarifying prompt."
            response_source = "prompt"
        elif primary_intent == "general_banking_query":
            route = "general_capabilities"
            objective = "Answer product or service information queries with concise options."
            response_source = "prompt"
            use_gemini = False
        elif primary_intent == "general_query" and self._looks_like_capability_query(transcript):
            route = "general_capabilities"
            objective = "Answer product capability query directly instead of generic fallback."
            response_source = "prompt"
            use_gemini = False
        elif issue_state.follow_up_count >= 3 and self._looks_like_no_issue_statement(transcript):
            route = "resolution_follow_up"
            objective = "Break issue-capture loops when caller says no issue remains."
            response_source = "prompt"
            close_after_resolution = True
        elif issue_type:
            if symptom and symptom != "unknown":
                route = "rule_guidance"
                objective = "Use deterministic guidance for the detected issue and symptom."
                response_source = "rule"
                use_gemini = self._should_fallback_to_gemini_for_guidance(
                    history,
                    build_issue_resolution_reply(issue_type, symptom, prompt_language),
                )
                if use_gemini:
                    response_source = "gemini"
            elif symptom == "unknown":
                route = "guided_clarify"
                objective = "Use Gemini to clarify a partially known issue."
                response_source = "gemini"
                use_gemini = True
            else:
                route = "issue_follow_up"
                objective = "Ask a targeted follow-up question for the detected issue."
                response_source = "prompt"
                use_gemini = self._should_fallback_to_gemini_for_guidance(
                    history,
                    build_issue_follow_up_question(issue_type, prompt_language),
                )
                if use_gemini:
                    response_source = "gemini"
        elif (
            issue_type
            and issue_state.issue_type
            and len(transcript.split()) <= 4
            and not is_simple_acknowledgement(transcript)
            and not self._looks_like_call_purpose_question(transcript)
        ):
            route = "guided_followup"
            objective = "Use Gemini to continue a guided issue follow-up."
            response_source = "gemini"
            use_gemini = True
        elif len([item for item in history if item["speaker"] == "customer"]) > self.max_turns:
            route = "max_turns_handoff"
            objective = "End the call because the conversation exceeded the configured turn limit."
            response_source = "prompt"
            should_hangup = True
        elif quality_state.fallback_mode:
            noisy_intent = self.audio_quality_service.normalize_noisy_intent(transcript)
            route = "noisy_intent" if noisy_intent else "noisy_fallback"
            objective = "Use noisy-call fallback handling."
            response_source = "fallback"

        return {
            "route": route,
            "objective": objective,
            "business_state": issue_state.business_state,
            "response_source": response_source,
            "reply_mode": reply_mode,
            "should_hangup": should_hangup,
            "use_gemini": use_gemini,
            "close_after_resolution": close_after_resolution,
            "issue_type": issue_type,
            "symptom": symptom,
            "language": prompt_language,
            "response_style": main_points.get("response_style"),
        }

    @staticmethod
    def _prompt_language(call: Call) -> str:
        return "hi-IN"

    @staticmethod
    def _looks_like_explicit_issue_switch(text: str) -> bool:
        normalized = normalize_issue_text(text)
        if not normalized:
            return False
        switch_markers = (
            "new issue",
            "another issue",
            "different issue",
            "ab doosra",
            "ab alag",
            "अब दूसरा",
            "अब अलग",
            "instead",
        )
        return any(marker in normalized for marker in switch_markers)

    @staticmethod
    def _apply_voice_guardrail(text: str, *, language_code: str, route: str) -> str:
        if normalize_language(language_code) != "hi-IN":
            return text
        if route not in {"gemini_response", "general_capabilities"}:
            return text

        cleaned = sanitize_spoken_text(text, max_length=140).strip()
        if not cleaned:
            return text

        sentence_parts = [part.strip() for part in re.split(r"[।.!?]+", cleaned) if part.strip()]
        if not sentence_parts:
            return cleaned
        first_sentence = sentence_parts[0]
        if not first_sentence.endswith("।"):
            first_sentence = f"{first_sentence}।"
        return first_sentence
