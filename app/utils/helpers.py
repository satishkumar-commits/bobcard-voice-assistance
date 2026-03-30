import re
from datetime import UTC, datetime
from urllib.parse import urlparse, urlunparse
from pathlib import Path
from uuid import uuid4


DEVANAGARI_PATTERN = re.compile(r"[\u0900-\u097F]")
BENGALI_PATTERN = re.compile(r"[\u0980-\u09FF]")
LATIN_PATTERN = re.compile(r"[A-Za-z]")
LATIN_WORD_PATTERN = re.compile(r"\b[A-Za-z]+\b")
ROMANIZED_HINDI_HINTS = {
    "mujhe",
    "mera",
    "meri",
    "main",
    "mai",
    "mein",
    "me",
    "aap",
    "ap",
    "kripya",
    "haan",
    "haanji",
    "han",
    "ha",
    "ji",
    "nahi",
    "nahi",
    "nahin",
    "aadhaar",
    "aadhar",
    "dobara",
    "karne",
    "karna",
    "karo",
    "kiya",
    "kya",
    "kyu",
    "kyon",
    "kab",
    "ab",
    "abhi",
    "yahaan",
    "yahan",
    "wahan",
    "yah",
    "yeh",
    "vo",
    "woh",
    "rahi",
    "raha",
    "hai",
    "hu",
    "hun",
    "hoon",
    "hoga",
    "hogi",
    "gaya",
    "gayi",
    "hua",
    "hui",
    "wala",
    "wali",
    "isme",
    "usme",
    "krdo",
    "kardo",
    "kr diya",
    "ho gaya",
}
HINGLISH_HINTS = {
    "otp",
    "password",
    "login",
    "refund",
    "statement",
    "invoice",
    "error",
    "app",
    "emi",
    "reference",
    "ओटीपी",
    "पासवर्ड",
    "लॉगिन",
    "रिफंड",
    "स्टेटमेंट",
    "इनवॉइस",
    "एरर",
    "ऐप",
    "ईएमआई",
    "इज",
    "इनकरेक्ट",
    "रीड",
    "डाउनलोड",
    "अपलोड",
    "वी",
    "नॉट",
    "एबल",
    "रीसेंड",
    "मैसेज",
    "वी",
    "आर",
    "टू",
    "रीड",
    "बोलो",
    "आई",
    "यस",
    "जस्ट",
    "वांटेड",
    "नो",
    "व्हाट",
    "सोल्यूशन",
    "प्रोवाइड",
    "यू",
    "आर",
    "लैंग्वेज",
    "डिटेक्टर",
}
ENGLISH_WORD_HINTS = {
    "hello",
    "bank",
    "banking",
    "solution",
    "solutions",
    "provide",
    "provided",
    "want",
    "wanted",
    "know",
    "what",
    "card",
    "credit",
    "login",
    "password",
    "statement",
    "invoice",
    "refund",
    "application",
    "status",
}

