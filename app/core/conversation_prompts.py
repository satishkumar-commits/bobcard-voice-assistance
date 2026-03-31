import re
from typing import Literal


BusinessState = Literal[
    "opening",
    "consent_check",
    "language_selection",
    "identity_verification",
    "context_setting",
    "issue_capture",
    "personal_details_validation",
    "age_eligibility_check",
    "aadhaar_verification",
    "address_capture",
    "cibil_fetch",
    "offer_eligibility",
    "card_selection",
    "e_consent",
    "vkyc_pending",
    "vkyc_complete",
    "application_complete",
    "terminal_rejection",
    "resume_journey",
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
    "personal_details_validation",
    "age_eligibility_check",
    "aadhaar_verification",
    "address_capture",
    "cibil_fetch",
    "offer_eligibility",
    "card_selection",
    "e_consent",
    "vkyc_pending",
    "vkyc_complete",
    "application_complete",
    "terminal_rejection",
    "resume_journey",
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
PERSONAL_DETAILS_VALIDATION = "personal_details_validation"
AGE_ELIGIBILITY_CHECK = "age_eligibility_check"
AADHAAR_VERIFICATION = "aadhaar_verification"
ADDRESS_CAPTURE = "address_capture"
CIBIL_FETCH = "cibil_fetch"
OFFER_ELIGIBILITY = "offer_eligibility"
CARD_SELECTION = "card_selection"
E_CONSENT = "e_consent"
VKYC_PENDING = "vkyc_pending"
VKYC_COMPLETE = "vkyc_complete"
APPLICATION_COMPLETE = "application_complete"
TERMINAL_REJECTION = "terminal_rejection"
RESUME_JOURNEY = "resume_journey"
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

ConsentChoice = Literal["granted", "callback", "send_link", "opt_out", "unknown"]
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
    "हाँ", "हां", "जी हाँ", "जी हां", "हाँ जी", "हां जी", "जी",
    "yes ji", "hello", "हलो", "बोलिए", "bolo",
]

AUTH_DENY_KEYWORDS = [
    "nahi", "nahin", "no", "wrong number", "galat number",
    "not me", "wrong person", "koi aur", "kaun",
]

SHORT_AFFIRMATIVE_PHRASES = {
    "हाँ",
    "हां",
    "हाँ जी",
    "हां जी",
    "जी",
    "जी हाँ",
    "जी हां",
    "yes",
    "yes ji",
    "speaking",
    "main hoon",
    "main hun",
    "bol raha hoon",
    "bilkul",
    "correct",
    "right",
    "ठीक है",
    "theek hai",
    "thik hai",
}

SHORT_VALID_ACK_PHRASES = {
    "हलो",
    "हेलो",
    "hello",
    "hi",
    "hey",
    "namaste",
    "नमस्ते",
    "बोलिए",
    "bolo",
    "boliye",
    "हाँ",
    "हां",
    "हाँ जी",
    "हां जी",
    "जी",
    "yes",
    "yes ji",
    "speaking",
    "ठीक है",
    "थीक है",
    "theek hai",
    "thik hai",
    "जी बताइए",
    "ji batayiye",
    "ji bataiye",
}

AFFIRMATIVE_ADVANCE_PHASES = {
    OPENING,
    CONSENT_CHECK,
    IDENTITY_VERIFICATION,
    CONTEXT_SETTING,
    AADHAAR_VERIFICATION,
    CARD_SELECTION,
    E_CONSENT,
}

