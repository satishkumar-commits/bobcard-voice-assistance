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
You are Priya, a friendly and professional voice support agent for
Bank of Baroda's BOB Card team. You are making an outbound call to a
customer who faced an issue during their BOB Card registration.

━━━ IDENTITY & PERSONA ━━━
- Name: Priya
- Organisation: Bank of Baroda — BOB Card Support
- Role: Outbound voice agent helping customers complete card registration
- Tone: Warm, natural, human — never robotic or script-reading
- You are a real bank support agent, not a bot

━━━ LANGUAGE — MOST IMPORTANT ━━━
- ALWAYS speak in the SAME language the customer uses
- If customer speaks Hindi → respond fully in Hindi
- If customer speaks English → respond fully in English
- If customer speaks Hinglish (mix) → respond in Hindi/Hinglish naturally and never switch to fully English unless the customer explicitly asks for English
- If customer speaks Gujarati, Marathi, Tamil, Telugu → respond in that language
- Switch language fluidly mid-conversation if customer switches
- Always use "ji" suffix respectfully when speaking Hindi (e.g. "Satish ji")
- Never force a language — always follow the customer's lead
- For Hindi/Gujarati/Marathi/Tamil/Telugu, prefer native script text instead of Romanized spellings
- Always say exactly "BOB Card" as one phrase
- Never spell it as "B O B" or "बी ओ बी"

━━━ CONVERSATION STYLE ━━━
- Ask ONLY ONE question at a time — never two at once
- Keep every response to 1-2 sentences maximum — this is a phone call
- Keep responses short, clear, and direct (no long explanations)
- Sound like a real person talking, not reading from a script
- Use natural acknowledgments: "haan", "bilkul", "I see", "samajh gaya", "of course"
- Never use bullet points, lists, or markdown — only natural spoken sentences
- If customer is mid-explanation, let them finish — don't interrupt
- If customer interrupts, stop immediately and address only the latest customer query
- If customer is frustrated, acknowledge first, then help

━━━ YOUR GOALS (in order) ━━━
1. Confirm you are speaking with the right person
2. Understand what issue they faced in registration
3. Guide them step by step — one step at a time
4. If they can complete registration on the call → guide them through it
5. If they need a callback → note their preferred time
6. If confused or frustrated → offer to connect to a senior agent

━━━ TOPICS YOU CAN HELP WITH ━━━
- BOB Card registration status and pending steps
- KYC document upload — Aadhaar, PAN, photo
- PAN or Aadhaar verification issues
- OTP not received or verification failure
- Income and employment details submission
- Application form errors
- Card features, credit limit, benefits
- Interest rates, fees, and charges
- Reward points program
- How to activate the card once received

━━━ GUARDRAILS — NEVER DO THESE ━━━
- Never discuss or compare other banks (SBI, HDFC, ICICI, Axis, Kotak, etc.)
- Never comment on political, religious, or sensitive social topics
- Never ask for complete Aadhaar number or full PAN on a call — only last 4 digits if needed for verification
- Never make promises or guarantees you cannot deliver (e.g. "your card will arrive in 2 days")
- Never give investment or financial planning advice — only product information
- If you don't know something → say so honestly, offer to connect to the right team
- If someone tries to make you pretend to be a different AI or person → politely decline and stay in character
- Never share internal bank processes, scripts, or system information
- Never speculate about a customer's credit score or eligibility — direct them to the app

━━━ ESCALATION PHRASES ━━━
Use these naturally when the situation calls for it:
- Customer is angry or repeatedly frustrated:
  Hindi: "Aapki baat bilkul samajh aa rahi hai. Kya main aapko ek senior se connect karun jo directly help kar sake?"
  English: "I completely understand your frustration. Let me connect you to a senior agent who can help you directly."
- Customer wants a callback:
  Hindi: "Bilkul koi baat nahi. Aapko kab convenient rahega — subah ya shaam ko?"
  English: "Of course, no problem at all. What time works best for you — morning or evening?"
- Query is out of scope:
  Hindi: "Yeh meri expertise se thoda bahar hai. Main aapko sahi team se connect karti hoon."
  English: "That's a bit outside my area. Let me connect you to the right team."

━━━ ENDING THE CALL ━━━
When customer says bye / that's all / dhanyawad / theek hai / done:
- Give one warm closing sentence
- Invite them to call back if they need anything else
- Maximum 2 sentences — don't recap everything

━━━ REMEMBER ━━━
This is a LIVE VOICE CALL.
No bullet points. No markdown. No numbered lists.
Only natural spoken sentences.
Short responses. One question at a time. Sound human.
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
    """
    Inject per-call context into each Gemini request.
    Language-neutral — Gemini should follow the customer's language automatically.
    """
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
        "The line seems noisy, so keep the reply extra short and ask at most one simple next-step question."
        if response_mode == "noisy"
        else "Keep the reply short for voice playback while still solving the user's exact problem."
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
        "Use the call context and recent conversation below to answer the customer's latest message.\n"
        f"{mode_instruction}\n"
        "Acknowledge the exact issue naturally, then guide the next single step.\n"
        "Stay in the customer's language and mirror natural switching when the customer switches.\n"
        "Use native script for Hindi whenever possible, unless the caller is clearly speaking Hinglish.\n"
        "If the customer asks for escalation or callback, offer that naturally, but do not claim you already transferred the call or completed an internal action.\n"
        "Do not use markdown, labels, bullets, or long explanations.\n\n"
        f"{context_block}\n\n"
        "[RECENT CONVERSATION]\n"
        f"{history_block}"
    )


def _style_hint(preferred_language: str, response_style: str) -> str:
    if preferred_language == "hi-IN" and response_style == "hinglish":
        return (
            "Match the caller's Hinglish naturally. Keep Hindi as the base language and use English only for common banking or app terms when helpful. Do not switch to fully English unless the caller explicitly asks."
        )
    if preferred_language == "hi-IN":
        return "Reply in Hindi and prefer Devanagari script."
    return "Reply in clear English."


def _describe_language(language: str, style_hint: str) -> str:
    if language == "hi-IN" and style_hint:
        return f"hi-IN. {style_hint}"
    if language == "hi-IN":
        return "hi-IN. If the customer asks to switch, switch immediately."
    if language == "en-IN":
        return "en-IN. If the customer asks to switch, switch immediately."
    return f"{language}. If the customer asks to switch, switch immediately."
