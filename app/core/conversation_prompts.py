import re
from typing import Literal


BusinessState = Literal[
    "opening",
    "consent_check",
    "language_selection",
    "identity_verification",
    "context_setting",
    "issue_capture",
    "resolution_action",
    "confirmation_closing",
]


CallPhase = Literal[
    "call_bootstrap",
    "greeting",
    "listening",
    "customer_speaking",
    "silence_detected",
    "utterance_finalized",
    "transcribing",
    "main_points_ready",
    "planning_response",
    "response_plan_ready",
    "gemini_requested",
    "gemini_reply_ready",
    "gemini_fallback_used",
    "tts_requested",
    "tts_first_chunk_ready",
    "playback_started",
    "barge_in_confirmed",
    "playback_cancelling",
    "playback_interrupted",
    "listening_resumed",
    "call_summary_ready",
    "session_cleanup",
    "opening",
    "consent_check",
    "language_selection",
    "identity_verification",
    "context_setting",
    "issue_capture",
    "resolution_action",
    "confirmation_closing",
]

CALL_BOOTSTRAP = "call_bootstrap"
GREETING = "greeting"
LISTENING = "listening"
CUSTOMER_SPEAKING = "customer_speaking"
SILENCE_DETECTED = "silence_detected"
UTTERANCE_FINALIZED = "utterance_finalized"
TRANSCRIBING = "transcribing"
MAIN_POINTS_READY = "main_points_ready"
PLANNING_RESPONSE = "planning_response"
RESPONSE_PLAN_READY = "response_plan_ready"
GEMINI_REQUESTED = "gemini_requested"
GEMINI_REPLY_READY = "gemini_reply_ready"
GEMINI_FALLBACK_USED = "gemini_fallback_used"
TTS_REQUESTED = "tts_requested"
TTS_FIRST_CHUNK_READY = "tts_first_chunk_ready"
PLAYBACK_STARTED = "playback_started"
BARGE_IN_CONFIRMED = "barge_in_confirmed"
PLAYBACK_CANCELLING = "playback_cancelling"
PLAYBACK_INTERRUPTED = "playback_interrupted"
LISTENING_RESUMED = "listening_resumed"
CALL_SUMMARY_READY = "call_summary_ready"
SESSION_CLEANUP = "session_cleanup"
OPENING = "opening"
CONSENT_CHECK = "consent_check"
LANGUAGE_SELECTION = "language_selection"
IDENTITY_VERIFICATION = "identity_verification"
CONTEXT_SETTING = "context_setting"
ISSUE_CAPTURE = "issue_capture"
RESOLUTION_ACTION = "resolution_action"
CONFIRMATION_CLOSING = "confirmation_closing"

# Backward-compatible aliases for older flow references.
IDENTITY_CONFIRMATION = IDENTITY_VERIFICATION
RESOLUTION = RESOLUTION_ACTION
CLOSING = CONFIRMATION_CLOSING

PART_A_CALL_PHASES = {
    CALL_BOOTSTRAP,
    GREETING,
    LISTENING,
}

PART_B_CALL_PHASES = {
    CUSTOMER_SPEAKING,
    SILENCE_DETECTED,
    UTTERANCE_FINALIZED,
    TRANSCRIBING,
    MAIN_POINTS_READY,
}

PART_C_CALL_PHASES = {
    PLANNING_RESPONSE,
    RESPONSE_PLAN_READY,
}

PART_D_CALL_PHASES = {
    GEMINI_REQUESTED,
    GEMINI_REPLY_READY,
    GEMINI_FALLBACK_USED,
}

PART_E_CALL_PHASES = {
    TTS_REQUESTED,
    TTS_FIRST_CHUNK_READY,
    PLAYBACK_STARTED,
}

PART_F_CALL_PHASES = {
    BARGE_IN_CONFIRMED,
    PLAYBACK_CANCELLING,
    PLAYBACK_INTERRUPTED,
    LISTENING_RESUMED,
}

PART_G_CALL_PHASES = {
    CALL_SUMMARY_READY,
    SESSION_CLEANUP,
}

ConsentChoice = Literal["granted", "callback", "opt_out", "unknown"]
ResolutionChoice = Literal["more_help", "no_more_help", "unknown"]

SUPPORTED_VOICE_LANGUAGES = {"hi-IN", "en-IN"}