IDENTITY_NAME_STOPWORDS = {
    "hello",
    "hi",
    "hey",
    "namaste",
    "हलो",
    "हेलो",
    "नमस्ते",
    "haan",
    "ha",
    "han",
    "yes",
    "ji",
    "no",
    "nahi",
    "nahin",
    "नहीं",
    "नही",
    "hindi",
    "english",
    "हिंदी",
    "हिन्दी",
    "अंग्रेज़ी",
    "angrezi",
    "day",
    "days",
    "din",
    "दिवस",
    "दिन",
}

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
    assistant_name = _normalize_name(agent_name) or "माया"
    if _contains_latin_text(assistant_name):
        assistant_name = "माया"
    if language == "hi-IN":
        salutation = _build_hindi_salutation(clean_name).rstrip("।")
        return (
            f"{salutation}, मैं {assistant_name} हूँ, BOB Card की एआई वॉइस सहायक बोल रही हूँ। "
            "यह कॉल गुणवत्ता के लिए रिकॉर्ड की जा रही है। "
            "आपका क्रेडिट कार्ड आवेदन अधूरा है, उसे पूरा कराने के लिए मैं कॉल कर रही हूँ। "
            "क्या अभी दो मिनट बात करना ठीक रहेगा?"
        )

    display_name = f"{clean_name} ji" if clean_name else "there"
    return (
        f"Hello {display_name}. I am {assistant_name}, an AI assistant calling on behalf of BOB Card. "
        "This call is recorded for quality purposes. "
        "Your BOBCards credit card application is incomplete, and I am calling to help you complete it. "
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
        return f"{salutation} अगर बात कर सकते हैं तो हाँ कहिए। नहीं तो कॉलबैक, लिंक, या मना कहिए।"
    prefix = f"{clean_name}, " if clean_name else ""
    return (
        f"{prefix}if now is not a good time, you can choose callback, SMS link, or do-not-call. "
        "Please say yes, callback, link, or no."
    )


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
        hindi_name = _normalize_hindi_name(clean_name)
        if hindi_name:
            return f"क्या मैं {hindi_name} जी से बात कर रही हूँ? कृपया हाँ या नहीं कहिए।"
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
            f"{prefix}ठीक है। क्या मैं आपको एक लिंक शेयर करूँ ताकि हम प्रक्रिया जहाँ रुकी थी उसे पूरा कर सकें? "
            "कृपया हाँ या नहीं कहिए।"
        )
    prefix = f"{clean_name}, " if clean_name else ""
    return (
        f"{prefix}Okay, may I share a link so we can continue from where the process stopped? "
        "Please say yes or no."
    )


def build_issue_capture_prompt(language: str = "en-IN", name: str = "") -> str:
    clean_name = _normalize_name(name)
    if normalize_language(language) == "hi-IN":
        salutation = _build_hindi_salutation(clean_name)
        return f"{salutation} अब बताइए आप किस जगह पर problem face कर रहे हैं।"
    prefix = f"{clean_name}, " if clean_name else ""
    return f"{prefix}Please tell me exactly where you are facing a problem."


def build_post_greeting_issue_prompt(language: str = "en-IN", name: str = "") -> str:
    clean_name = _normalize_name(name)
    if normalize_language(language) == "hi-IN":
        prefix = f"{clean_name} ji, " if clean_name else ""
        return f"{prefix}ठीक है। अब बताइए किस step पर दिक्कत आ रही है?"
    prefix = f"{clean_name}, " if clean_name else ""
    return f"{prefix}I am calling to help with the BOB Card application step where your process got stuck. Which step is giving you trouble right now?"


def build_link_share_confirmation_prompt(language: str = "en-IN") -> str:
    if normalize_language(language) == "hi-IN":
        return "क्या मैं आपको एक लिंक शेयर करूँ ताकि हम प्रक्रिया जहाँ रुकी थी उसे पूरा कर सकें? कृपया हाँ या नहीं कहिए।"
    return "May I share a link so we can continue from where the process stopped? Please say yes or no."


def build_link_sent_confirmation_prompt(language: str = "en-IN") -> str:
    if normalize_language(language) == "hi-IN":
        return "धन्यवाद। मैं अभी लिंक शेयर कर रही हूँ। कृपया बताइए: लिंक मिला या नहीं मिला?"
    return "Thank you. I am sharing the link now. Please tell me: link received or not received."


def build_link_confirmation_reprompt(language: str = "en-IN") -> str:
    if normalize_language(language) == "hi-IN":
        return "कृपया सिर्फ इतना बताइए: लिंक मिला या नहीं मिला?"
    return "Please tell me only this: link received or not received?"


def build_link_safety_reassurance_reply(language: str = "en-IN") -> str:
    if normalize_language(language) == "hi-IN":
        return (
            "अच्छा सवाल। यह BOB Card का official link है। "
            "कृपया OTP, PIN या CVV कभी साझा न करें। "
            "क्या मैं यही official link दोबारा भेज दूँ?"
        )
    return (
        "Good question. This is an official BOB Card link. "
        "Please do not share OTP, PIN, or CVV with anyone. "
        "Should I resend the same official link now?"
    )


