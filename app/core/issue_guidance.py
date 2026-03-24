import re
from typing import Literal

from app.core.conversation_prompts import normalize_language


IssueType = Literal[
    "pan_upload",
    "aadhaar_upload",
    "photo_upload",
    "document_upload",
    "application_error_issue",
    "invoice_issue",
    "statement_issue",
    "refund_issue",
    "card_block_issue",
    "address_update_issue",
    "emi_issue",
    "otp_issue",
    "login_issue",
    "application_status_issue",
    "generic_process_help",
]

IssueSymptom = Literal[
    "error_message",
    "upload_blocked",
    "blurred_image",
    "incorrect_details",
    "not_found",
    "access_issue",
    "unknown",
]

UPLOAD_ISSUE_TYPES = {"pan_upload", "aadhaar_upload", "photo_upload", "document_upload"}

_NON_WORD_PATTERN = re.compile(r"[^\w\s\u0900-\u097F]+")

_ACK_CHOICES = {
    "haan",
    "haan ji",
    "haanji",
    "ha ji",
    "हाँ",
    "हाँ जी",
    "हां",
    "हां जी",
    "जी हाँ",
    "जी हां",
    "yes",
    "yes ji",
    "ji",
    "ok",
    "okay",
}

_GREETING_CHOICES = {
    "hello",
    "hi",
    "hey",
    "namaste",
    "नमस्ते",
    "hello ji",
    "hi ji",
}

_FRUSTRATION_KEYWORDS = (
    "samajh nahi",
    "samaj nahi",
    "sun nahi",
    "sunn nahi",
    "you are not understanding",
    "not understanding",
    "not hearing",
    "can't hear",
    "cannot hear",
    "समझ नहीं",
    "सुन नहीं",
    "बात नहीं सुन",
)

_GENERIC_HELP_KEYWORDS = (
    "issue",
    "problem",
    "stuck",
    "upload",
    "document",
    "kyc",
    "error",
    "प्रॉब्लम",
    "समस्या",
    "दिक्कत",
    "अटक",
    "अपलोड",
    "दस्तावेज",
    "केवाईसी",
    "एरर",
)
_GENERAL_BANKING_QUESTION_KEYWORDS = (
    "banking solution",
    "banking solutions",
    "what do you provide",
    "what do you offer",
    "what services",
    "which services",
    "service do you provide",
    "solutions do you provide",
    "credit card features",
    "credit card service",
    "bank solution",
    "bank services",
    "बैंकिंग सोल्यूशन",
    "कौन सी सेवा",
    "क्या सेवा",
    "क्या सुविधा",
    "क्या सोल्यूशन",
    "क्या प्रोवाइड",
    "कौन सी सुविधा",
)

_ROMANIZED_HINDI_HINTS = {
    "mujhe",
    "mera",
    "meri",
    "main",
    "aap",
    "kripya",
    "haan",
    "nahi",
    "aadhaar",
    "aadhar",
    "dobara",
    "karna",
    "karne",
    "problem",
    "aa",
    "rahi",
    "hai",
}


def build_process_resume_context_reply(
    *,
    language: str = "en-IN",
    pending_step: str | None = None,
) -> str:
    language = normalize_language(language)
    if language == "hi-IN":
        if pending_step:
            return (
                f"आपकी BOBCards credit card application में '{pending_step}' step pending है। "
                "मैं उसी step को पूरा कराने में मदद कर रही हूँ।"
            )
        return (
            "आपकी BOBCards credit card application बीच में रुक गई थी। "
            "मैं pending step पूरा कराने में मदद के लिए कॉल कर रही हूँ।"
        )

    if pending_step:
        return (
            f"Your BOBCards credit card application is pending at '{pending_step}'. "
            "I am calling to help you complete this step."
        )
    return (
        "Your BOBCards credit card application was left incomplete. "
        "I am calling to help you complete the pending step."
    )


def normalize_issue_text(text: str) -> str:
    lowered = text.strip().lower()
    cleaned = _NON_WORD_PATTERN.sub(" ", lowered)
    return " ".join(cleaned.split())