GOODBYE_KEYWORDS = [
    "bye", "alvida", "theek hai", "theek h", "dhanyawad", "shukriya",
    "bas", "khatam", "ho gaya", "ho gya", "band karo", "rakhta hoon",
    "rakh deta", "rakh do", "zyada nahi", "nahi chahiye", "thoda baad",
    "goodbye", "that's all", "that is all", "nothing else",
    "all done", "done for now", "ok thanks", "ok thank you",
    "thank you bye", "thanks bye", "no more",
]

ESCALATION_KEYWORDS = [
    "agent", "manager", "senior", "insaan", "human", "manushya",
    "gussa", "problem", "complaint", "shikayat", "galat",
    "koi nahi sun", "sun nahi", "samajh nahi",
    "speak to agent", "speak to human", "real person",
    "supervisor", "escalate", "not helpful", "this is wrong",
    "i want to complain",
]

AUTH_CONFIRM_KEYWORDS = [
    "haan", "ha", "han", "yes", "correct", "bilkul", "sahi", "theek",
    "right", "that's me", "speaking", "main hoon", "main hun", "bol raha hoon",
]

AUTH_DENY_KEYWORDS = [
    "nahi", "nahin", "no", "wrong number", "galat number",
    "not me", "wrong person", "koi aur", "kaun",
]

LANGUAGE_SWITCH_TARGETS = {
    "en-IN": [
        "english", "angrezi", "inglish",
        "इंग्लिश", "इंगलिश", "अंग्रेजी", "अँग्रेजी", "अंग्रेज़ी", "अँग्रेज़ी",
    ],
    "hi-IN": ["hindi", "hindee", "hindhi", "हिंदी", "हिन्दी"],
    "gu-IN": ["gujarati", "gujrati", "gujarathi", "ગુજરાતી"],
    "mr-IN": ["marathi", "marati", "मराठी"],
    "ta-IN": ["tamil", "tamizh", "தமிழ்"],
    "te-IN": ["telugu", "telgu", "తెలుగు"],
}

LANGUAGE_SWITCH_VERBS = [
    "speak", "talk", "respond", "answer", "continue", "switch", "change",
    "language", "bolo", "boliye", "baat", "baat karo",
    "बोलो", "बोलिए", "बात", "बात करो", "टॉक", "टॉक करो",
    "communicate", "in",
]

LANGUAGE_SWITCH_ONLY_BLOCKLIST = [
    "otp", "kyc", "registration", "status", "problem", "issue", "card", "limit",
    "interest", "fees", "charges", "payment", "bill", "due",
]


def normalize_language(language: str | None) -> str:
    if language in SUPPORTED_VOICE_LANGUAGES:
        return language
    return "en-IN"


def build_opening_greeting(
    name: str = "",
    language: str = "en-IN",
    agent_name: str = "",
) -> str:
    language = normalize_language(language)
    clean_name = _normalize_name(name)
    if language == "hi-IN":
        return (
            f"{_build_hindi_salutation(clean_name)} मैं बॉब कार्ड्स सपोर्ट टीम से बोल रही हूँ। "
            "यह कॉल रिकॉर्ड की जा रही है। "
            "मैंने देखा कि आपकी क्रेडिट कार्ड या बैंकिंग प्रक्रिया बीच में रुक गई थी। "
            "उसी को पूरा कराने में मदद के लिए कॉल किया है। "
            "क्या अभी दो मिनट बात करना ठीक रहेगा?"
        )

    display_name = f"{clean_name} ji" if clean_name else "there"
    return (
        f"Hello {display_name}. I am calling from the BOBCards support team. "
        "This call is being recorded. You were applying for a credit card or continuing a banking process, "
        "and I am calling to help you finish that step. "
        "Is this a good time to speak for two minutes?"
    )


def detect_language_preference(text: str) -> str | None:
    normalized = _normalize_choice_text(text)
    if not normalized:
        return None

    has_switch_verb = any(marker in normalized for marker in LANGUAGE_SWITCH_VERBS)
    for language_code, markers in LANGUAGE_SWITCH_TARGETS.items():
        if language_code not in SUPPORTED_VOICE_LANGUAGES:
            continue
        if not any(marker in normalized for marker in markers):
            continue

        if has_switch_verb:
            return language_code

        tokens = set(normalized.split())
        if tokens and tokens.issubset(set(LANGUAGE_SWITCH_ONLY_BLOCKLIST)):
            continue

        if len(tokens) <= 3:
            return language_code

    return None