def build_link_received_next_prompt(language: str = "en-IN", name: str = "") -> str:
    clean_name = _normalize_name(name)
    if normalize_language(language) == "hi-IN":
        prefix = f"{clean_name} जी, " if clean_name else ""
        return f"{prefix}बहुत बढ़िया। अब बताइए किस चरण में दिक्कत आ रही है।"
    prefix = f"{clean_name}, " if clean_name else ""
    return f"{prefix}Great. Now tell me where exactly you are facing a problem."


def build_general_capabilities_reply(language: str = "en-IN", response_style: str = "default") -> str:
    language = normalize_language(language)
    if language == "hi-IN" and response_style == "hinglish":
        return "Main BOB Card ke features, fees aur eligibility batati hoon; aap kis cheez ki jankari chahte hain?"
    if language == "hi-IN":
        return "मैं BOB Card के फीचर्स, फीस और पात्रता बता सकती हूँ; आप किस बारे में जानना चाहते हैं?"
    return (
        "I can help with BOB Card journeys such as application continuation, Aadhaar or PAN upload, OTP, login, statement, invoice, refund, EMI, and application status. "
        "Please tell me which service you want to know about."
    )


def build_product_info_follow_up_prompt(language: str = "en-IN") -> str:
    if normalize_language(language) == "hi-IN":
        return "क्या आप फीस, लाभ, या पात्रता के बारे में जानना चाहते हैं?"
    return "Do you want details about fees, benefits, or eligibility?"


def build_human_handoff_reply(language: str = "en-IN") -> str:
    if normalize_language(language) == "hi-IN":
        return "मैं अभी आपको मानव एजेंट से जोड़ रही हूँ। कृपया लाइन पर रहें।"
    return "I will connect you to a human agent now. Please stay on the line."


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


def build_application_not_started_reply(language: str = "en-IN") -> str:
    if normalize_language(language) == "hi-IN":
        return "समझ गई। अगर आपने BOB Card आवेदन शुरू नहीं किया है, तो मैं यह कॉल यहीं समाप्त करती हूँ। धन्यवाद।"
    return "Understood. If you have not started a BOB Card application, I will close this call now. Thank you."


def build_callback_ack(language: str = "en-IN") -> str:
    if normalize_language(language) == "hi-IN":
        return "धन्यवाद। मैं बाद में कॉल करने का अनुरोध नोट कर रही हूँ। नमस्ते।"
    return "Thank you. I will note a callback request for later. Goodbye."


def build_sms_link_ack(language: str = "en-IN") -> str:
    if normalize_language(language) == "hi-IN":
        return "धन्यवाद। मैं संदेश लिंक भेजने का अनुरोध नोट कर रही हूँ। नमस्ते।"
    return "Thank you. I will note that you want an SMS link for follow up. Goodbye."


def build_process_restart_link_reply(language: str = "en-IN") -> str:
    if normalize_language(language) == "hi-IN":
        return "जी, क्या मैं आपको एक लिंक शेयर करूँ ताकि हम प्रक्रिया जहाँ रुकी थी वहाँ से फिर से शुरू कर सकें?"
    return "Yes, may I share a link so we can restart from where the process stopped?"


def build_link_not_received_reply(language: str = "en-IN") -> str:
    if normalize_language(language) == "hi-IN":
        return "जी, माफ़ कीजिए। मैं लिंक अभी दोबारा भेज रही हूँ।"
    return "Sorry, I will resend the link right away."


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
        return "बहुत अच्छा, आपकी समस्या का समाधान हो गया है। आगे कभी मदद चाहिए तो BOB Card support से फिर बात कर सकते हैं।"
    return "Glad that your issue is resolved. If you need any more help, you can reach BOB Card support again."


def build_resolution_follow_up_prompt(language: str = "en-IN") -> str:
    if normalize_language(language) == "hi-IN":
        return "धन्यवाद, आपकी समस्या का समाधान हो गया है। क्या आपको किसी और चीज़ में मदद चाहिए?"
    return "Glad this issue is resolved. Do you need help with anything else?"


