import logging
import json
import re
from dataclasses import dataclass
from time import perf_counter
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.core.config import Settings
from app.core.conversation_prompts import (
    build_empty_input_reply,
    build_general_capabilities_reply,
    build_human_handoff_reply,
    build_issue_capture_prompt,
    normalize_language,
)
from app.core.issue_guidance import (
    build_issue_follow_up_question,
    build_issue_help_reply,
    build_issue_resolution_reply,
    detect_issue_symptom,
    detect_issue_type,
)
from app.core.prompts import BANKING_SYSTEM_PROMPT, HUMAN_HANDOFF_REPLY, build_conversation_prompt, build_state_aware_prompt
from app.services.realtime_service import emit_latency_event
from app.utils.helpers import contains_devanagari, contains_latin, sanitize_spoken_text, utc_now_iso


logger = logging.getLogger(__name__)

_LEADING_LANGUAGE_LABEL_PATTERN = re.compile(
    r"^\s*(?:\((?:hindi|english|hinglish)\)|(?:hindi|english|hinglish)\s*[:\-])\s*",
    re.IGNORECASE,
)


@dataclass
class GeminiReplyDecision:
    text: str
    source: str
    used_fallback: bool
    fallback_reason: str | None
    provider_success: bool
    model: str
    language_code: str
    response_mode: str
    response_style: str
    active_issue_type: str | None = None