def build_consent_reprompt(language: str, name: str = "") -> str:
    language = normalize_language(language)
    clean_name = _normalize_name(name)
    if language == "hi-IN":
        salutation = _build_hindi_salutation(clean_name)
        return f"{salutation} क्या आप अभी बात करने के लिए तैयार हैं? कृपया हाँ, बाद में, या मना कहिए।"
    prefix = f"{clean_name}, " if clean_name else ""
    return f"{prefix}is this a good time to continue? Please say yes, callback, or no."


def build_language_prompt(name: str = "", language: str = "en-IN") -> str:
    clean_name = _normalize_name(name)
    if normalize_language(language) == "hi-IN":
        salutation = _build_hindi_salutation(clean_name)
        return f"{salutation} आप हिंदी या अंग्रेज़ी में बात करना पसंद करेंगे?"
    prefix = f"{clean_name}, " if clean_name else ""
    return f"{prefix}would you like to continue in English or Hindi?"


def build_language_selected_reply(name: str = "", language: str = "en-IN") -> str:
    clean_name = _normalize_name(name)
    if normalize_language(language) == "hi-IN":
        ack = _build_hindi_ack(clean_name)
        return f"{ack} हम हिंदी में बात करते हैं।"
    prefix = f"Thank you {clean_name}. " if clean_name else "Thank you. "
    return f"{prefix}We can continue in English."


def build_language_preference_reprompt(name: str = "") -> str:
    clean_name = _normalize_name(name)
    if clean_name and not _contains_latin_text(clean_name):
        return f"{_build_hindi_salutation(clean_name)} कृपया हिंदी या अंग्रेज़ी बोलिए।"
    prefix = f"{clean_name}, " if clean_name else ""
    return f"{prefix}please say Hindi or English."


def build_identity_verification_prompt(name: str = "", language: str = "en-IN") -> str:
    clean_name = _normalize_name(name)
    if normalize_language(language) == "hi-IN":
        if clean_name:
            return f"क्या मैं {clean_name} ji से बात कर रही हूँ? कृपया हाँ या नहीं कहिए।"
        return "क्या मैं सही ग्राहक से बात कर रही हूँ? कृपया हाँ या नहीं कहिए।"
    if clean_name:
        return f"Am I speaking with {clean_name}? Please say yes or no."
    return "Am I speaking with the correct customer? Please say yes or no."


def build_identity_reprompt(name: str = "", language: str = "en-IN") -> str:
    clean_name = _normalize_name(name)
    if normalize_language(language) == "hi-IN":
        salutation = _build_hindi_salutation(clean_name)
        return f"{salutation} कृपया अपना नाम या सिर्फ हाँ बोलकर पुष्टि कीजिए।"
    prefix = f"{clean_name}, " if clean_name else ""
    return f"{prefix}please confirm your identity by saying your name or saying yes."


def build_identity_mismatch_reply(language: str = "en-IN") -> str:
    if normalize_language(language) == "hi-IN":
        return "ठीक है। लगता है मैं सही व्यक्ति से बात नहीं कर रही हूँ। हम इस कॉल को यहीं समाप्त करते हैं। धन्यवाद।"
    return "Understood. It looks like I am not speaking with the correct person, so I will end this call now. Thank you."


def build_context_setting_prompt(language: str = "en-IN", name: str = "") -> str:
    clean_name = _normalize_name(name)
    if normalize_language(language) == "hi-IN":
        prefix = f"{clean_name} ji, " if clean_name else ""
        return (
            f"{prefix}मैं आपकी BOBCards application या banking process में जहाँ step रुक गया था, "
            "उसी में मदद करने के लिए कॉल कर रही हूँ।"
        )
    prefix = f"{clean_name}, " if clean_name else ""
    return (
        f"{prefix}I am calling to help with the BOBCards application or banking step "
        "where your process got stuck."
    )


def build_issue_capture_prompt(language: str = "en-IN", name: str = "") -> str:
    clean_name = _normalize_name(name)
    if normalize_language(language) == "hi-IN":
        salutation = _build_hindi_salutation(clean_name)
        return f"{salutation} मैं आपके साथ यही step पूरा कराती हूँ। बस बताइए अभी दिक्कत किस जगह आ रही है।"
    prefix = f"{clean_name}, " if clean_name else ""
    return f"{prefix}I will help you complete this step. Please tell me where exactly you are getting stuck right now."