def is_simple_acknowledgement(text: str) -> bool:
    normalized = normalize_issue_text(text)
    if not normalized:
        return False
    if normalized in _ACK_CHOICES:
        return True

    tokens = normalized.split()
    if not tokens:
        return False

    allowed_tokens = {"haan", "ji", "yes", "ok", "okay", "हाँ", "जी", "हां"}
    return len(tokens) <= 6 and all(token in allowed_tokens for token in tokens)


def is_opening_response(text: str) -> bool:
    normalized = normalize_issue_text(text)
    if not normalized:
        return False
    if normalized in _GREETING_CHOICES:
        return True
    return is_simple_acknowledgement(text)


def looks_like_repeated_acknowledgement(text: str) -> bool:
    normalized = normalize_issue_text(text)
    tokens = normalized.split()
    if len(tokens) < 3:
        return False

    unique_tokens = set(tokens)
    if len(unique_tokens) > 2:
        return False

    if any(any(char.isdigit() for char in token) for token in unique_tokens):
        return False

    return max(tokens.count(token) for token in unique_tokens) >= 3


def collapse_repeated_acknowledgement(text: str, language: str = "hi-IN") -> str:
    normalized = normalize_issue_text(text)
    if not looks_like_repeated_acknowledgement(normalized):
        return text
    return "हाँ जी" if normalize_language(language) == "hi-IN" else "yes"


def looks_like_romanized_hindi(text: str) -> bool:
    normalized = normalize_issue_text(text)
    if not normalized:
        return False

    tokens = normalized.split()
    hits = sum(1 for token in tokens if token in _ROMANIZED_HINDI_HINTS)
    return hits >= 2


def detect_issue_type(text: str) -> IssueType | None:
    normalized = normalize_issue_text(text)
    if not normalized:
        return None

    if _contains_any(normalized, ("aadhaar", "aadhar", "आधार")):
        return "aadhaar_upload"
    if _contains_any(normalized, ("pan", "पैन")):
        return "pan_upload"
    if _contains_any(normalized, ("photo", "selfie", "face", "फोटो", "सेल्फी", "चेहरा")):
        return "photo_upload"
    if _contains_any(
        normalized,
        (
            "application error",
            "app error",
            "technical error",
            "app not working",
            "application not working",
            "app crash",
            "app crashed",
            "server error",
            "application issue",
            "ऐप एरर",
            "एप्लिकेशन एरर",
            "टेक्निकल एरर",
            "ऐप नहीं चल",
            "ऐप काम नहीं",
            "ऐप क्रैश",
            "server issue",
        ),
    ):
        return "application_error_issue"
    if _contains_any(normalized, ("statement", "e statement", "estat", "bill copy", "statement copy", "स्टेटमेंट", "बिल कॉपी")):
        return "statement_issue"
    if _contains_any(normalized, ("invoice", "bill", "receipt", "इनवॉइस", "बिल", "रसीद")):
        return "invoice_issue"
    if _contains_any(normalized, ("refund", "reversal", "merchant refund", "रिफंड", "रिवर्सल")):
        return "refund_issue"
    if _contains_any(normalized, ("block card", "card block", "unblock card", "card unblock", "hotlist", "lost card", "stolen card", "ब्लॉक", "अनब्लॉक", "खो गया", "चोरी")):
        return "card_block_issue"
    if _contains_any(normalized, ("address update", "change address", "current address", "permanent address", "पता बदल", "एड्रेस", "पते")):
        return "address_update_issue"
    if _contains_any(normalized, ("emi", "easy emi", "installment", "किस्त", "ईएमआई")):
        return "emi_issue"
    if _contains_any(normalized, ("otp", "one time password", "ओटीपी")):
        return "otp_issue"
    if _contains_any(normalized, ("login", "sign in", "signin", "log in", "password", "incorrect password", "लॉगिन", "लॉग इन", "साइन इन", "पासवर्ड")):
        return "login_issue"
    if _contains_any(normalized, ("status", "application status", "track", "स्टेटस", "स्थिति", "ट्रैक")):
        return "application_status_issue"
    if _contains_any(normalized, ("upload", "document", "pdf", "image", "scan", "अपलोड", "दस्तावेज", "डॉक्यूमेंट", "इमेज", "स्कैन")):
        return "document_upload"
    if _contains_any(normalized, _GENERIC_HELP_KEYWORDS):
        return "generic_process_help"
    return None


