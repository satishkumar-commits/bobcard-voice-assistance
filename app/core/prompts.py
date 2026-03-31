from app.core.conversation_prompts import (
    build_empty_input_reply,
    build_first_unclear_reply,
    build_human_handoff_reply,
    build_noisy_fallback_reply,
    build_noisy_mode_acknowledgement,
    build_opening_greeting,
    build_second_unclear_reply,
)



SYSTEM_PROMPT = """
You are Maya, a warm and concise BOB Card outbound voice assistant.
Primary goal: complete pending BOBCards journey steps with fast turn-taking and deterministic flow.

Identity:
- Name: Maya
- Organization: BOB Card Support
- Tone: respectful, natural, short spoken sentences, never robotic

Critical behavior:
- Keep the opening very short (2-4 seconds if possible).
- First-turn opener style: identity check + purpose + quick consent in one compact line.
- Ask only one question at a time.
- If user interrupts, respond only to latest user input. Never continue the previous thread.
- If user already affirmed (yes/haan/जी/speaking), move forward. Do not repeat the same yes/no question.
- Treat short acknowledgements like hello/हलो/हाँ जी/जी/yes ji/बोलिए as meaningful when context supports them.
- Keep replies concise for TTS latency. Prefer one or two short sentences.

Deterministic flow-first:
- Prioritize flow/state instructions from call context over free-form explanations.
- Do not fabricate eligibility, approval, backend actions, or system status.
- If backend status is unknown, say so briefly and guide next valid step.

Supported journey states:
- opening
- consent_check
- language_selection
- identity_verification
- context_setting
- issue_capture
- personal_details_validation
- age_eligibility_check
- aadhaar_verification
- address_capture
- cibil_fetch
- offer_eligibility
- card_selection
- e_consent
- vkyc_pending
- vkyc_complete
- application_complete
- terminal_rejection
- resume_journey

Language policy:
- Match caller language each turn (Hindi/English/Hinglish context).
- For Hindi/Hinglish replies: use Devanagari for Hindi words.
- Keep technical tokens in Latin script when needed: BOB Card, OTP, PAN, Aadhaar, SMS, KYC.

Guardrails:
- Never ask for full PAN or Aadhaar numbers.
- Never claim a transfer, resend, approval, or completion unless it is explicitly confirmed in context.
- For unclear audio, ask a short repeat prompt.
- Close with one short sentence when call is complete.
""".strip()

BANKING_SYSTEM_PROMPT = SYSTEM_PROMPT

INITIAL_GREETING = build_opening_greeting(language="en-IN")
EMPTY_INPUT_REPLY = build_empty_input_reply(language="en-IN")
HUMAN_HANDOFF_REPLY = build_human_handoff_reply(language="en-IN")
FIRST_UNCLEAR_REPLY = build_first_unclear_reply(language="en-IN")
SECOND_UNCLEAR_REPLY = build_second_unclear_reply(language="en-IN")
NOISY_FALLBACK_REPLY = build_noisy_fallback_reply(language="en-IN")
NOISY_MODE_ACKNOWLEDGEMENT = build_noisy_mode_acknowledgement(language="en-IN")


def build_user_context(
    name: str,
    language: str,
    session_data: dict | None = None,
) -> str:
    """Inject per-call context into each Gemini request."""
    session_data = session_data or {}
    turns_count = session_data.get("turns_count", 0)
    notes = session_data.get("notes", "")
    authenticated = session_data.get("authenticated", True)
    style_hint = session_data.get("style_hint", "")
    current_phase = session_data.get("current_phase", "")
    pending_step = session_data.get("pending_step", "")
    call_sid = session_data.get("call_sid", "")

    ctx = "[CALL CONTEXT]\n"
    if call_sid:
        ctx += f"Call SID: {call_sid}\n"
    ctx += f"Customer Name: {name or 'Unknown'}\n"
    ctx += f"Current Response Language: {_describe_language(language, style_hint)}\n"
    if current_phase:
        ctx += f"Current Phase: {current_phase}\n"
    if pending_step:
        ctx += f"Pending Step: {pending_step}\n"
    if style_hint:
        ctx += f"Style Hint: {style_hint}\n"
    ctx += f"Registration Issue: {notes if notes else 'Customer faced an issue during BOB Card registration'}\n"
    ctx += f"Turn: {turns_count + 1}\n"
    ctx += f"Identity Confirmed: {'Yes' if authenticated else 'No — confirm identity first before proceeding'}\n"

    return ctx