class GeminiService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def generate_reply(
        self,
        history: list[dict[str, str]],
        latest_user_text: str,
        response_mode: str = "normal",
        language_code: str = "en-IN",
        response_style: str = "default",
        active_issue_type: str | None = None,
        call_sid: str = "",
        current_phase: str = "",
        pending_step: str = "",
    ) -> str:
        decision = await self.generate_reply_decision(
            history=history,
            latest_user_text=latest_user_text,
            response_mode=response_mode,
            language_code=language_code,
            response_style=response_style,
            active_issue_type=active_issue_type,
            call_sid=call_sid,
            current_phase=current_phase,
            pending_step=pending_step,
        )
        return decision.text

    async def generate_reply_decision(
        self,
        history: list[dict[str, str]],
        latest_user_text: str,
        response_mode: str = "normal",
        language_code: str = "en-IN",
        response_style: str = "default",
        active_issue_type: str | None = None,
        call_sid: str = "",
        current_phase: str = "",
        pending_step: str = "",
    ) -> GeminiReplyDecision:
        preferred_language = normalize_language(language_code)
        payload = self._build_generate_payload(
            history=history,
            latest_user_text=latest_user_text,
            response_mode=response_mode,
            preferred_language=preferred_language,
            response_style=response_style,
            active_issue_type=active_issue_type,
            current_phase=current_phase,
            pending_step=pending_step,
        )
        headers = {"x-goog-api-key": self.settings.gemini_api_key}
        request_sent_at = utc_now_iso()

        try:
            started_at = perf_counter()
            async with httpx.AsyncClient(timeout=18.0) as client:
                response = await client.post(
                    f"{self.settings.gemini_base_url}/models/{self.settings.gemini_model}:generateContent",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
            response_received_at = utc_now_iso()
            latency_ms = int((perf_counter() - started_at) * 1000)
        except httpx.HTTPError as exc:
            logger.exception("Gemini request failed: %s", exc)
            return self._fallback_decision(
                reason="http_error",
                latest_user_text=latest_user_text,
                language_code=preferred_language,
                response_mode=response_mode,
                response_style=response_style,
                provider_success=False,
                active_issue_type=active_issue_type,
            )

        prompt_tokens, output_tokens, total_tokens = self._extract_usage_tokens(data)

        try:
            parts = data["candidates"][0]["content"]["parts"]
            text = " ".join(part.get("text", "") for part in parts).strip()
        except (KeyError, IndexError, TypeError):
            logger.warning("Gemini returned an unexpected payload: %s", data)
            self._emit_gemini_latency_event(
                call_sid=call_sid,
                request_sent_at=request_sent_at,
                response_received_at=response_received_at,
                latency_ms=latency_ms,
                language=preferred_language,
                prompt_tokens=prompt_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                output_words=None,
            )
            return self._fallback_decision(
                reason="invalid_payload",
                latest_user_text=latest_user_text,
                language_code=preferred_language,
                response_mode=response_mode,
                response_style=response_style,
                provider_success=True,
                active_issue_type=active_issue_type,
            )

        self._emit_gemini_latency_event(
            call_sid=call_sid,
            request_sent_at=request_sent_at,
            response_received_at=response_received_at,
            latency_ms=latency_ms,
            language=preferred_language,
            prompt_tokens=prompt_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            output_words=self._count_words(text),
        )

        return self._normalize_reply(
            text,
            preferred_language,
            latest_user_text,
            response_mode,
            response_style,
            active_issue_type=active_issue_type,
        )

    async def generate_reply_decision_streaming(
        self,
        history: list[dict[str, str]],
        latest_user_text: str,
        response_mode: str = "normal",
        language_code: str = "en-IN",
        response_style: str = "default",
        active_issue_type: str | None = None,
        call_sid: str = "",
        current_phase: str = "",
        pending_step: str = "",
        on_text_chunk: Callable[[str], Awaitable[None]] | None = None,
    ) -> GeminiReplyDecision:
        preferred_language = normalize_language(language_code)
        payload = self._build_generate_payload(
            history=history,
            latest_user_text=latest_user_text,
            response_mode=response_mode,
            preferred_language=preferred_language,
            response_style=response_style,
            active_issue_type=active_issue_type,
            current_phase=current_phase,
            pending_step=pending_step,
        )
        headers = {"x-goog-api-key": self.settings.gemini_api_key}
        request_sent_at = utc_now_iso()
        started_at = perf_counter()
        prompt_tokens: int | None = None
        output_tokens: int | None = None
        total_tokens: int | None = None
        previous_text = ""
        chunk_parts: list[str] = []

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                async with client.stream(
                    "POST",
                    f"{self.settings.gemini_base_url}/models/{self.settings.gemini_model}:streamGenerateContent?alt=sse",
                    headers=headers,
                    json=payload,
                ) as response:
                    response.raise_for_status()
                    async for raw_line in response.aiter_lines():
                        line = (raw_line or "").strip()
                        if not line or not line.startswith("data:"):
                            continue
                        data_text = line[5:].strip()
                        if not data_text or data_text == "[DONE]":
                            continue
                        try:
                            event = json.loads(data_text)
                        except json.JSONDecodeError:
                            continue

                        event_prompt_tokens, event_output_tokens, event_total_tokens = self._extract_usage_tokens(event)
                        if event_prompt_tokens is not None:
                            prompt_tokens = event_prompt_tokens
                        if event_output_tokens is not None:
                            output_tokens = event_output_tokens
                        if event_total_tokens is not None:
                            total_tokens = event_total_tokens

                        event_text = self._extract_text_from_event(event)
                        if not event_text:
                            continue

                        if event_text.startswith(previous_text):
                            delta = event_text[len(previous_text) :]
                            previous_text = event_text
                        else:
                            delta = event_text
                            previous_text += event_text

                        if not delta:
                            continue

                        chunk_parts.append(delta)
                        if on_text_chunk is not None:
                            await on_text_chunk(delta)

            response_received_at = utc_now_iso()
            latency_ms = int((perf_counter() - started_at) * 1000)
        except httpx.HTTPError as exc:
            logger.exception("Gemini streaming request failed: %s", exc)
            return self._fallback_decision(
                reason="http_error",
                latest_user_text=latest_user_text,
                language_code=preferred_language,
                response_mode=response_mode,
                response_style=response_style,
                provider_success=False,
                active_issue_type=active_issue_type,
            )

        text = "".join(chunk_parts).strip()
        self._emit_gemini_latency_event(
            call_sid=call_sid,
            request_sent_at=request_sent_at,
            response_received_at=response_received_at,
            latency_ms=latency_ms,
            language=preferred_language,
            prompt_tokens=prompt_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            output_words=self._count_words(text),
        )

        return self._normalize_reply(
            text,
            preferred_language,
            latest_user_text,
            response_mode,
            response_style,
            active_issue_type=active_issue_type,
        )

    @staticmethod
    def _extract_usage_tokens(data: dict[str, Any]) -> tuple[int | None, int | None, int | None]:
        usage = data.get("usageMetadata")
        if not isinstance(usage, dict):
            return None, None, None

        prompt_tokens = GeminiService._to_int(usage.get("promptTokenCount"))
        output_tokens = GeminiService._to_int(
            usage.get("candidatesTokenCount") or usage.get("candidateTokenCount") or usage.get("outputTokenCount")
        )
        total_tokens = GeminiService._to_int(usage.get("totalTokenCount"))
        return prompt_tokens, output_tokens, total_tokens

    @staticmethod
    def _to_int(value: Any) -> int | None:
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
        return None

    @staticmethod
    def _count_words(text: str) -> int | None:
        cleaned = (text or "").strip()
        if not cleaned:
            return None
        return len(re.findall(r"\S+", cleaned))

    @staticmethod
    def _extract_text_from_event(data: dict[str, Any]) -> str:
        try:
            parts = data["candidates"][0]["content"]["parts"]
            return " ".join(part.get("text", "") for part in parts).strip()
        except (KeyError, IndexError, TypeError, AttributeError):
            return ""

    @staticmethod
    def _build_generate_payload(
        *,
        history: list[dict[str, str]],
        latest_user_text: str,
        response_mode: str,
        preferred_language: str,
        response_style: str,
        active_issue_type: str | None,
        current_phase: str,
        pending_step: str,
    ) -> dict[str, Any]:
        prompt_text = (
            build_state_aware_prompt(
                current_phase=current_phase,
                history=history,
                latest_user_text=latest_user_text,
                response_mode=response_mode,
                preferred_language=preferred_language,
                response_style=response_style,
                issue_notes=(active_issue_type or "").replace("_", " "),
                pending_step=pending_step,
            )
            if current_phase
            else build_conversation_prompt(
                history=history,
                latest_user_text=latest_user_text,
                response_mode=response_mode,
                preferred_language=preferred_language,
                response_style=response_style,
                issue_notes=(active_issue_type or "").replace("_", " "),
            )
        )
        return {
            "system_instruction": {
                "parts": [{"text": BANKING_SYSTEM_PROMPT}],
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": prompt_text
                        }
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0.05,
                "maxOutputTokens": 96,
            },
        }

    @staticmethod
    def _emit_gemini_latency_event(
        *,
        call_sid: str,
        request_sent_at: str,
        response_received_at: str,
        latency_ms: int,
        language: str,
        prompt_tokens: int | None,
        output_tokens: int | None,
        total_tokens: int | None,
        output_words: int | None,
    ) -> None:
        logger.info(
            (
                "Latency step=gemini call=%s request_sent_at=%s response_received_at=%s latency_ms=%s "
                "language=%s prompt_tokens=%s output_tokens=%s output_words=%s total_tokens=%s"
            ),
            call_sid or "unknown",
            request_sent_at,
            response_received_at,
            latency_ms,
            language,
            prompt_tokens if prompt_tokens is not None else "-",
            output_tokens if output_tokens is not None else "-",
            output_words if output_words is not None else "-",
            total_tokens if total_tokens is not None else "-",
        )
        emit_latency_event(
            {
                "step": "gemini",
                "call_sid": call_sid,
                "request_sent_at": request_sent_at,
                "response_received_at": response_received_at,
                "latency_ms": latency_ms,
                "language": language,
                "prompt_tokens": prompt_tokens,
                "output_tokens": output_tokens,
                "output_words": output_words,
                "total_tokens": total_tokens,
            }
        )

    @staticmethod
    def _normalize_reply(
        text: str,
        language_code: str,
        latest_user_text: str,
        response_mode: str,
        response_style: str,
        active_issue_type: str | None = None,
    ) -> GeminiReplyDecision:
        cleaned = sanitize_spoken_text(GeminiService._strip_language_labels(text or ""))
        normalized = cleaned.lower().strip(" .,!?:;")
        weak_replies = {
            "sorry",
            "i am sorry",
            "maaf kijiye",
            "mujhe afsos",
            "afsos hai",
            HUMAN_HANDOFF_REPLY.lower(),
        }

        if len(cleaned.split()) < 4 or normalized in weak_replies:
            return GeminiService._fallback_decision(
                reason="weak_reply",
                latest_user_text=latest_user_text,
                language_code=language_code,
                response_mode=response_mode,
                response_style=response_style,
                provider_success=True,
                active_issue_type=active_issue_type,
            )

        disallowed_transfer_phrases = (
            "connect kar deti hoon",
            "connect kar deta hoon",
            "connect you to a human agent",
            "transfer you to a human agent",
            "human agent se connect",
        )
        if any(phrase in normalized for phrase in disallowed_transfer_phrases):
            return GeminiService._fallback_decision(
                reason="disallowed_transfer",
                latest_user_text=latest_user_text,
                language_code=language_code,
                response_mode=response_mode,
                response_style=response_style,
                provider_success=True,
                active_issue_type=active_issue_type,
            )

        weak_generic_phrases = (
            "पूरी जानकारी नहीं",
            "बाद में कॉल",
            "try again later",
            "callback can be arranged",
            "human agent can follow up later",
        )
        if any(phrase in normalized for phrase in weak_generic_phrases):
            return GeminiService._fallback_decision(
                reason="weak_generic",
                latest_user_text=latest_user_text,
                language_code=language_code,
                response_mode=response_mode,
                response_style=response_style,
                provider_success=True,
                active_issue_type=active_issue_type,
            )

        if GeminiService._looks_like_issue_capture_prompt(cleaned):
            return GeminiService._fallback_decision(
                reason="issue_capture_loop",
                latest_user_text=latest_user_text,
                language_code=language_code,
                response_mode=response_mode,
                response_style=response_style,
                provider_success=True,
                active_issue_type=active_issue_type,
            )

        if language_code == "hi-IN" and (not contains_devanagari(cleaned) or contains_latin(cleaned)):
            return GeminiService._fallback_decision(
                reason="off_language_hi",
                latest_user_text=latest_user_text,
                language_code=language_code,
                response_mode=response_mode,
                response_style=response_style,
                provider_success=True,
                active_issue_type=active_issue_type,
            )

        if language_code == "en-IN" and contains_devanagari(cleaned):
            return GeminiService._fallback_decision(
                reason="off_language_en",
                latest_user_text=latest_user_text,
                language_code=language_code,
                response_mode=response_mode,
                response_style=response_style,
                provider_success=True,
                active_issue_type=active_issue_type,
            )

        return GeminiReplyDecision(
            text=cleaned,
            source="gemini",
            used_fallback=False,
            fallback_reason=None,
            provider_success=True,
            model="gemini",
            language_code=language_code,
            response_mode=response_mode,
            response_style=response_style,
            active_issue_type=active_issue_type,
        )

    @staticmethod
    def _strip_language_labels(text: str) -> str:
        cleaned = text or ""
        while True:
            stripped = _LEADING_LANGUAGE_LABEL_PATTERN.sub("", cleaned, count=1)
            if stripped == cleaned:
                break
            cleaned = stripped
        return cleaned.strip()

    @staticmethod
    def _issue_aware_fallback(
        latest_user_text: str,
        language_code: str,
        response_style: str = "default",
        active_issue_type: str | None = None,
    ) -> str:
        issue_type = detect_issue_type(latest_user_text) or active_issue_type
        if issue_type:
            symptom = detect_issue_symptom(latest_user_text)
            if symptom and symptom != "unknown":
                return build_issue_resolution_reply(issue_type, symptom, language_code)
            if issue_type == "generic_process_help" or GeminiService._looks_like_guidance_request(latest_user_text):
                return build_issue_help_reply(issue_type, language_code)
            return build_issue_follow_up_question(issue_type, language_code)
        if GeminiService._looks_like_general_banking_question(latest_user_text):
            return build_general_capabilities_reply(language_code, response_style=response_style)
        if latest_user_text.strip():
            return build_issue_capture_prompt(language_code)
        return build_empty_input_reply(language_code)

    @staticmethod
    def _fallback_decision(
        reason: str,
        latest_user_text: str,
        language_code: str,
        response_mode: str,
        response_style: str = "default",
        provider_success: bool = False,
        active_issue_type: str | None = None,
    ) -> GeminiReplyDecision:
        fallback_text = GeminiService._issue_aware_fallback(
            latest_user_text,
            language_code,
            response_style,
            active_issue_type=active_issue_type,
        )
        return GeminiReplyDecision(
            text=fallback_text,
            source="fallback",
            used_fallback=True,
            fallback_reason=reason,
            provider_success=provider_success,
            model="fallback",
            language_code=language_code,
            response_mode=response_mode,
            response_style=response_style,
            active_issue_type=active_issue_type,
        )

    @staticmethod
    def _looks_like_general_banking_question(text: str) -> bool:
        normalized = (text or "").lower()
        question_markers = (
            "what",
            "which",
            "how",
            "services",
            "service",
            "solution",
            "solutions",
            "provide",
            "available",
            "offer",
            "benefit",
            "benefits",
            "facility",
            "facilities",
            "banking solution",
            "banking solutions",
            "credit card service",
            "credit card services",
            "what can you do",
            "how can you help",
            "कैसी सेवा",
            "कौन सी सेवा",
            "क्या सेवा",
            "क्या सुविधा",
            "बैंकिंग सोल्यूशन",
            "सर्विस",
            "सोल्यूशन",
            "प्रोवाइड",
            "क्या ऑफर",
            "कैसे मदद",
            "क्या मदद",
        )
        return any(marker in normalized for marker in question_markers)

    @staticmethod
    def _looks_like_issue_capture_prompt(text: str) -> bool:
        normalized = (text or "").lower()
        prompt_markers = (
            "कहाँ अटके हैं",
            "कहाँ अटके",
            "अभी सिर्फ बताइए",
            "जैसे आधार",
            "step by step help",
            "where you are stuck",
            "tell me where you are stuck",
        )
        return any(marker in normalized for marker in prompt_markers)

    @staticmethod
    def _looks_like_guidance_request(text: str) -> bool:
        normalized = (text or "").lower()
        markers = (
            "कैसे",
            "आगे",
            "बताओ",
            "बताइए आगे",
            "क्या करूँ",
            "क्या करु",
            "अब क्या",
            "how do i",
            "how to",
            "what next",
            "now what",
            "guide me",
            "help me continue",
        )
        return any(marker in normalized for marker in markers)