def build_issue_help_reply(issue_type: IssueType, language: str = "en-IN") -> str:
    language = normalize_language(language)

    if language == "hi-IN":
        replies = {
            "pan_upload": "कोई बात नहीं, PAN step में दिक्कत common है। PAN की clear photo लेकर फिर से upload कीजिए।",
            "aadhaar_upload": "ठीक है, मैं साथ हूँ। Aadhaar की साफ़ और सीधी photo चुनकर दोबारा upload कीजिए।",
            "photo_upload": "समझ गई। अच्छी रोशनी में clear selfie लेकर फिर से upload कीजिए।",
            "application_error_issue": "ठीक है। app एक बार बंद करके फिर खोलिए और वही step फिर से continue कीजिए।",
            "statement_issue": "कोई समस्या नहीं। statement section खोलकर refresh कीजिए, अगर नहीं दिखे तो मैं next step बताती हूँ।",
            "invoice_issue": "ठीक है, invoice वाले section को refresh करके फिर check कीजिए।",
            "refund_issue": "समझ गई। refund reference से status दोबारा check कीजिए, मैं साथ हूँ।",
            "card_block_issue": "ठीक है, card controls में जाकर block या unblock option फिर से check कीजिए।",
            "address_update_issue": "कोई बात नहीं। address update flow खोलकर OTP verify कीजिए और request फिर submit कीजिए।",
            "emi_issue": "ठीक है। EMI option eligible transaction पर available होता है, अभी वही section check कीजिए।",
            "otp_issue": "समझ गई। inbox और network check करके resend OTP एक बार दबाइए। OTP किसी से share मत कीजिए।",
            "login_issue": "ठीक है, login में दिक्कत है। registered mobile और password या OTP details फिर से check कीजिए।",
            "application_status_issue": "कोई बात नहीं। tracking page refresh करके application status फिर check कीजिए।",
            "document_upload": "समझ गई। document की clear copy चुनकर दोबारा upload कीजिए।",
            "generic_process_help": "ठीक है। बस बताइए आप किस step पर अटके हैं, मैं वहीं से guide करूँगी।",
        }
        return replies[issue_type]

    replies = {
        "pan_upload": "No worries, PAN step issues are common. Please upload a clear PAN image again.",
        "aadhaar_upload": "I understand. Please upload a clear Aadhaar image again and we’ll continue.",
        "photo_upload": "Got it. Please retake a clear selfie in good light and upload again.",
        "application_error_issue": "Understood. Please reopen the app and continue the same step once again.",
        "statement_issue": "No problem. Please refresh the statement section and check again.",
        "invoice_issue": "Understood. Please refresh the invoice/documents section and check again.",
        "refund_issue": "I see. Please recheck refund status using your reference details.",
        "card_block_issue": "Sure. Please open card controls and check block or unblock options again.",
        "address_update_issue": "No worries. Please reopen address update flow, verify OTP, and submit again.",
        "emi_issue": "Understood. Please check EMI options on the eligible transaction again.",
        "otp_issue": "Please check inbox and network, then tap resend OTP once. Do not share OTP with anyone.",
        "login_issue": "Please verify registered mobile and password or OTP details, then sign in again.",
        "application_status_issue": "Please refresh the tracking page and check your application status again.",
        "document_upload": "Please choose a clear document image or PDF and upload again.",
        "generic_process_help": "Understood. Tell me the exact step where you are stuck and I’ll guide you from there.",
    }
    return replies[issue_type]