def build_conversation_prompt(
    history: list[dict[str, str]],
    latest_user_text: str,
    response_mode: str = "normal",
    preferred_language: str = "en-IN",
    response_style: str = "default",
    customer_name: str = "",
    issue_notes: str = "",
    authenticated: bool = True,
    current_phase: str = "",
    pending_step: str = "",
    call_sid: str = "",
) -> str:
    recent_lines: list[str] = []
    for item in history[-6:]:
        speaker = item["speaker"].capitalize()
        recent_lines.append(f"{speaker}: {item['text']}")

    recent_lines.append(f"Customer: {latest_user_text}")
    history_block = "\n".join(recent_lines)

    mode_instruction = (
        "The line seems noisy, so keep the reply very short, acknowledge briefly, and ask only one simple next-step question."
        if response_mode == "noisy"
        else "Keep the reply short and natural for live voice playback while still solving the caller's exact problem."
    )
    style_hint = _style_hint(preferred_language, response_style)
    context_block = build_user_context(
        name=customer_name,
        language=preferred_language,
        session_data={
            "turns_count": len(history),
            "notes": issue_notes,
            "authenticated": authenticated,
            "style_hint": style_hint,
            "current_phase": current_phase,
            "pending_step": pending_step,
            "call_sid": call_sid,
        },
    )

    return (
        "Use the call context and recent conversation below to answer the caller's latest message.\n"
        f"{mode_instruction}\n"
        "Reply to the latest user intent only; if interrupted, do not continue the previous thread.\n"
        "If the latest turn is a short acknowledgement in a valid stage, treat it as meaningful and move flow forward.\n"
        "If the user already affirmed identity/consent, do not ask the same yes/no question again.\n"
        "Acknowledge naturally first, then guide the next single deterministic step.\n"
        "Ask only one question at a time.\n"
        "Use only factual details available in call context; never fabricate offers, benefits, or status.\n"
        "Follow the caller's active language for this turn.\n"
        f"{style_hint}\n"
        "Keep the brand text exactly as 'BOB Card'.\n"
        "If the customer asks for escalation or callback, offer that naturally, but do not claim you already transferred the call or completed an internal action.\n"
        "Do not use markdown, labels, bullets, numbering, or long explanations.\n\n"
        f"{context_block}\n\n"
        "[RECENT CONVERSATION]\n"
        f"{history_block}"
    )


def _style_hint(preferred_language: str, response_style: str) -> str:
    if preferred_language == "hi-IN":
        if response_style == "hinglish":
            return (
                "For Hindi/Hinglish callers, reply strictly in Devanagari Hindi only. "
                "Do not use Roman Hindi. Keep it short and natural. "
                "Use Latin script only when required for: BOB Card, OTP, PAN, Aadhaar, SMS."
            )
        return (
            "Reply in clear Devanagari Hindi only. "
            "Do not use Roman Hindi. Keep it short and natural. "
            "Use Latin script only when required for: BOB Card, OTP, PAN, Aadhaar, SMS."
        )
    return "Reply in clear English."


def _describe_language(language: str, style_hint: str) -> str:
    if language == "hi-IN" and style_hint:
        return f"hi-IN/Hinglish caller context. {style_hint} Switch immediately if caller asks to change language."
    if language == "hi-IN":
        return (
            "hi-IN/Hinglish caller context. Reply in Devanagari Hindi only; no Roman Hindi. "
            "Use Latin script only when required for: BOB Card, OTP, PAN, Aadhaar, SMS. "
            "If caller switches language, switch immediately."
        )
    if language == "en-IN":
        return "en-IN caller context. Reply in clear English. If caller switches language, switch immediately."
    return f"{language}. If the customer asks to switch, switch immediately."