DEVANAGARI_TECHNICAL_REPLACEMENTS = (
    (re.compile(r"\bbobcards\b", re.IGNORECASE), "बीओबी कार्ड्स"),
    (re.compile(r"\bbob\s*card\b", re.IGNORECASE), "बीओबी कार्ड"),
    (re.compile(r"\bcredit\s*card\b", re.IGNORECASE), "क्रेडिट कार्ड"),
    (re.compile(r"\botp\b", re.IGNORECASE), "ओटीपी"),
    (re.compile(r"\btransaction\b", re.IGNORECASE), "ट्रांजैक्शन"),
    (re.compile(r"\bapplication\b", re.IGNORECASE), "आवेदन"),
    (re.compile(r"\bbanking\b", re.IGNORECASE), "बैंकिंग"),
    (re.compile(r"\blog[\s-]*in\b", re.IGNORECASE), "लॉगिन"),
    (re.compile(r"\bsign[\s-]*in\b", re.IGNORECASE), "साइन इन"),
    (re.compile(r"\bpassword\b", re.IGNORECASE), "पासवर्ड"),
    (re.compile(r"\bstatement\b", re.IGNORECASE), "स्टेटमेंट"),
    (re.compile(r"\binvoice\b", re.IGNORECASE), "इनवॉइस"),
    (re.compile(r"\brefund\b", re.IGNORECASE), "रिफंड"),
    (re.compile(r"\bemi\b", re.IGNORECASE), "ईएमआई"),
    (re.compile(r"\berror\b", re.IGNORECASE), "एरर"),
    (re.compile(r"\bapp\b", re.IGNORECASE), "ऐप"),
    (re.compile(r"\bupload\b", re.IGNORECASE), "अपलोड"),
    (re.compile(r"\bdownload\b", re.IGNORECASE), "डाउनलोड"),
    (re.compile(r"\bstatus\b", re.IGNORECASE), "स्थिति"),
    (re.compile(r"\bstep\b", re.IGNORECASE), "चरण"),
    (re.compile(r"\bprocess\b", re.IGNORECASE), "प्रक्रिया"),
    (re.compile(r"\bsms\b", re.IGNORECASE), "एसएमएस"),
    (re.compile(r"\blink\b", re.IGNORECASE), "लिंक"),
    (re.compile(r"\bcallback\b", re.IGNORECASE), "कॉलबैक"),
    (re.compile(r"\baadhaar\b|\baadhar\b", re.IGNORECASE), "आधार"),
    (re.compile(r"\bpan\b", re.IGNORECASE), "पैन"),
    (re.compile(r"\bphoto\b", re.IGNORECASE), "फोटो"),
    (re.compile(r"\bblur\b", re.IGNORECASE), "धुंधली"),
    (re.compile(r"\bhelp\b", re.IGNORECASE), "मदद"),
    (re.compile(r"\bissue\b", re.IGNORECASE), "समस्या"),
    (re.compile(r"\bai\b", re.IGNORECASE), "एआई"),
    (re.compile(r"\bvoice\b", re.IGNORECASE), "वॉइस"),
    (re.compile(r"\bassistant\b", re.IGNORECASE), "सहायक"),
    (re.compile(r"\bquality\b", re.IGNORECASE), "गुणवत्ता"),
    (re.compile(r"\btraining\b", re.IGNORECASE), "प्रशिक्षण"),
    (re.compile(r"\brecord(?:ed|ing)?\b", re.IGNORECASE), "रिकॉर्ड"),
    (re.compile(r"\bcall\b", re.IGNORECASE), "कॉल"),
    (re.compile(r"\bexactly\b", re.IGNORECASE), "ठीक-ठीक"),
    (re.compile(r"\baapko\b", re.IGNORECASE), "आपको"),
    (re.compile(r"\bagar\b", re.IGNORECASE), "अगर"),
    (re.compile(r"\baur\b", re.IGNORECASE), "और"),
    (re.compile(r"\bkuch\b", re.IGNORECASE), "कुछ"),
    (re.compile(r"\bchahiye\b", re.IGNORECASE), "चाहिए"),
    (re.compile(r"\bbataiyega\b", re.IGNORECASE), "बताइएगा"),
    (re.compile(r"\btoh\b", re.IGNORECASE), "तो"),
    (re.compile(r"\bhai\b", re.IGNORECASE), "है"),
    (re.compile(r"\bkarke\b", re.IGNORECASE), "करके"),
    (re.compile(r"\bkhushi\b", re.IGNORECASE), "खुशी"),
    (re.compile(r"\bhui\b", re.IGNORECASE), "हुई"),
)


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def contains_devanagari(text: str) -> bool:
    return bool(DEVANAGARI_PATTERN.search(text))


def contains_bengali(text: str) -> bool:
    return bool(BENGALI_PATTERN.search(text))


def contains_latin(text: str) -> bool:
    return bool(LATIN_PATTERN.search(text))


def looks_like_romanized_hindi(text: str) -> bool:
    normalized = " ".join(re.sub(r"[^A-Za-z\s]", " ", text.lower()).split())
    if not normalized:
        return False

    tokens = normalized.split()
    hits = sum(1 for token in tokens if token in ROMANIZED_HINDI_HINTS)
    return hits >= 2