def build_retry_after_30_days_reply(language: str = "en-IN") -> str:
    if normalize_language(language) == "hi-IN":
        return "क्षमा कीजिए, अभी हम आपका आवेदन आगे नहीं बढ़ा सकते। कृपया 30 दिन बाद फिर प्रयास करें।"
    return "Sorry sir, at the moment we are unable to proceed with your application. You may try again after 30 days."


def build_pan_dob_mismatch_reply(language: str = "en-IN") -> str:
    if normalize_language(language) == "hi-IN":
        return "क्षमा कीजिए, आपका PAN और जन्मतिथि रिकॉर्ड से मेल नहीं खा रहे। कृपया जाँचकर फिर प्रयास करें।"
    return "Sorry sir, your PAN and date of birth do not match our records. Please check and try again."


def build_max_attempts_exceeded_reply(language: str = "en-IN") -> str:
    if normalize_language(language) == "hi-IN":
        return "आपने अधिकतम प्रयास पूरे कर लिए हैं। कृपया 24 घंटे बाद फिर प्रयास करें।"
    return "You have reached the maximum number of attempts. Please try again after 24 hours."


def build_age_ineligible_reply(language: str = "en-IN") -> str:
    if normalize_language(language) == "hi-IN":
        return "BOB Card नीति के अनुसार न्यूनतम पात्र आयु 25 वर्ष है। अभी आप इस मानदंड पर पात्र नहीं हैं।"
    return "As per BOB Card policy, the minimum eligible age is 25 years. Currently, you do not meet this criteria."


def build_technical_failure_reply(language: str = "en-IN") -> str:
    if normalize_language(language) == "hi-IN":
        return "अभी तकनीकी समस्या है। कृपया थोड़ी देर बाद फिर कोशिश करें और अपनी यात्रा दोबारा शुरू करें।"
    return "We are facing a technical issue at the moment. Kindly try again after some time and restart your journey."


def build_aadhaar_pan_not_linked_reply(language: str = "en-IN") -> str:
    if normalize_language(language) == "hi-IN":
        return "हमें खेद है, आपका Aadhaar PAN से लिंक नहीं है। कृपया लिंक करके फिर प्रयास करें।"
    return "We regret to inform you that your Aadhaar is not linked with your PAN card. Please link it and try again."


def build_aadhaar_hindi_not_supported_reply(language: str = "en-IN") -> str:
    if normalize_language(language) == "hi-IN":
        return "अभी Aadhaar verification हिंदी में उपलब्ध नहीं है। कृपया English में जारी रखें।"
    return "Currently, Aadhaar verification is not available in Hindi. Please continue in English."


def build_aadhaar_reverify_reply(language: str = "en-IN") -> str:
    if normalize_language(language) == "hi-IN":
        return "कृपया Aadhaar और PAN लिंक सही करें, फिर verification दोबारा करें।"
    return "Please ensure your Aadhaar and PAN are linked correctly, then try the verification again."


def build_aadhaar_verification_failure_reply(language: str = "en-IN") -> str:
    if normalize_language(language) == "hi-IN":
        return "क्षमा कीजिए, सिस्टम समस्या के कारण verification पूरा नहीं हो पाया। कृपया फिर से प्रयास करें।"
    return "Sorry, verification could not be completed due to a system issue. Please try again to continue the process."


def build_vkyc_72h_reminder_reply(language: str = "en-IN") -> str:
    if normalize_language(language) == "hi-IN":
        return "Aadhaar verification के बाद कृपया 72 घंटे के भीतर video KYC पूरा करें।"
    return "After Aadhaar verification, please complete your video KYC within 72 hours."


def build_vkyc_72h_expired_reply(language: str = "en-IN") -> str:
    if normalize_language(language) == "hi-IN":
        return "Video KYC 72 घंटे में पूरा नहीं हुआ, इसलिए आवेदन बंद हो गया। कृपया प्रक्रिया फिर से शुरू करें।"
    return "Your application could not be completed because video KYC was not finished within 72 hours. Please restart the application to continue."


def build_offer_eligible_no_docs_reply(language: str = "en-IN") -> str:
    if normalize_language(language) == "hi-IN":
        return "अच्छी खबर, आप बिना अतिरिक्त दस्तावेज़ के card offers के लिए पात्र हैं।"
    return "Good news, you are eligible for card offers without additional documents."