def build_post_greeting_issue_prompt(language: str = "en-IN", name: str = "") -> str:
    clean_name = _normalize_name(name)
    if normalize_language(language) == "hi-IN":
        prefix = f"{clean_name} ji, " if clean_name else ""
        return f"{prefix}मैं आपके BOB Card application में जहाँ process रुक गया था, उसी में help करती हूँ। अभी किस step पर दिक्कत आ रही है?"
    prefix = f"{clean_name}, " if clean_name else ""
    return f"{prefix}I am calling to help with the BOB Card application step where your process got stuck. Which step is giving you trouble right now?"


def build_general_capabilities_reply(language: str = "en-IN", response_style: str = "default") -> str:
    language = normalize_language(language)
    if language == "hi-IN" and response_style == "hinglish":
        return (
            "Main BOBCards se judi banking help deti hoon, jaise credit card application, Aadhaar ya PAN upload, OTP, login, statement, invoice, refund, EMI, aur application status. "
            "Aap jo service samajhna chahte hain, uska naam bol dijiye."
        )
    if language == "hi-IN":
        return (
            "मैं BOBCards से जुड़ी बैंकिंग मदद देती हूँ, जैसे क्रेडिट कार्ड आवेदन, आधार या पैन अपलोड, ओटीपी, लॉगिन, स्टेटमेंट, इनवॉइस, रिफंड, ईएमआई, और आवेदन की स्थिति। "
            "आप जिस सेवा के बारे में जानना चाहते हैं, उसका नाम बताइए।"
        )
    return (
        "I can help with BOBCards banking journeys such as credit card application, Aadhaar or PAN upload, OTP, login, statement, invoice, refund, EMI, and application status. "
        "Please tell me which service you want to know about."
    )


def build_human_handoff_reply(language: str = "en-IN") -> str:
    if normalize_language(language) == "hi-IN":
        return "इस हिस्से में मैं पक्की जानकारी नहीं दे पा रही हूँ। ज़रूरत हो तो मैं callback का अनुरोध नोट कर सकती हूँ।"
    return "I am not fully confident about that part. If you want, I can note a callback request."


def build_empty_input_reply(language: str = "en-IN") -> str:
    if normalize_language(language) == "hi-IN":
        return "आपकी आवाज़ साफ़ नहीं आई। एक बार फिर बोलिए।"
    return "I could not hear you clearly. Please say it once again."


def build_first_unclear_reply(language: str = "en-IN") -> str:
    if normalize_language(language) == "hi-IN":
        return "मैं आपकी बात ठीक से पकड़ नहीं पाई। एक बार फिर बोलिए।"
    return "I could not catch that clearly. Please repeat once."


def build_second_unclear_reply(language: str = "en-IN") -> str:
    if normalize_language(language) == "hi-IN":
        return "लाइन पर थोड़ा शोर है। आप छोटे शब्दों में जवाब दीजिए, मैं उसी से आगे बढ़ती हूँ।"
    return "There is some noise on the line. Please answer in a few words and I will continue from there."


def build_noisy_fallback_reply(language: str = "en-IN") -> str:
    if normalize_language(language) == "hi-IN":
        return "लाइन पर काफ़ी शोर है। अगर अभी बात मुश्किल है, तो आप बाद में कॉल कह सकते हैं।"
    return "There is a lot of noise on the line. If this is not a good time, you can ask for a callback."


def build_noisy_mode_acknowledgement(language: str = "en-IN") -> str:
    if normalize_language(language) == "hi-IN":
        return "मैं छोटा जवाब रखती हूँ क्योंकि लाइन पर शोर है। आप भी छोटे जवाब दीजिए।"
    return "I will keep this short because the line sounds noisy. Please answer in a few words."


def build_opt_out_reply(language: str = "en-IN") -> str:
    if normalize_language(language) == "hi-IN":
        return "समझ गई। हम इस स्वचालित कॉल को यहीं समाप्त करते हैं। धन्यवाद।"
    return "Understood. We will end this automated call now. Thank you."