def looks_like_hinglish(text: str) -> bool:
    normalized = " ".join(re.sub(r"[^A-Za-z\s]", " ", text.lower()).split())
    if not normalized:
        return False

    tokens = normalized.split()
    hindi_hits = sum(1 for token in tokens if token in ROMANIZED_HINDI_HINTS)
    english_hits = sum(1 for token in tokens if token in ENGLISH_WORD_HINTS or token in HINGLISH_HINTS)

    if hindi_hits >= 2:
        return True
    return hindi_hits >= 1 and english_hits >= 1


def infer_language_code(text: str, stt_language: str | None = None, preferred_language: str | None = None) -> str:
    supported = {"hi-IN", "en-IN"}
    normalized_latin = " ".join(re.sub(r"[^A-Za-z\s]", " ", (text or "").lower()).split())
    english_hits = sum(1 for token in normalized_latin.split() if token in ENGLISH_WORD_HINTS)
    is_hinglish = looks_like_hinglish(text)

    if contains_devanagari(text):
        return "hi-IN"

    if preferred_language == "hi-IN" and (is_hinglish or looks_like_romanized_hindi(text) or contains_bengali(text)):
        return "hi-IN"

    if normalized_latin and english_hits >= 2 and not is_hinglish and not looks_like_romanized_hindi(text):
        return "en-IN"

    if stt_language == "en-IN" and normalized_latin and not is_hinglish and not looks_like_romanized_hindi(text):
        return "en-IN"
    if stt_language == "hi-IN":
        return "hi-IN"
    if stt_language in supported:
        return stt_language

    if is_hinglish:
        return "hi-IN"

    if normalized_latin and not looks_like_romanized_hindi(text):
        return "en-IN"

    if preferred_language in supported:
        return preferred_language

    if looks_like_romanized_hindi(text):
        return "hi-IN"
    if LATIN_PATTERN.search(text):
        return "en-IN"
    return "en-IN"


def detect_response_style(text: str, preferred_language: str | None = None, current_style: str = "default") -> str:
    if preferred_language != "hi-IN":
        return "default"

    normalized = " ".join(re.sub(r"[^\w\s\u0900-\u097F]", " ", (text or "").lower()).split())
    if not normalized:
        return current_style

    if looks_like_romanized_hindi(text):
        return "hinglish"

    if looks_like_hinglish(text):
        return "hinglish"

    if contains_devanagari(text) and LATIN_PATTERN.search(text):
        return "hinglish"

    if any(hint in normalized for hint in HINGLISH_HINTS):
        return "hinglish"

    return current_style if current_style == "hinglish" else "default"


def apply_response_style(text: str, language_code: str, response_style: str) -> str:
    if language_code != "hi-IN" or response_style != "hinglish":
        return text

    styled = text
    replacements = (
        ("मैं एक-एक कदम में मदद करूँगी।", "मैं step by step help करूँगी।"),
        ("मैं step by step मदद करूँगी।", "मैं step by step help करूँगी।"),
        ("अभी सिर्फ बताइए कि आप कहाँ अटके हैं,", "अब बताइए कि आप कहाँ stuck हैं,"),
        ("आधार", "Aadhaar"),
        ("पैन", "PAN"),
        ("आवेदन की स्थिति", "application status"),
        ("रेफरेंस विवरण", "reference details"),
        ("रेफरेंस", "reference"),
        ("ओटीपी", "OTP"),
        ("लॉगिन", "login"),
        ("साइन इन", "sign in"),
        ("इनवॉइस", "invoice"),
        ("स्टेटमेंट", "statement"),
        ("ऐप", "app"),
        ("एरर मैसेज", "error message"),
        ("एरर", "error"),
        ("रिफंड", "refund"),
        ("ईएमआई", "EMI"),
        ("पासवर्ड", "password"),
        ("चरण", "step"),
        ("इंटरनेट कनेक्शन", "internet connection"),
        ("संदेश इनबॉक्स", "SMS inbox"),
        ("अनुरोध", "request"),
        ("सेक्शन", "section"),
        ("विकल्प", "option"),
        ("डाउनलोड", "download"),
        ("अपलोड", "upload"),
        ("डॉक्यूमेंट्स", "documents"),
        ("दस्तावेज़", "document"),
        ("पोर्टल", "portal"),
        ("जाँचिए", "check kijiye"),
        ("ताज़ा कीजिए", "refresh kijiye"),
        ("सत्यापित कीजिए", "verify kijiye"),
    )
    for source, target in replacements:
        styled = styled.replace(source, target)
    return styled