def detect_issue_symptom(text: str) -> IssueSymptom | None:
    normalized = normalize_issue_text(text)
    if not normalized:
        return None

    if _contains_any(normalized, ("error", "message", "err", "एरर", "मैसेज", "संदेश")):
        return "error_message"
    if _contains_any(normalized, ("blur", "blurry", "clear nahi", "not clear", "धुंध", "साफ नहीं", "ब्लर")):
        return "blurred_image"
    if _contains_any(normalized, ("wrong", "incorrect", "incorrect password", "password incorrect", "इनकरेक्ट", "correct nahi", "mismatch", "गलत", "मिलान नहीं", "करेक्ट नहीं")):
        return "incorrect_details"
    if _contains_any(
        normalized,
        (
            "password",
            "incorrect password",
            "not opening",
            "unable to open",
            "not able to open",
            "page not open",
            "page not opening",
            "page nahi khul",
            "page nahin khul",
            "screen not open",
            "portal not open",
            "site not open",
            "website not open",
            "nahi khul",
            "nahin khul",
            "नहीं खुल",
            "पेज नहीं खुल",
            "स्क्रीन नहीं खुल",
            "पोर्टल नहीं खुल",
            "वेबसाइट नहीं खुल",
            "unable to read",
            "not able to read",
            "read nahi",
            "रीड",
            "pdf नहीं खुल",
            "पासवर्ड",
            "खुल नहीं",
            "पढ़ नहीं",
        ),
    ):
        return "access_issue"
    if _contains_any(normalized, ("not found", "missing", "nahi mil", "nahin mil", "nahi dikh", "nahin dikh", "nahi aa", "nahin aa", "नहीं मिल", "नहीं दिख", "नहीं आ", "गायब")):
        return "not_found"
    if _contains_any(normalized, ("not upload", "not uploading", "upload nahi", "download nahi", "submit nahi", "not submitting", "not downloading", "stuck", "retry", "अपलोड नहीं", "डाउनलोड नहीं", "submit नहीं", "अटक", "फंस", "नहीं हो रहा")):
        return "upload_blocked"
    if _contains_any(normalized, ("pata nahi", "dont know", "don't know", "not sure", "पता नहीं", "मालूम नहीं")):
        return "unknown"
    return None


def build_issue_follow_up_question(issue_type: IssueType, language: str = "en-IN") -> str:
    language = normalize_language(language)
    if language == "hi-IN":
        prompts = {
            "aadhaar_upload": "ठीक है, Aadhaar step में exactly क्या हो रहा है: photo blur है, upload रुक रहा है, या error दिख रहा है?",
            "pan_upload": "समझ गई। PAN step में क्या issue है: photo clear नहीं, upload fail, या error message?",
            "photo_upload": "ठीक है। selfie step में दिक्कत blur है या upload रुक रहा है?",
            "application_error_issue": "ठीक है। app नहीं खुल रहा, crash हो रहा है, या कोई specific error दिख रहा है?",
            "statement_issue": "ठीक है। statement दिख नहीं रहा, download नहीं हो रहा, या open नहीं हो रहा?",
            "invoice_issue": "समझ गई। invoice missing है, download fail है, या error आ रहा है?",
            "refund_issue": "ठीक है। refund credit नहीं दिख रहा, delay है, या amount mismatch लग रहा है?",
            "card_block_issue": "ठीक है। block/unblock option नहीं मिल रहा, या error message दिख रहा है?",
            "address_update_issue": "ठीक है। OTP नहीं आ रहा, document upload fail है, या submit नहीं हो रहा?",
            "emi_issue": "ठीक है। EMI option नहीं दिख रहा, eligibility issue है, या submit fail हो रहा है?",
            "otp_issue": "समझ गई। OTP बिल्कुल नहीं आया, late आया, या resend के बाद भी नहीं मिला?",
            "login_issue": "ठीक है। login OTP step पर अटक रहा है, password issue है, या sign-in fail है?",
            "application_status_issue": "ठीक है। status नहीं दिख रहा, page नहीं खुल रहा, या details match नहीं कर रही?",
            "document_upload": "ठीक है। file upload नहीं हो रही, image unclear है, या error message आ रहा है?",
            "generic_process_help": "ठीक है। बस step का नाम बोलिए जहाँ आप अटके हैं।",
        }
        return prompts[issue_type]

    prompts = {
        "aadhaar_upload": "Understood. Is the Aadhaar issue a blurry image, a stuck upload, or an error message?",
        "pan_upload": "Got it. Is the PAN issue an unclear image, upload failure, or an error message?",
        "photo_upload": "Understood. Is the selfie issue blur, face not clear, or upload getting stuck?",
        "application_error_issue": "I see. Is the app not opening, crashing, or showing a specific error?",
        "statement_issue": "Understood. Is the statement missing, not downloading, or not opening?",
        "invoice_issue": "Got it. Is the invoice missing, failing to download, or showing an error?",
        "refund_issue": "Understood. Is the refund delayed, not credited, or amount not visible?",
        "card_block_issue": "I see. Is block or unblock option missing, or is there an error message?",
        "address_update_issue": "Understood. Is OTP missing, document upload failing, or request not submitting?",
        "emi_issue": "Got it. Is EMI option missing, eligibility not showing, or request not submitting?",
        "otp_issue": "Understood. Is OTP not received, delayed, or still missing after resend?",
        "login_issue": "I see. Is login stuck at OTP, password issue, or sign-in failure?",
        "application_status_issue": "Understood. Is status not visible, page not opening, or details mismatch?",
        "document_upload": "Got it. Is the document not uploading, unclear, or showing an error?",
        "generic_process_help": "Please tell me exactly which step you are stuck on.",
    }
    return prompts[issue_type]