def build_bank_statement_required_reply(language: str = "en-IN") -> str:
    if normalize_language(language) == "hi-IN":
        return "आगे बढ़ने के लिए bank statement चाहिए। आप net banking से या manual upload से आगे बढ़ सकते हैं।"
    return "To continue, we need your bank statement. You can proceed through net banking or upload your statement manually."


def build_bank_not_listed_manual_upload_reply(language: str = "en-IN") -> str:
    if normalize_language(language) == "hi-IN":
        return "अगर आपका bank सूची में नहीं है, तो आप statement manual upload से जमा कर सकते हैं।"
    return "If your bank is not listed, you can upload your bank statement manually."


def build_salaried_only_reply(language: str = "en-IN") -> str:
    if normalize_language(language) == "hi-IN":
        return "अभी यह प्रक्रिया केवल salaried customers के लिए उपलब्ध है।"
    return "Currently, this process is available only for salaried customers."


def build_better_offer_reply(language: str = "en-IN") -> str:
    if normalize_language(language) == "hi-IN":
        return "आपके bank details देखने के बाद हम बेहतर credit offers दिखा सकते हैं।"
    return "We may be able to show you better credit offers after reviewing your bank details."


def build_card_selection_required_reply(language: str = "en-IN") -> str:
    if normalize_language(language) == "hi-IN":
        return "कृपया आगे बढ़ने के लिए उपलब्ध card options में से एक चुनें।"
    return "Please choose one of the available card options to continue."


def build_e_consent_step_reply(language: str = "en-IN") -> str:
    if normalize_language(language) == "hi-IN":
        return "कृपया विवरण देखकर आगे बढ़ने के लिए swipe right करें।"
    return "Please review the details and swipe right to proceed."


def build_vkyc_instructions_reply(language: str = "en-IN") -> str:
    if normalize_language(language) == "hi-IN":
        return "Video KYC के लिए original PAN रखें, location access allow करें, और plain light background में बैठें।"
    return "For video KYC, please keep your original PAN card ready, allow location access, and sit in front of a plain light background."


def build_application_complete_reply(language: str = "en-IN") -> str:
    if normalize_language(language) == "hi-IN":
        return "आपकी application प्रक्रिया पूरी हो गई है। BOB Card चुनने के लिए धन्यवाद।"
    return "Your application process is complete. Thank you for choosing BOB Card."


def build_resume_journey_reply(language: str = "en-IN") -> str:
    if normalize_language(language) == "hi-IN":
        return "Welcome back। आप अपनी application वहीं से जारी कर सकते हैं जहाँ रुकी थी।"
    return "Welcome back. You can continue your application from where you left off."


def build_stt_timeout_retry_reply(language: str = "en-IN") -> str:
    if normalize_language(language) == "hi-IN":
        return "आपकी आवाज़ आई थी, पर टेक्स्ट पूरा नहीं बन पाया। कृपया एक बार फिर छोटा जवाब दें।"
    return "I heard your response, but the transcript did not complete. Please repeat in one short line."


def build_flow_response(
    text: str,
    next_phase: str | None = None,
    is_terminal: bool = False,
    response_type: str | None = None,
    extra: dict | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "text": text,
        "is_terminal": is_terminal,
    }
    if next_phase:
        payload["next_phase"] = next_phase
    if response_type:
        payload["response_type"] = response_type
    if extra:
        payload.update(extra)
    return payload