def build_callback_ack(language: str = "en-IN") -> str:
    if normalize_language(language) == "hi-IN":
        return "धन्यवाद। मैं बाद में कॉल करने का अनुरोध नोट कर रही हूँ। नमस्ते।"
    return "Thank you. I will note a callback request for later. Goodbye."


def build_sms_link_ack(language: str = "en-IN") -> str:
    if normalize_language(language) == "hi-IN":
        return "धन्यवाद। मैं संदेश लिंक भेजने का अनुरोध नोट कर रही हूँ। नमस्ते।"
    return "Thank you. I will note that you want an SMS link for follow up. Goodbye."


def build_short_choice_prompt(language: str = "en-IN") -> str:
    if normalize_language(language) == "hi-IN":
        return "कृपया बाद में कॉल या लिंक भेजें बोलिए।"
    return "Please say callback or send link."


def build_goodbye_reply(language: str = "en-IN") -> str:
    if normalize_language(language) == "hi-IN":
        return "आपके समय के लिए धन्यवाद। ज़रूरत पड़े तो BOBCards agent बाद में मदद कर सकता है।"
    return "Thank you for your time. If you need more help, a BOBCards agent can assist you later."


def build_resolution_completed_reply(language: str = "en-IN") -> str:
    if normalize_language(language) == "hi-IN":
        return "बहुत अच्छा, आपकी दिक्कत resolve हो गई। आगे कभी मदद चाहिए तो BOB Card support से फिर बात कर सकते हैं।"
    return "Glad that your issue is resolved. If you need any more help, you can reach BOB Card support again."


def build_resolution_follow_up_prompt(language: str = "en-IN") -> str:
    if normalize_language(language) == "hi-IN":
        return "ठीक है, यह issue resolve हो गया। क्या आपको किसी और चीज़ में मदद चाहिए?"
    return "Glad this issue is resolved. Do you need help with anything else?"


def detect_resolution_choice(text: str) -> ResolutionChoice:
    normalized = _normalize_choice_text(text)
    if not normalized:
        return "unknown"

    no_more_help_markers = (
        "no",
        "nope",
        "no thanks",
        "nothing else",
        "that is all",
        "thats all",
        "that's all",
        "all good",
        "no issue",
        "no more help",
        "no more",
        "नहीं",
        "नही",
        "बस",
        "और कुछ नहीं",
        "और मदद नहीं",
        "नहीं चाहिए",
        "कोई और मदद नहीं",
        "ठीक है बस",
    )
    if normalized in no_more_help_markers or any(marker in normalized for marker in no_more_help_markers):
        return "no_more_help"

    more_help_markers = (
        "yes",
        "haan",
        "haan ji",
        "haanji",
        "yes please",
        "sure",
        "another issue",
        "need help",
        "more help",
        "हाँ",
        "हां",
        "हाँ जी",
        "हां जी",
        "जी",
        "हाँ चाहिए",
        "और मदद चाहिए",
        "एक और दिक्कत",
        "एक और issue",
    )
    if normalized in more_help_markers or any(marker in normalized for marker in more_help_markers):
        return "more_help"

    return "unknown"


def wants_goodbye(text: str) -> bool:
    normalized = _normalize_choice_text(text)
    if not normalized:
        return False

    strong_goodbye_markers = (
        "bye",
        "alvida",
        "dhanyawad",
        "shukriya",
        "khatam",
        "band karo",
        "rakhta hoon",
        "rakh deta",
        "rakh do",
        "goodbye",
        "that s all",
        "that is all",
        "nothing else",
        "all done",
        "done for now",
        "ok thanks",
        "ok thank you",
        "thank you bye",
        "thanks bye",
    )
    if any(marker in normalized for marker in strong_goodbye_markers):
        return True

    soft_goodbye_markers = ("theek hai", "theek h", "bas", "no more", "zyada nahi", "nahi chahiye", "thoda baad")
    tokens = normalized.split()
    return len(tokens) <= 4 and any(marker in normalized for marker in soft_goodbye_markers)