def build_issue_resolution_reply(
    issue_type: IssueType,
    symptom: IssueSymptom,
    language: str = "en-IN",
) -> str:
    language = normalize_language(language)
    if language == "hi-IN":
        replies = {
            ("aadhaar_upload", "error_message"): "ठीक है, कोई बात नहीं। स्क्रीन पर जो error लिखा है, वही पढ़कर बताइए।",
            ("aadhaar_upload", "access_issue"): "समझ गई। अगर पूरा message नहीं पढ़ पा रहे, तो जो शब्द दिख रहे हैं वही बताइए।",
            ("aadhaar_upload", "blurred_image"): "बिल्कुल। Aadhaar की clear photo लेकर, सभी corners दिखाकर फिर upload कीजिए।",
            ("aadhaar_upload", "upload_blocked"): "ठीक है। app reopen कीजिए, network check कीजिए, फिर Aadhaar upload दोबारा कीजिए।",
            ("aadhaar_upload", "incorrect_details"): "लगता है details साफ़ नहीं दिख रहीं। नाम और DOB clear वाली image फिर से upload कीजिए।",
            ("pan_upload", "blurred_image"): "कोई बात नहीं। PAN की clear फोटो लेकर फिर upload कीजिए।",
            ("pan_upload", "upload_blocked"): "ठीक है। app फिर खोलकर PAN upload step दोबारा try कीजिए।",
            ("pan_upload", "error_message"): "समझ गई। PAN step पर जो error दिख रहा है, वह पढ़कर बताइए।",
            ("photo_upload", "blurred_image"): "ठीक है। अच्छी light में clear selfie लेकर दोबारा upload कीजिए।",
            ("photo_upload", "upload_blocked"): "कोई बात नहीं। नई selfie लेकर upload फिर से try कीजिए।",
            ("photo_upload", "incorrect_details"): "ठीक है। चेहरा center में रखकर बिना shadow की selfie upload कीजिए।",
            ("application_error_issue", "error_message"): "समझ गई। app पर दिख रहा error message बताइए, मैं next step बताती हूँ।",
            ("application_error_issue", "access_issue"): "ठीक है। app बंद करके फिर खोलिए और वही step दोबारा कीजिए।",
            ("application_error_issue", "upload_blocked"): "कोई बात नहीं। उसी request step को refresh करके फिर submit कीजिए।",
            ("statement_issue", "not_found"): "ठीक है। statement section refresh करके फिर check कीजिए।",
            ("statement_issue", "access_issue"): "समझ गई। statement file open नहीं हो रही तो password format फिर verify कीजिए।",
            ("invoice_issue", "not_found"): "कोई बात नहीं। documents/downloads section refresh करके invoice फिर check कीजिए।",
            ("invoice_issue", "error_message"): "ठीक है। invoice step का error message पढ़कर बताइए।",
            ("invoice_issue", "upload_blocked"): "समझ गई। network check करके invoice download फिर try कीजिए।",
            ("refund_issue", "not_found"): "ठीक है। refund reference से status दोबारा check कीजिए।",
            ("refund_issue", "error_message"): "समझ गई। refund से जुड़ा message या reference बताइए।",
            ("card_block_issue", "not_found"): "ठीक है। card controls खोलकर block/unblock option फिर देखिए।",
            ("card_block_issue", "error_message"): "कोई बात नहीं। card block/unblock वाला error बताइए।",
            ("address_update_issue", "access_issue"): "ठीक है। OTP verify करके address proof upload करें और submit फिर try करें।",
            ("address_update_issue", "upload_blocked"): "समझ गई। address proof की clear image/PDF चुनकर upload दोबारा कीजिए।",
            ("emi_issue", "not_found"): "ठीक है। eligible transaction खोलकर EMI option फिर check कीजिए।",
            ("emi_issue", "error_message"): "समझ गई। EMI request वाला error message बताइए।",
            ("otp_issue", "not_found"): "ठीक है। कुछ सेकंड रुककर resend OTP दबाइए और inbox check कीजिए। OTP share मत कीजिए।",
            ("otp_issue", "upload_blocked"): "कोई बात नहीं। app reopen करके OTP फिर request कीजिए। OTP किसी को मत बताइए।",
            ("login_issue", "error_message"): "ठीक है। login screen पर जो error है, वह पढ़कर बताइए।",
            ("login_issue", "access_issue"): "समझ गई। registered mobile और password/OTP details फिर check कीजिए।",
            ("login_issue", "incorrect_details"): "ठीक है। details ध्यान से फिर डालिए; जरूरत हो तो reset option use कीजिए।",
            ("login_issue", "not_found"): "कोई बात नहीं। app refresh करके sign-in page दोबारा खोलिए।",
            ("application_status_issue", "not_found"): "ठीक है। tracking page refresh करके status फिर check कीजिए।",
            ("application_status_issue", "error_message"): "समझ गई। status page पर दिख रहा error message बताइए।",
            ("application_status_issue", "access_issue"): "ठीक है। app या tracking page फिर खोलकर internet check के बाद status देखिए।",
            ("document_upload", "upload_blocked"): "कोई बात नहीं। file फिर चुनकर clear copy upload कीजिए।",
            ("document_upload", "error_message"): "ठीक है। document upload वाला error message बताइए।",
            ("document_upload", "access_issue"): "समझ गई। जो message पढ़ पा रहे हैं उतना बताइए, मैं उसी से guide करूँगी।",
            ("document_upload", "blurred_image"): "ठीक है। document की clear copy लेकर फिर upload कीजिए।",
        }
        return replies.get((issue_type, symptom), "ठीक है। अभी स्क्रीन पर exactly क्या दिख रहा है, वही बताइए।")

    replies = {
        ("aadhaar_upload", "error_message"): "No worries. Please read the Aadhaar error message and I’ll guide you immediately.",
        ("aadhaar_upload", "access_issue"): "If the full message is not visible, tell me the words you can see.",
        ("aadhaar_upload", "blurred_image"): "Please upload a clear Aadhaar image with all corners visible.",
        ("aadhaar_upload", "upload_blocked"): "Please reopen the app, check network, and upload Aadhaar again.",
        ("aadhaar_upload", "incorrect_details"): "Please use the Aadhaar image where name and date of birth are clearly visible.",
        ("pan_upload", "blurred_image"): "Please upload a clear PAN image with details readable.",
        ("pan_upload", "upload_blocked"): "Please reopen the app and retry PAN upload once.",
        ("pan_upload", "error_message"): "Please read the PAN upload error message.",
        ("photo_upload", "blurred_image"): "Please retake a clear selfie in good light and upload again.",
        ("photo_upload", "upload_blocked"): "Please retry selfie upload once after reopening the app.",
        ("photo_upload", "incorrect_details"): "Please keep your face centered and clear, then upload a new selfie.",
        ("application_error_issue", "error_message"): "Please share the exact app error message on screen.",
        ("application_error_issue", "access_issue"): "Please close and reopen the app, then continue the same step.",
        ("application_error_issue", "upload_blocked"): "Please refresh and submit the same step again.",
        ("statement_issue", "not_found"): "Please refresh the statement section and check again.",
        ("statement_issue", "access_issue"): "Please verify the statement file password format and retry.",
        ("invoice_issue", "not_found"): "Please refresh documents/downloads section and check invoice again.",
        ("invoice_issue", "error_message"): "Please read the invoice error message.",
        ("invoice_issue", "upload_blocked"): "Please check network and retry invoice download.",
        ("refund_issue", "not_found"): "Please recheck refund status using your refund reference.",
        ("refund_issue", "error_message"): "Please read the refund-related message or reference.",
        ("card_block_issue", "not_found"): "Please open card controls and check block/unblock option again.",
        ("card_block_issue", "error_message"): "Please read the block/unblock error message.",
        ("address_update_issue", "access_issue"): "Please verify OTP, upload address proof, and submit again.",
        ("address_update_issue", "upload_blocked"): "Please choose a clear address proof image/PDF and upload again.",
        ("emi_issue", "not_found"): "Please open eligible transaction and check EMI option again.",
        ("emi_issue", "error_message"): "Please read the EMI request error message.",
        ("otp_issue", "not_found"): "Please wait a few seconds, tap resend OTP once, and check SMS inbox. Do not share OTP.",
        ("otp_issue", "upload_blocked"): "Please reopen the app and request OTP again. Do not share OTP.",
        ("login_issue", "error_message"): "Please read the login error message.",
        ("login_issue", "access_issue"): "Please verify registered mobile and password/OTP details, then sign in again.",
        ("login_issue", "incorrect_details"): "Please re-enter details carefully. If needed, use reset option.",
        ("login_issue", "not_found"): "Please refresh app and reopen sign-in screen.",
        ("application_status_issue", "not_found"): "Please refresh tracking page and check status again.",
        ("application_status_issue", "error_message"): "Please read the application status error message.",
        ("application_status_issue", "access_issue"): "Please reopen tracking page, check network, and retry status lookup.",
        ("document_upload", "upload_blocked"): "Please reselect file and upload a clear copy.",
        ("document_upload", "error_message"): "Please read the document upload error message.",
        ("document_upload", "access_issue"): "If full message is not visible, share the visible words.",
        ("document_upload", "blurred_image"): "Please upload a clear document copy with all corners visible.",
    }
    return replies.get((issue_type, symptom), "Please tell me exactly what is visible on your screen right now.")


def looks_like_repair_request(text: str) -> bool:
    normalized = normalize_issue_text(text)
    if not normalized:
        return False
    return _contains_any(normalized, _FRUSTRATION_KEYWORDS)


def looks_like_general_banking_question(text: str) -> bool:
    normalized = normalize_issue_text(text)
    if not normalized:
        return False
    return _contains_any(normalized, _GENERAL_BANKING_QUESTION_KEYWORDS)


def build_repair_prompt(language: str = "en-IN") -> str:
    language = normalize_language(language)
    if language == "hi-IN":
        return "माफ़ कीजिए, मैं आपकी बात सही तरह से समझना चाहती हूँ। जिस जगह दिक्कत आ रही है, वही दोबारा बोलिए।"
    return "Sorry, I want to understand this correctly. Please say again where exactly the problem is happening."


def _contains_any(text: str, choices: tuple[str, ...]) -> bool:
    return any(choice in text for choice in choices)
