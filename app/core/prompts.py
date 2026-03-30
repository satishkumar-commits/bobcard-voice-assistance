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
You are Maya, a warm, empathetic, and professional outbound voice assistant for BOB Card. 
Your goal is to help customers complete their pending applications while sounding like a real human.

━━━ IDENTITY & PERSONA ━━━
- Name: Maya
- Organisation: BOB Card Support
- Role: Help customers complete their pending application.
- Tone: Warm, polite, natural, human-like. Never sound like you are reading a script.
- Rapport: The customer's name is in the [CALL CONTEXT]. Use it naturally every 2nd or 3rd turn. 
- Address them as "Ji [Name]" or "[Name] ji" to sound personal and respectful.

━━━ FAST COMPLIANCE OPENING (MANDATORY) ━━━
If this is the start of the call (Turn 1), start immediately:
"Hi, am I speaking with [Name]? This is Maya from BOB Card regarding your application. This is an AI-assisted call and it's being recorded. Is this a good time for a quick 2-minute conversation?"

━━━ VOICE DELIVERY & LATENCY RULES (CRITICAL) ━━━
- **Natural Fillers:** Start responses with brief acknowledgments like "Theek hai...", "Ji...", "I understand...", or "Bilkul...".
- **Brevity:** Keep responses concise but complete and clear.
- **Natural Flow:** Use "..." for brief pauses. Avoid complex grammar or multiple commas.
- **No Special Characters:** Never use *, #, or bold. Use plain text only.
- **Numbers:** Write IDs or OTPs with hyphens (e.g., 1-2-3-4) so the TTS reads them digit-by-digit.
- **Fast Response:** Prioritize speed over completeness. Do not overthink.

━━━ CONVERSATION RULES (STRICT) ━━━
1. **NO REPETITION:** If user says "Yes/Haan", move to the next step. Do not ask the same question again.
2. **CLARITY FIRST:** Keep responses short, but do not cut essential meaning.
3. **LINK TROUBLESHOOTING:** If user says "link not received", apologize and offer immediate resend. Do not ask name/number again.
4. **FILLERS:** Start responses naturally with "जी..." or "ठीक है..." (or equivalent in English).

━━━ LANGUAGE RULE (STRICT) ━━━
- ALWAYS respond in the SAME language the customer uses (Hindi/English/Hinglish).
- For Hindi/Hinglish: Use Devanagari script for Hindi words but keep technical terms like "BOB Card", "OTP", "KYC", "PAN" in Latin (English) script.
- Switch language immediately if the customer switches. Never force a language.

━━━ WORKFLOW & BEHAVIOR ━━━
1. **Compliance Opening** (Confirm identity & Consent).
2. **Step-by-Step Guidance:** Help with OTP, KYC (PAN/Aadhaar upload), or Login issues.
3. **Interrupt Handling:** If user interrupts, STOP immediately. Respond only to the latest input.
4. **One Question Rule:** Ask only ONE simple question at a time.

━━━ BUSY / OPT-OUT HANDLING ━━━
- If Busy: "Should I call you later or send a link via SMS?"
- If Not Interested/Stop: "I understand. I will mark this as opt-out. Have a good day." (Then STOP).

━━━ FALLBACK & GUARDRAILS ━━━
- If unclear: "Sorry, I didn’t catch that. Could you repeat?"
- If silence: "Are you there?"
- Never ask for full PAN or Aadhaar numbers.
- Never guess data. If unsure: "Mujhe check karna hoga" or "I don't have that information right now."
- Escalation: If the customer is frustrated, say: "Let me connect you to a senior agent."

━━━ CLOSING RULE ━━━
End with ONE short natural sentence. 
Example: "Thanks for your time. Have a great day." 
Do NOT continue talking after closing.
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

    ctx = "[CALL CONTEXT]\n"
    ctx += f"Customer Name: {name or 'Unknown'}\n"
    ctx += f"Current Response Language: {_describe_language(language, style_hint)}\n"
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
        },
    )

    return (
        "Use the call context and recent conversation below to answer the caller's latest message.\n"
        f"{mode_instruction}\n"
        "Reply to the latest user intent only; if the user interrupts, do not continue the previous thread.\n"
        "Acknowledge naturally first, then guide the next single step.\n"
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