def detect_escalation_request(text: str) -> bool:
    normalized = _normalize_choice_text(text)
    if not normalized:
        return False

    direct_request_markers = (
        "speak to agent",
        "speak to human",
        "real person",
        "supervisor",
        "escalate",
        "i want to complain",
        "agent",
        "manager",
        "senior",
        "human",
        "insaan",
        "manushya",
    )
    if any(marker in normalized for marker in direct_request_markers):
        return True

    frustration_markers = (
        "complaint",
        "shikayat",
        "koi nahi sun",
        "sun nahi",
        "samajh nahi",
        "not helpful",
        "this is wrong",
    )
    escalation_context_markers = ("agent", "manager", "senior", "human", "supervisor", "escalate")
    return any(marker in normalized for marker in frustration_markers) and any(
        marker in normalized for marker in escalation_context_markers
    )


def detect_auth_confirmation(text: str) -> bool:
    normalized = _normalize_choice_text(text)
    if not normalized:
        return False
    return any(marker in normalized for marker in AUTH_CONFIRM_KEYWORDS)


def detect_auth_denial(text: str) -> bool:
    normalized = _normalize_choice_text(text)
    if not normalized:
        return False
    return any(marker in normalized for marker in AUTH_DENY_KEYWORDS)


def build_opted_out_notice(language: str = "en-IN") -> str:
    if normalize_language(language) == "hi-IN":
        return "आपका नंबर मना सूची में है। हम इस स्वचालित कॉल को आगे नहीं बढ़ाएँगे। धन्यवाद।"
    return "Your number is marked as opted out. We will not continue this automated call. Thank you."


def detect_consent_choice(text: str) -> ConsentChoice:
    normalized = _normalize_choice_text(text)
    if not normalized:
        return "unknown"

    opt_out_markers = (
        "not interested",
        "do not call",
        "don't call",
        "dont call",
        "stop calling",
        "मुझे कॉल मत करो",
        "कॉल मत करो",
        "रुचि नहीं",
        "दिलचस्पी नहीं",
    )
    if any(marker in normalized for marker in opt_out_markers):
        return "opt_out"

    callback_markers = (
        "busy",
        "not now",
        "later",
        "callback",
        "call back",
        "another time",
        "abhi nahi",
        "time nahi",
        "baad mein",
        "baad me",
        "kal",
        "subah",
        "shaam",
        "अभी नहीं",
        "बाद में",
        "कल",
        "सुबह",
        "शाम",
    )
    if any(marker in normalized for marker in callback_markers):
        return "callback"

    affirmative_markers = (
        "yes",
        "haan",
        "ha",
        "bilkul",
        "okay",
        "ok",
        "sure",
        "correct",
        "हाँ",
        "हां",
        "जी",
        "जी हाँ",
        "जी हां",
        "हाँ जी",
        "हां जी",
        "ठीक है",
        "theek hai",
        "बात कर सकते हैं",
        "baat kar sakte hain",
        "talk kar sakte hain",
        "we can talk",
        "can talk now",
    )
    if normalized in affirmative_markers or any(marker in normalized for marker in affirmative_markers):
        return "granted"

    if normalized in {"no", "nahi", "nahin", "नहीं", "नही"}:
        return "callback"

    return "unknown"


def next_phase_after_consent(choice: ConsentChoice = "granted") -> CallPhase:
    if choice == "granted":
        return LANGUAGE_SELECTION
    if choice in {"callback", "opt_out"}:
        return CLOSING
    return CONSENT_CHECK


def next_phase_after_language_selection() -> CallPhase:
    return IDENTITY_VERIFICATION


def next_phase_after_identity(notes: str | None) -> CallPhase:
    return CONTEXT_SETTING if (notes or "").strip() else ISSUE_CAPTURE


def next_phase_after_issue_capture() -> CallPhase:
    return RESOLUTION_ACTION


def next_phase_after_resolution(needs_more_help: bool = False) -> CallPhase:
    return ISSUE_CAPTURE if needs_more_help else CONFIRMATION_CLOSING


def _normalize_choice_text(text: str) -> str:
    normalized = (text or "").lower().strip()
    normalized = re.sub(r"[।,.!?;:]+", " ", normalized)
    normalized = re.sub(r"[^\w\s\u0900-\u097F]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _contains_latin_text(text: str) -> bool:
    return any("a" <= char.lower() <= "z" for char in text)


def _normalize_name(name: str) -> str:
    return " ".join(name.strip().split())


def _build_hindi_salutation(name: str) -> str:
    return f"नमस्ते {name}।" if name else "नमस्ते।"


def _build_hindi_ack(name: str) -> str:
    return f"ठीक है {name}।" if name else "ठीक है।"