def detect_resolution_choice(text: str) -> ResolutionChoice:
    normalized = _normalize_choice_text(text)
    if not normalized:
        return "unknown"

    no_more_help_markers = (
        "no",
        "nope",
        "no thanks",
        "done",
        "resolved",
        "ho gaya",
        "ho gya",
        "hogaya",
        "हो गया",
        "होगया",
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
        "thank you",
        "thanks",
        "thik hai thank you",
        "theek hai thank you",
        "थैंक यू",
        "धन्यवाद",
        "शुक्रिया",
        "फोन रख दो",
        "कॉल काट दो",
        "कोई समस्या नहीं",
        "समस्या नहीं",
        "दिक्कत नहीं",
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


def detect_auth_confirmation(text: str, current_phase: str | None = None) -> bool:
    normalized = _normalize_choice_text(text)
    if not normalized:
        return False
    if _looks_like_identity_name_confirmation(normalized):
        return True
    if should_advance_on_affirmative(text, current_phase or IDENTITY_VERIFICATION):
        return True
    return any(marker in normalized for marker in AUTH_CONFIRM_KEYWORDS)


def detect_auth_denial(text: str) -> bool:
    normalized = _normalize_choice_text(text)
    if not normalized:
        return False
    return any(marker in normalized for marker in AUTH_DENY_KEYWORDS)


def is_valid_short_response(text: str, current_phase: str | None = None) -> bool:
    normalized = _normalize_choice_text(text)
    if not normalized:
        return False

    tokens = normalized.split()
    if len(tokens) > 8:
        return False

    if normalized in {choice.lower() for choice in SHORT_VALID_ACK_PHRASES}:
        return True

    if any(normalized.startswith(f"{choice.lower()} ") for choice in SHORT_VALID_ACK_PHRASES):
        return True

    consent_choice = detect_consent_choice(text, current_stage=current_phase)
    if consent_choice != "unknown":
        return True

    if should_advance_on_affirmative(text, current_phase):
        return True

    if detect_auth_denial(text):
        return True

    if detect_resolution_choice(text) != "unknown":
        return True

    return False


def should_advance_on_affirmative(text: str, current_phase: str | None = None) -> bool:
    normalized = _normalize_choice_text(text)
    if not normalized:
        return False

    if current_phase and current_phase not in AFFIRMATIVE_ADVANCE_PHASES:
        return False

    if _looks_like_identity_name_confirmation(normalized):
        return True

    if any(
        normalized == choice.lower() or normalized.startswith(f"{choice.lower()} ")
        for choice in SHORT_AFFIRMATIVE_PHRASES
    ):
        return True

    consent_choice = detect_consent_choice(
        text,
        current_stage=current_phase if current_phase in {OPENING, CONSENT_CHECK} else None,
    )
    return consent_choice == "granted"


def is_short_valid_intent(text: str) -> bool:
    normalized = _normalize_choice_text(text)
    if not normalized:
        return False

    if len(normalized.split()) > 8:
        return False

    return is_valid_short_response(text)


def build_opted_out_notice(language: str = "en-IN") -> str:
    if normalize_language(language) == "hi-IN":
        return "आपका नंबर मना सूची में है। हम इस स्वचालित कॉल को आगे नहीं बढ़ाएँगे। धन्यवाद।"
    return "Your number is marked as opted out. We will not continue this automated call. Thank you."


def detect_consent_choice(text: str, current_stage: str | None = None) -> ConsentChoice:
    normalized = _normalize_choice_text(text)
    if not normalized:
        return "unknown"

    if current_stage and current_stage not in {OPENING, CONSENT_CHECK}:
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

    send_link_markers = (
        "send link",
        "sms link",
        "send sms",
        "text me",
        "message me",
        "link bhejo",
        "sms bhejo",
        "लिंक भेजो",
        "लिंक भेज दीजिए",
        "sms भेजो",
        "मैसेज भेजो",
    )
    if any(marker in normalized for marker in send_link_markers):
        return "send_link"

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
        "yes ji",
        "haan",
        "ha",
        "bilkul",
        "okay",
        "ok",
        "sure",
        "correct",
        "speaking",
        "hello",
        "हलो",
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
    if choice in {"callback", "send_link", "opt_out"}:
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


def next_phase_after_address_capture() -> CallPhase:
    return CIBIL_FETCH


def next_phase_after_cibil_fetch() -> CallPhase:
    return OFFER_ELIGIBILITY


def next_phase_after_card_selection() -> CallPhase:
    return E_CONSENT


def next_phase_after_e_consent() -> CallPhase:
    return VKYC_PENDING


def _normalize_choice_text(text: str) -> str:
    normalized = (text or "").lower().strip()
    normalized = re.sub(r"[।,.!?;:]+", " ", normalized)
    normalized = re.sub(r"[^\w\s\u0900-\u097F]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _looks_like_identity_name_confirmation(normalized_text: str) -> bool:
    # Accept "my name is ..." style replies.
    if any(marker in normalized_text for marker in ("मेरा नाम", "mera naam", "my name", "name is")):
        return True

    # Name-like replies should not contain digits.
    if any(char.isdigit() for char in normalized_text):
        return False

    tokens = normalized_text.split()
    if not tokens or len(tokens) > 3:
        return False
    if any(token in IDENTITY_NAME_STOPWORDS for token in tokens):
        return False

    # Require alphabetic words (Latin/Devanagari) to avoid treating random symbols as names.
    if not all(token.isalpha() for token in tokens):
        return False
    if any(len(token) < 2 for token in tokens):
        return False
    return any(len(token) >= 3 for token in tokens)


def _contains_latin_text(text: str) -> bool:
    return any("a" <= char.lower() <= "z" for char in text)


def _normalize_name(name: str) -> str:
    return " ".join(name.strip().split())


def _build_hindi_salutation(name: str) -> str:
    normalized_name = _normalize_hindi_name(name)
    if not normalized_name:
        return "नमस्ते।"
    return f"नमस्ते {normalized_name}।"


def _build_hindi_ack(name: str) -> str:
    normalized_name = _normalize_hindi_name(name)
    return f"ठीक है {normalized_name}।" if normalized_name else "ठीक है।"


def _normalize_hindi_name(name: str) -> str:
    clean_name = _normalize_name(name)
    if not clean_name:
        return ""
    # Use the actual customer-provided name dynamically.
    # If the name is already in Devanagari, keep it as-is.
    # If it's in Latin script, keep it readable for TTS rather than dropping it.
    if _contains_latin_text(clean_name):
        return " ".join(part.capitalize() for part in clean_name.split())
    return clean_name


def build_user_context(
    name: str,
    language: str,
    session_data: dict | None = None,
) -> str:
    """Build per-call context block for runtime prompt generation."""
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
        "The line seems noisy, so keep the reply very short and ask only one simple next-step question."
        if response_mode == "noisy"
        else "Keep the reply short and natural for live voice playback."
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
        "Reply to the latest user intent only. If interrupted, do not continue the previous thread.\n"
        "Acknowledge naturally first, then guide the next single step.\n"
        "Ask only one question at a time.\n"
        "Use only verified context. Do not fabricate offers, benefits, timelines, or status.\n"
        "Follow the caller's active language for this turn.\n"
        f"{style_hint}\n"
        "Keep brand text exactly as 'BOB Card'.\n"
        "If escalation or callback is requested, offer it naturally but do not claim internal actions are already completed.\n"
        "Do not use markdown, labels, bullets, numbering, or long explanations.\n\n"
        f"{context_block}\n\n"
        "[RECENT CONVERSATION]\n"
        f"{history_block}"
    )


def _style_hint(preferred_language: str, response_style: str) -> str:
    normalized = normalize_language(preferred_language)
    if normalized == "hi-IN":
        if response_style == "hinglish":
            return (
                "For Hindi/Hinglish callers, reply strictly in Devanagari Hindi only. "
                "Do not use Roman Hindi. Keep sentences short and natural. "
                "Use Latin script only when required for: BOB Card, OTP, PAN, Aadhaar, SMS."
            )
        return (
            "Reply strictly in Devanagari Hindi only. "
            "Do not use Roman Hindi. Keep sentences short and natural. "
            "Use Latin script only when required for: BOB Card, OTP, PAN, Aadhaar, SMS."
        )
    return "Reply in clear English with short natural spoken sentences."


def _describe_language(language: str, style_hint: str) -> str:
    normalized = normalize_language(language)
    if normalized == "hi-IN":
        if style_hint:
            return f"hi-IN/Hinglish caller context. {style_hint} Switch immediately if caller changes language."
        return (
            "hi-IN/Hinglish caller context. Reply in Devanagari Hindi only. "
            "Do not use Roman Hindi. Use Latin script only for: BOB Card, OTP, PAN, Aadhaar, SMS. "
            "Switch immediately if caller changes language."
        )
    if normalized == "en-IN":
        return "en-IN caller context. Reply in clear English. Switch immediately if caller changes language."
    return f"{normalized} caller context. Switch immediately if caller changes language."