def enforce_devanagari_hindi_reply(text: str, max_sentences: int = 3) -> str:
    fallback = "मैं आपकी बीओबी कार्ड सहायता के लिए तैयार हूँ। कृपया अपनी समस्या संक्षेप में बताइए।"
    cleaned = " ".join((text or "").strip().split())
    if not cleaned:
        return fallback

    normalized = cleaned
    for pattern, replacement in DEVANAGARI_TECHNICAL_REPLACEMENTS:
        normalized = pattern.sub(replacement, normalized)

    normalized = re.sub(r"[.]+", "।", normalized)
    parts = [part.strip(" ,;:") for part in re.split(r"[।!?]+", normalized) if part.strip(" ,;:")]
    if not parts:
        return fallback

    sentence_limit = max(1, min(max_sentences, 3))
    normalized = "। ".join(parts[:sentence_limit]).strip(" ,;:")
    if normalized and not normalized.endswith("।"):
        normalized += "।"

    protected_name_tokens: dict[str, str] = {}
    name_token_index = 0

    def _protect_names(pattern: re.Pattern[str], value: str) -> str:
        nonlocal name_token_index

        def replacer(match: re.Match[str]) -> str:
            nonlocal name_token_index
            raw_name = " ".join((match.group("name") or "").split()).strip()
            if not raw_name:
                return match.group(0)
            placeholder = f"नामटोकन{name_token_index}"
            name_token_index += 1
            protected_name_tokens[placeholder] = raw_name
            return match.group(0).replace(raw_name, placeholder, 1)

        return pattern.sub(replacer, value)

    # Keep customer names intact in Hindi prompts where names may still be in Latin script.
    normalized = _protect_names(re.compile(r"(?P<name>[A-Za-z][A-Za-z\s]{0,40})(?=\s+जी)"), normalized)
    normalized = _protect_names(re.compile(r"(?<=नमस्ते\s)(?P<name>[A-Za-z][A-Za-z\s]{0,40})(?=।|,|$)"), normalized)

    if contains_latin(normalized):
        for pattern, replacement in DEVANAGARI_TECHNICAL_REPLACEMENTS:
            normalized = pattern.sub(replacement, normalized)
        normalized = LATIN_WORD_PATTERN.sub("", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip(" ,;:")
        if normalized and not normalized.endswith("।"):
            normalized += "।"

    for placeholder, raw_name in protected_name_tokens.items():
        normalized = normalized.replace(placeholder, raw_name)

    normalized = re.sub(r"(।\s*){2,}", "। ", normalized).strip(" ,;:")
    if normalized and not normalized.endswith("।"):
        normalized += "।"

    devanagari_words = re.findall(r"[\u0900-\u097F]+", normalized)
    if len(devanagari_words) < 2:
        return fallback

    if not contains_devanagari(normalized):
        return fallback

    return sanitize_spoken_text(normalized, max_length=220)


def sanitize_spoken_text(text: str, max_length: int = 280) -> str:
    cleaned = " ".join(text.strip().split())
    if len(cleaned) > max_length:
        return cleaned[: max_length - 3].rstrip() + "..."
    return cleaned


def build_public_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def build_websocket_url(base_url: str, path: str) -> str:
    parsed = urlparse(base_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    normalized_path = "/" + path.lstrip("/")
    return urlunparse(
        (
            scheme,
            parsed.netloc,
            normalized_path,
            "",
            "",
            "",
        )
    )


def generate_audio_filename(call_sid: str) -> str:
    return f"{call_sid}-{uuid4().hex}.mp3"


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
