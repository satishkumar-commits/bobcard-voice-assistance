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
    "personal_details_mismatch",
    "max_attempts_exceeded",
    "age_ineligible",
    "technical_error",
    "aadhaar_pan_not_linked",
    "aadhaar_hindi_not_supported",
    "aadhaar_reverify",
    "aadhaar_verification_failure",
    "retry_after_30_days",
    "vkyc_pending",
    "vkyc_expired",
    "offer_eligible_no_docs",
    "bank_statement_required",
    "bank_not_found_manual_upload",
    "salaried_only",
    "card_selection_required",
    "e_consent_step",
    "vkyc_instructions",
    "application_complete",
    "resume_journey",
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
    "ठीक है",
    "थीक है",
    "theek hai",
    "thik hai",
    "जी बताइए",
    "ji batayiye",
    "ji bataiye",
    "hello",
    "हलो",
    "हेलो",
    "बोलिए",
    "bolo",
    "boliye",
    "speaking",
}

_GREETING_CHOICES = {
    "hello",
    "hi",
    "hey",
    "namaste",
    "नमस्ते",
    "hello ji",
    "hi ji",
    "हलो",
    "हेलो",
    "बोलिए",
    "bolo",
    "speaking",
}

_LOW_CONTENT_VALID_CHOICES = {
    "हाँ",
    "हां",
    "हाँ जी",
    "हां जी",
    "जी",
    "जी हाँ",
    "जी हां",
    "hello",
    "हलो",
    "हेलो",
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
    "bolo",
    "boliye",
    "बोलिए",
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
    "platinum card",
    "platinum",
    "card details",
    "card information",
    "card benefits",
    "card feature",
    "प्लेटिनम कार्ड",
    "कार्ड के बारे में",
    "कार्ड की जानकारी",
    "कार्ड डिटेल",
    "कार्ड लाभ",
    "कार्ड फीचर",
    "खासियत",
    "खासियतें",
    "features",
    "benefits",
    "card ki jankari",
    "card ki jankari chahiye",
    "card ke fayde",
    "कार्ड की खासियत",
    "कार्ड की खासियतें",
    "कार्ड की जानकारी",
    "कार्ड के फायदे",
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
            return f"ठीक है। अभी हम '{pending_step}' चरण पूरा करते हैं।"
        return "ठीक है। अब हम आपकी लंबित प्रक्रिया पूरी करते हैं।"

    if pending_step:
        return f"Okay. Let us complete the '{pending_step}' step now."
    return "Okay. Let us complete your pending process now."


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
    if normalized in _LOW_CONTENT_VALID_CHOICES:
        return True
    if any(normalized.startswith(f"{choice} ") for choice in _LOW_CONTENT_VALID_CHOICES):
        return True

    tokens = normalized.split()
    if not tokens:
        return False

    allowed_tokens = {"haan", "ji", "yes", "ok", "okay", "हाँ", "जी", "हां", "hello", "speaking", "bolo", "boliye"}
    return len(tokens) <= 6 and all(token in allowed_tokens for token in tokens)


def is_valid_low_content_turn(text: str) -> bool:
    normalized = normalize_issue_text(text)
    if not normalized:
        return False
    if normalized in _LOW_CONTENT_VALID_CHOICES:
        return True
    if any(normalized.startswith(f"{choice} ") for choice in _LOW_CONTENT_VALID_CHOICES):
        return True
    return is_simple_acknowledgement(normalized) or is_opening_response(normalized)


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

    if _contains_any(normalized, ("already has bob card", "already have bob card", "application rejected", "try again after 30 days", "30 day", "30 days")):
        return "retry_after_30_days"
    if _contains_any(normalized, ("pan dob mismatch", "pan and dob do not match", "dob mismatch", "date of birth mismatch")):
        return "personal_details_mismatch"
    if _contains_any(normalized, ("max attempts", "maximum attempts", "too many attempts", "24 hours")):
        return "max_attempts_exceeded"
    if _contains_any(normalized, ("minimum age 25", "age below 25", "not eligible by age", "age ineligible")):
        return "age_ineligible"
    if _contains_any(normalized, ("technical issue", "system issue", "api failure", "service unavailable", "temporarily unavailable")):
        return "technical_error"
    if _contains_any(normalized, ("aadhaar not linked", "aadhaar pan not linked", "link aadhaar with pan", "aadhaar pan link")):
        return "aadhaar_pan_not_linked"
    if _contains_any(normalized, ("aadhaar hindi not supported", "hindi not supported for aadhaar", "continue in english")):
        return "aadhaar_hindi_not_supported"
    if _contains_any(normalized, ("reverify aadhaar", "aadhaar reverify", "verify again", "re verification")):
        return "aadhaar_reverify"
    if _contains_any(normalized, ("uidai error", "aadhaar verification failed", "verification could not be completed")):
        return "aadhaar_verification_failure"
    if _contains_any(normalized, ("video kyc pending", "complete video kyc within 72 hours", "72 hours rule")):
        return "vkyc_pending"
    if _contains_any(normalized, ("video kyc expired", "vkyc expired", "72 hours expired", "restart application")):
        return "vkyc_expired"
    if _contains_any(normalized, ("eligible without documents", "no additional documents", "offer eligible")):
        return "offer_eligible_no_docs"
    if _contains_any(normalized, ("bank statement required", "need bank statement", "upload statement", "net banking")):
        return "bank_statement_required"
    if _contains_any(normalized, ("bank not listed", "bank not found", "manual upload")):
        return "bank_not_found_manual_upload"
    if _contains_any(normalized, ("salaried only", "only salaried")):
        return "salaried_only"
    if _contains_any(normalized, ("choose card option", "card selection", "select card")):
        return "card_selection_required"
    if _contains_any(normalized, ("e consent", "swipe right to proceed", "review details and swipe")):
        return "e_consent_step"
    if _contains_any(normalized, ("video kyc instructions", "original pan card ready", "plain light background", "allow location access")):
        return "vkyc_instructions"
    if _contains_any(
        normalized,
        ("application complete", "process complete", "thank you for choosing bank of baroda", "thank you for choosing bob card"),
    ):
        return "application_complete"
    if _contains_any(normalized, ("welcome back", "resume journey", "continue from where you left off")):
        return "resume_journey"

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
            "pan_upload": "समझ गई। PAN की साफ़ फोटो लेकर फिर से अपलोड कीजिए।",
            "aadhaar_upload": "ठीक है। Aadhaar की साफ़ और सीधी फोटो फिर से अपलोड कीजिए।",
            "photo_upload": "ठीक है। अच्छी रोशनी में साफ़ सेल्फी लेकर दोबारा अपलोड कीजिए।",
            "application_error_issue": "समझ गई। ऐप बंद करके फिर खोलिए, फिर वही चरण दोबारा कीजिए।",
            "statement_issue": "ठीक है। स्टेटमेंट सेक्शन रीफ्रेश करके फिर देखिए।",
            "invoice_issue": "समझ गई। इनवॉइस सेक्शन रीफ्रेश करके फिर जाँचिए।",
            "refund_issue": "ठीक है। रिफंड रेफरेंस से स्थिति फिर से जाँचिए।",
            "card_block_issue": "समझ गई। कार्ड कंट्रोल में ब्लॉक या अनब्लॉक विकल्प फिर देखें।",
            "address_update_issue": "ठीक है। पता अपडेट प्रक्रिया खोलकर OTP सत्यापित करें और अनुरोध भेजें।",
            "emi_issue": "समझ गई। जिस लेन-देन पर EMI चाहिए, वही पेज फिर देखें।",
            "otp_issue": "ठीक है। नेटवर्क और SMS इनबॉक्स जाँचकर OTP फिर से मंगाइए। OTP किसी से साझा न करें।",
            "login_issue": "समझ गई। पंजीकृत मोबाइल और पासवर्ड या OTP फिर से जाँचिए।",
            "application_status_issue": "ठीक है। ट्रैकिंग पेज रीफ्रेश करके स्थिति फिर देखिए।",
            "document_upload": "समझ गई। दस्तावेज़ की साफ़ कॉपी चुनकर दोबारा अपलोड कीजिए।",
            "generic_process_help": "ठीक है। आप किस चरण पर रुके हैं, बस वही बताइए।",
            "retry_after_30_days": "अभी आपका आवेदन आगे नहीं बढ़ सकता। कृपया 30 दिन बाद फिर प्रयास करें।",
            "personal_details_mismatch": "आपका PAN और जन्मतिथि रिकॉर्ड से मेल नहीं खा रहे। कृपया जाँचकर फिर प्रयास करें।",
            "max_attempts_exceeded": "आपके अधिकतम प्रयास पूरे हो चुके हैं। कृपया 24 घंटे बाद फिर कोशिश करें।",
            "age_ineligible": "न्यूनतम पात्र आयु 25 वर्ष है। अभी आप पात्र नहीं हैं।",
            "technical_error": "अभी सिस्टम में तकनीकी समस्या है। कृपया थोड़ी देर बाद फिर प्रयास करें।",
            "aadhaar_pan_not_linked": "आपका Aadhaar, PAN से लिंक नहीं है। कृपया लिंक करके फिर प्रयास करें।",
            "aadhaar_hindi_not_supported": "अभी Aadhaar verification हिंदी में उपलब्ध नहीं है। कृपया English में जारी रखें।",
            "aadhaar_reverify": "कृपया Aadhaar और PAN लिंक सही करके verification फिर से करें।",
            "aadhaar_verification_failure": "सिस्टम समस्या के कारण verification पूरा नहीं हो पाया। कृपया फिर कोशिश करें।",
            "vkyc_pending": "Aadhaar verification के बाद video KYC 72 घंटे में पूरा करें।",
            "vkyc_expired": "Video KYC समय पर पूरा नहीं हुआ। कृपया आवेदन फिर से शुरू करें।",
            "offer_eligible_no_docs": "अच्छी खबर, आप बिना अतिरिक्त दस्तावेज़ के offer के लिए पात्र हैं।",
            "bank_statement_required": "आगे बढ़ने के लिए bank statement चाहिए। net banking या manual upload चुनें।",
            "bank_not_found_manual_upload": "अगर bank सूची में नहीं है तो statement manual upload करें।",
            "salaried_only": "अभी यह प्रक्रिया केवल salaried customers के लिए उपलब्ध है।",
            "card_selection_required": "कृपया आगे बढ़ने के लिए एक card विकल्प चुनें।",
            "e_consent_step": "कृपया विवरण देखकर swipe right करें।",
            "vkyc_instructions": "Video KYC के लिए original PAN रखें, location on करें और plain background में बैठें।",
            "application_complete": "आपकी application प्रक्रिया पूरी हो गई है। धन्यवाद।",
            "resume_journey": "Welcome back। आप अपनी application वहीं से जारी कर सकते हैं जहाँ रुकी थी।",
        }
        return replies[issue_type]

    replies = {
        "pan_upload": "Got it. Please upload a clear PAN image again.",
        "aadhaar_upload": "Understood. Please upload a clear Aadhaar image again.",
        "photo_upload": "Okay. Please retake a clear selfie in good light.",
        "application_error_issue": "I understand. Please reopen the app and retry the same step.",
        "statement_issue": "Sure. Please refresh the statement section and check again.",
        "invoice_issue": "Understood. Please refresh the invoice section and check again.",
        "refund_issue": "Got it. Please recheck refund status with your reference.",
        "card_block_issue": "Okay. Please open card controls and check block or unblock options.",
        "address_update_issue": "Understood. Reopen address update, verify OTP, and submit again.",
        "emi_issue": "Sure. Please check EMI option on the eligible transaction again.",
        "otp_issue": "Please check network and SMS inbox, then request OTP again. Do not share OTP.",
        "login_issue": "Please verify registered mobile and password or OTP, then sign in again.",
        "application_status_issue": "Please refresh the tracking page and check status again.",
        "document_upload": "Please select a clear document image or PDF and upload again.",
        "generic_process_help": "Understood. Tell me the exact step where you are stuck.",
        "retry_after_30_days": "Sorry sir, at the moment we are unable to proceed with your application. You may try again after 30 days.",
        "personal_details_mismatch": "Sorry sir, your PAN and date of birth do not match our records. Please check and try again.",
        "max_attempts_exceeded": "You have reached the maximum number of attempts. Please try again after 24 hours.",
        "age_ineligible": "As per BOB Card policy, the minimum eligible age is 25 years. Currently, you do not meet this criteria.",
        "technical_error": "We are facing a technical issue at the moment. Kindly try again after some time and restart your journey.",
        "aadhaar_pan_not_linked": "We regret to inform you that your Aadhaar is not linked with your PAN card. Please link it and try again.",
        "aadhaar_hindi_not_supported": "Currently, Aadhaar verification is not available in Hindi. Please continue in English.",
        "aadhaar_reverify": "Please ensure your Aadhaar and PAN are linked correctly, then try the verification again.",
        "aadhaar_verification_failure": "Sorry, verification could not be completed due to a system issue. Please try again to continue the process.",
        "vkyc_pending": "After Aadhaar verification, please complete your video KYC within 72 hours.",
        "vkyc_expired": "Your application could not be completed because video KYC was not finished within 72 hours. Please restart the application to continue.",
        "offer_eligible_no_docs": "Good news, you are eligible for card offers without additional documents.",
        "bank_statement_required": "To continue, we need your bank statement. You can proceed through net banking or upload your statement manually.",
        "bank_not_found_manual_upload": "If your bank is not listed, you can upload your bank statement manually.",
        "salaried_only": "Currently, this process is available only for salaried customers.",
        "card_selection_required": "Please choose one of the available card options to continue.",
        "e_consent_step": "Please review the details and swipe right to proceed.",
        "vkyc_instructions": "For video KYC, please keep your original PAN card ready, allow location access, and sit in front of a plain light background.",
        "application_complete": "Your application process is complete. Thank you for choosing BOB Card.",
        "resume_journey": "Welcome back. You can continue your application from where you left off.",
    }
    return replies[issue_type]


def detect_issue_symptom(text: str) -> IssueSymptom | None:
    normalized = normalize_issue_text(text)
    if not normalized:
        return None

    if _contains_any(normalized, ("error", "message", "err", "एरर", "मैसेज", "संदेश")):
        return "error_message"
    if _contains_any(
        normalized,
        (
            "blur",
            "blurry",
            "clear nahi",
            "not clear",
            "धुंध",
            "साफ नहीं",
            "ब्लर",
            "photo acchi nahi",
            "photo achi nahi",
            "फोटो अच्छी नहीं",
            "फोटो अच्छी नही",
            "saaf nahi lag rahi",
            "साफ नहीं लग रही",
        ),
    ):
        return "blurred_image"
    if _contains_any(
        normalized,
        (
            "wrong",
            "incorrect",
            "incorrect password",
            "password incorrect",
            "इनकरेक्ट",
            "correct nahi",
            "mismatch",
            "गलत",
            "मिलान नहीं",
            "करेक्ट नहीं",
            "amount mismatch",
            "amount different",
            "amount less",
            "amount more",
            "राशि अलग",
            "अलग राशि",
            "कम राशि",
            "ज़्यादा राशि",
            "ज्यादा राशि",
            "होना चाहिए था",
            "should have been",
        ),
    ):
        return "incorrect_details"
    if any(ch.isdigit() for ch in normalized) and _contains_any(
        normalized,
        (
            "shown",
            "showing",
            "dikha",
            "dikh raha",
            "dikh rha",
            "दिख रहा",
            "दिख रही",
            "दिखा है",
        ),
    ):
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
    if _contains_any(
        normalized,
        (
            "upload ruk",
            "ruk raha",
            "ruk gaya",
            "not going",
            "not able to upload",
            "नहीं जा रहा",
            "नहीं जा रही",
            "रुक रहा",
            "रुक रही",
            "रुक गया",
            "रुक गई",
            "हो नहीं रहा",
            "हो नहीं रही",
            "नहीं हो पा",
        ),
    ):
        return "upload_blocked"
    if _contains_any(normalized, ("pata nahi", "dont know", "don't know", "not sure", "पता नहीं", "मालूम नहीं")):
        return "unknown"
    return None


def looks_like_issue_resolved_signal(text: str, issue_type: IssueType | None = None) -> bool:
    normalized = normalize_issue_text(text)
    if not normalized:
        return False

    strong_done_markers = (
        "resolved",
        "problem solved",
        "issue solved",
        "all set",
        "done",
        "complete",
        "completed",
        "ho gaya",
        "ho gya",
        "hogaya",
        "ठीक हो गया",
        "हल हो गया",
        "हल हो गई",
        "रिजॉल्व",
        "रिज़ॉल्व",
    )
    generic_negative_markers = (
        "not resolved",
        "resolve nahi",
        "resolved nahi",
        "नहीं हुआ",
        "नही हुआ",
        "नहीं हो रहा",
        "नही हो रहा",
        "pending",
        "stuck",
        "error",
        "failed",
    )
    if any(marker in normalized for marker in strong_done_markers) and not any(
        marker in normalized for marker in generic_negative_markers
    ):
        return True

    if issue_type == "otp_issue":
        otp_positive_markers = (
            "otp mil gaya",
            "otp aa gaya",
            "otp received",
            "received otp",
            "ओटीपी मिल गया",
            "ओटीपी आ गया",
            "ओटीपी मिल गया है",
            "ओटीपी आ गया है",
            "sms mil gaya",
            "sms aa gaya",
            "message mil gaya",
            "मैसेज मिल गया",
            "संदेश मिल गया",
        )
        otp_negative_markers = (
            "otp nahi mila",
            "otp nahin mila",
            "otp nahi aa",
            "otp not received",
            "not received otp",
            "ओटीपी नहीं मिला",
            "ओटीपी नही मिला",
            "ओटीपी नहीं आया",
            "ओटीपी नही आया",
            "invalid otp",
            "गलत otp",
            "ओटीपी गलत",
        )
        return any(marker in normalized for marker in otp_positive_markers) and not any(
            marker in normalized for marker in otp_negative_markers
        )

    return False


def build_issue_follow_up_question(
    issue_type: IssueType,
    language: str = "en-IN",
    *,
    follow_up_count: int = 0,
) -> str:
    language = normalize_language(language)
    stage_index = max(0, min(follow_up_count, 3)) - 1 if follow_up_count > 0 else 0

    if language == "hi-IN":
        prompts = {
            "aadhaar_upload": (
                "समझ गई। अभी Aadhaar अपलोड पेज पर कौन सा संदेश दिख रहा है?",
                "ठीक है। अपलोड दबाने के बाद स्क्रीन पर क्या बदलता है?",
                "क्या फोटो चुनने के बाद भी वही पेज रुका रहता है?",
            ),
            "pan_upload": (
                "समझ गई। अभी PAN अपलोड पेज पर क्या लिखा दिख रहा है?",
                "ठीक है। अपलोड बटन दबाने के बाद क्या होता है?",
                "क्या PAN फोटो चुनने के बाद भी आगे नहीं बढ़ रहा?",
            ),
            "photo_upload": (
                "समझ गई। सेल्फी लेने के बाद स्क्रीन पर क्या दिख रहा है?",
                "ठीक है। क्या कैमरा खुल रहा है या वहीं रुक रहा है?",
                "क्या सेल्फी कैप्चर के बाद फिर से रीटेक पर आ रहा है?",
            ),
            "application_error_issue": (
                "समझ गई। अभी ऐप में ऊपर कौन सा एरर दिख रहा है?",
                "ठीक है। यह एरर किस पेज पर आ रहा है?",
                "क्या ऐप दोबारा खोलने पर भी वही एरर आता है?",
            ),
            "statement_issue": (
                "समझ गई। स्टेटमेंट पेज पर अभी क्या दिख रहा है?",
                "ठीक है। डाउनलोड दबाने पर कोई संदेश आता है क्या?",
                "क्या फाइल खुलते समय पासवर्ड संदेश दिख रहा है?",
            ),
            "invoice_issue": (
                "समझ गई। इनवॉइस सेक्शन में अभी क्या लिखा आ रहा है?",
                "ठीक है। डाउनलोड दबाने पर कौन सा संदेश मिलता है?",
                "क्या इनवॉइस लिस्ट खुल रही है या खाली दिख रही है?",
            ),
            "refund_issue": (
                "समझ गई। रिफंड में अभी सबसे बड़ी दिक्कत क्या दिख रही है?",
                "ठीक है। क्या ट्रांजैक्शन पर कोई स्टेटस लाइन दिख रही है?",
                "क्या अपेक्षित राशि और दिख रही राशि अलग है?",
            ),
            "card_block_issue": (
                "समझ गई। कार्ड कंट्रोल पेज पर अभी क्या दिख रहा है?",
                "ठीक है। ब्लॉक या अनब्लॉक दबाने पर क्या संदेश आता है?",
                "क्या वही कार्रवाई फिर करने पर भी एरर आ रहा है?",
            ),
            "address_update_issue": (
                "समझ गई। पता अपडेट में अभी कौन सा चरण रुका है?",
                "ठीक है। OTP चरण में क्या लिखा दिख रहा है?",
                "क्या पता प्रमाण अपलोड के बाद भी सबमिट नहीं हो रहा?",
            ),
            "emi_issue": (
                "समझ गई। EMI विकल्प खोलने पर क्या दिख रहा है?",
                "ठीक है। क्या पात्रता संदेश आ रहा है या खाली है?",
                "क्या EMI अनुरोध भेजते समय एरर दिख रहा है?",
            ),
            "otp_issue": (
                "समझ गई। OTP स्क्रीन पर अभी क्या लिखा आ रहा है?",
                "ठीक है। री-सेंड के बाद कोई नया संदेश आया क्या?",
                "क्या SMS आता है लेकिन OTP बॉक्स में मान्य नहीं हो रहा?",
            ),
            "login_issue": (
                "समझ गई। लॉगिन पेज पर कौन सा संदेश दिख रहा है?",
                "ठीक है। क्या मोबाइल दर्ज करने के बाद OTP स्क्रीन खुल रही है?",
                "क्या पासवर्ड डालने पर तुरंत एरर आता है?",
            ),
            "application_status_issue": (
                "समझ गई। स्टेटस पेज पर अभी क्या दिख रहा है?",
                "ठीक है। क्या ट्रैकिंग नंबर डालने के बाद पेज खुल रहा है?",
                "क्या स्टेटस लाइन बदलती है या वही रहती है?",
            ),
            "document_upload": (
                "समझ गई। दस्तावेज़ अपलोड पेज पर अभी क्या दिख रहा है?",
                "ठीक है। फाइल चुनने के बाद कौन सा संदेश आता है?",
                "क्या सबमिट दबाने पर भी अपलोड पूरा नहीं होता?",
            ),
            "generic_process_help": (
                "समझ गई। आप अभी किस चरण पर रुके हैं?",
                "ठीक है। उस चरण पर स्क्रीन में क्या लिखा आ रहा है?",
                "क्या आप वही लाइन शब्दों में पढ़कर बता सकते हैं?",
            ),
            "retry_after_30_days": (
                "अभी आवेदन आगे नहीं बढ़ सकता। कृपया 30 दिन बाद प्रयास करें।",
                "अभी आवेदन आगे नहीं बढ़ सकता। कृपया 30 दिन बाद प्रयास करें।",
                "अभी आवेदन आगे नहीं बढ़ सकता। कृपया 30 दिन बाद प्रयास करें।",
            ),
            "personal_details_mismatch": (
                "PAN और DOB रिकॉर्ड से मेल नहीं खा रहे। कृपया जाँचकर फिर प्रयास करें।",
                "PAN और DOB रिकॉर्ड से मेल नहीं खा रहे। कृपया जाँचकर फिर प्रयास करें।",
                "PAN और DOB रिकॉर्ड से मेल नहीं खा रहे। कृपया जाँचकर फिर प्रयास करें।",
            ),
            "max_attempts_exceeded": (
                "अधिकतम प्रयास पूरे हो गए हैं। कृपया 24 घंटे बाद फिर कोशिश करें।",
                "अधिकतम प्रयास पूरे हो गए हैं। कृपया 24 घंटे बाद फिर कोशिश करें।",
                "अधिकतम प्रयास पूरे हो गए हैं। कृपया 24 घंटे बाद फिर कोशिश करें।",
            ),
            "age_ineligible": (
                "न्यूनतम पात्र आयु 25 वर्ष है। अभी आप पात्र नहीं हैं।",
                "न्यूनतम पात्र आयु 25 वर्ष है। अभी आप पात्र नहीं हैं।",
                "न्यूनतम पात्र आयु 25 वर्ष है। अभी आप पात्र नहीं हैं।",
            ),
            "technical_error": (
                "अभी तकनीकी समस्या है। कृपया थोड़ी देर बाद फिर प्रयास करें।",
                "अभी तकनीकी समस्या है। कृपया थोड़ी देर बाद फिर प्रयास करें।",
                "अभी तकनीकी समस्या है। कृपया थोड़ी देर बाद फिर प्रयास करें।",
            ),
            "aadhaar_pan_not_linked": (
                "Aadhaar PAN से लिंक नहीं है। कृपया लिंक करके फिर प्रयास करें।",
                "Aadhaar PAN से लिंक नहीं है। कृपया लिंक करके फिर प्रयास करें।",
                "Aadhaar PAN से लिंक नहीं है। कृपया लिंक करके फिर प्रयास करें।",
            ),
            "aadhaar_hindi_not_supported": (
                "Aadhaar verification हिंदी में उपलब्ध नहीं है। कृपया English में जारी रखें।",
                "Aadhaar verification हिंदी में उपलब्ध नहीं है। कृपया English में जारी रखें।",
                "Aadhaar verification हिंदी में उपलब्ध नहीं है। कृपया English में जारी रखें।",
            ),
            "aadhaar_reverify": (
                "कृपया Aadhaar और PAN लिंक सही करके verification फिर करें।",
                "कृपया Aadhaar और PAN लिंक सही करके verification फिर करें।",
                "कृपया Aadhaar और PAN लिंक सही करके verification फिर करें।",
            ),
            "aadhaar_verification_failure": (
                "Verification सिस्टम समस्या से पूरा नहीं हुआ। कृपया फिर प्रयास करें।",
                "Verification सिस्टम समस्या से पूरा नहीं हुआ। कृपया फिर प्रयास करें।",
                "Verification सिस्टम समस्या से पूरा नहीं हुआ। कृपया फिर प्रयास करें।",
            ),
            "vkyc_pending": (
                "Aadhaar verification के बाद 72 घंटे में video KYC पूरा करें।",
                "Aadhaar verification के बाद 72 घंटे में video KYC पूरा करें।",
                "Aadhaar verification के बाद 72 घंटे में video KYC पूरा करें।",
            ),
            "vkyc_expired": (
                "Video KYC समय पर पूरा नहीं हुआ। कृपया आवेदन फिर शुरू करें।",
                "Video KYC समय पर पूरा नहीं हुआ। कृपया आवेदन फिर शुरू करें।",
                "Video KYC समय पर पूरा नहीं हुआ। कृपया आवेदन फिर शुरू करें।",
            ),
            "offer_eligible_no_docs": (
                "अच्छी खबर, आप बिना अतिरिक्त दस्तावेज़ के पात्र हैं।",
                "अच्छी खबर, आप बिना अतिरिक्त दस्तावेज़ के पात्र हैं।",
                "अच्छी खबर, आप बिना अतिरिक्त दस्तावेज़ के पात्र हैं।",
            ),
            "bank_statement_required": (
                "आगे बढ़ने के लिए bank statement चाहिए। net banking या manual upload चुनें।",
                "आगे बढ़ने के लिए bank statement चाहिए। net banking या manual upload चुनें।",
                "आगे बढ़ने के लिए bank statement चाहिए। net banking या manual upload चुनें।",
            ),
            "bank_not_found_manual_upload": (
                "अगर bank सूची में नहीं है तो manual upload करें।",
                "अगर bank सूची में नहीं है तो manual upload करें।",
                "अगर bank सूची में नहीं है तो manual upload करें।",
            ),
            "salaried_only": (
                "अभी यह प्रक्रिया केवल salaried customers के लिए उपलब्ध है।",
                "अभी यह प्रक्रिया केवल salaried customers के लिए उपलब्ध है।",
                "अभी यह प्रक्रिया केवल salaried customers के लिए उपलब्ध है।",
            ),
            "card_selection_required": (
                "कृपया आगे बढ़ने के लिए एक card विकल्प चुनें।",
                "कृपया आगे बढ़ने के लिए एक card विकल्प चुनें।",
                "कृपया आगे बढ़ने के लिए एक card विकल्प चुनें।",
            ),
            "e_consent_step": (
                "कृपया विवरण देखकर swipe right करें।",
                "कृपया विवरण देखकर swipe right करें।",
                "कृपया विवरण देखकर swipe right करें।",
            ),
            "vkyc_instructions": (
                "Video KYC के लिए PAN रखें, location allow करें और plain background में बैठें।",
                "Video KYC के लिए PAN रखें, location allow करें और plain background में बैठें।",
                "Video KYC के लिए PAN रखें, location allow करें और plain background में बैठें।",
            ),
            "application_complete": (
                "आपकी application प्रक्रिया पूरी हो गई है। धन्यवाद।",
                "आपकी application प्रक्रिया पूरी हो गई है। धन्यवाद।",
                "आपकी application प्रक्रिया पूरी हो गई है। धन्यवाद।",
            ),
            "resume_journey": (
                "Welcome back। आप अपनी application वहीं से जारी कर सकते हैं जहाँ रुकी थी।",
                "Welcome back। आप अपनी application वहीं से जारी कर सकते हैं जहाँ रुकी थी।",
                "Welcome back। आप अपनी application वहीं से जारी कर सकते हैं जहाँ रुकी थी।",
            ),
        }
        selected_prompts = prompts.get(issue_type, prompts["generic_process_help"])
        return selected_prompts[stage_index]

    prompts = {
        "aadhaar_upload": (
            "Understood. What message is currently visible on the Aadhaar upload page?",
            "Okay. What changes right after you tap upload?",
            "Does it still stay on the same page after selecting the image?",
        ),
        "pan_upload": (
            "Got it. What message is visible on the PAN upload page now?",
            "Okay. What happens immediately after you tap upload?",
            "Does it still not move ahead after selecting PAN image?",
        ),
        "photo_upload": (
            "Understood. What do you see right after taking selfie?",
            "Okay. Does camera open, or does it stay stuck?",
            "After capture, does it return to retake again?",
        ),
        "application_error_issue": (
            "I understand. Which error line is visible at the top of app screen?",
            "Okay. On which exact page does this error appear?",
            "After reopening app, does the same error still appear?",
        ),
        "statement_issue": (
            "Understood. What is visible on statement page right now?",
            "Okay. What message appears when you tap download?",
            "Do you see a password-related message while opening file?",
        ),
        "invoice_issue": (
            "Got it. What text is visible in invoice section now?",
            "Okay. What message appears when you tap download?",
            "Does invoice list open, or does it look empty?",
        ),
        "refund_issue": (
            "Understood. What is the main refund issue visible now?",
            "Okay. Do you see any status line on that transaction?",
            "Are expected amount and shown amount different?",
        ),
        "card_block_issue": (
            "Understood. What is visible now on card controls page?",
            "Okay. What message appears after tapping block or unblock?",
            "Does the same error come even after retry?",
        ),
        "address_update_issue": (
            "Understood. Which exact step is stuck in address update?",
            "Okay. What message do you see at OTP step?",
            "After proof upload, does submit still fail?",
        ),
        "emi_issue": (
            "Understood. What do you see when opening EMI option?",
            "Okay. Is any eligibility message visible there?",
            "Do you get an error while submitting EMI request?",
        ),
        "otp_issue": (
            "Understood. What message is visible on OTP screen now?",
            "Okay. After resend, do you see any new message?",
            "Do you receive SMS but OTP is still not accepted?",
        ),
        "login_issue": (
            "I see. What exact message is visible on login page?",
            "Okay. After entering mobile, does OTP screen open?",
            "Do you get immediate error after entering password?",
        ),
        "application_status_issue": (
            "Understood. What is visible now on status tracking page?",
            "Okay. After entering tracking details, does page load?",
            "Does the status line change or remain the same?",
        ),
        "document_upload": (
            "Understood. What is visible now on document upload page?",
            "Okay. What message appears right after choosing file?",
            "When you submit, does upload still not complete?",
        ),
        "generic_process_help": (
            "Understood. Which exact step are you stuck on right now?",
            "Okay. What text is visible on that screen?",
            "Can you read the same line shown there?",
        ),
        "retry_after_30_days": (
            "Sorry sir, at the moment we are unable to proceed with your application. You may try again after 30 days.",
            "Sorry sir, at the moment we are unable to proceed with your application. You may try again after 30 days.",
            "Sorry sir, at the moment we are unable to proceed with your application. You may try again after 30 days.",
        ),
        "personal_details_mismatch": (
            "Sorry sir, your PAN and date of birth do not match our records. Please check and try again.",
            "Sorry sir, your PAN and date of birth do not match our records. Please check and try again.",
            "Sorry sir, your PAN and date of birth do not match our records. Please check and try again.",
        ),
        "max_attempts_exceeded": (
            "You have reached the maximum number of attempts. Please try again after 24 hours.",
            "You have reached the maximum number of attempts. Please try again after 24 hours.",
            "You have reached the maximum number of attempts. Please try again after 24 hours.",
        ),
        "age_ineligible": (
            "As per BOB Card policy, the minimum eligible age is 25 years. Currently, you do not meet this criteria.",
            "As per BOB Card policy, the minimum eligible age is 25 years. Currently, you do not meet this criteria.",
            "As per BOB Card policy, the minimum eligible age is 25 years. Currently, you do not meet this criteria.",
        ),
        "technical_error": (
            "We are facing a technical issue at the moment. Kindly try again after some time and restart your journey.",
            "We are facing a technical issue at the moment. Kindly try again after some time and restart your journey.",
            "We are facing a technical issue at the moment. Kindly try again after some time and restart your journey.",
        ),
        "aadhaar_pan_not_linked": (
            "We regret to inform you that your Aadhaar is not linked with your PAN card. Please link it and try again.",
            "We regret to inform you that your Aadhaar is not linked with your PAN card. Please link it and try again.",
            "We regret to inform you that your Aadhaar is not linked with your PAN card. Please link it and try again.",
        ),
        "aadhaar_hindi_not_supported": (
            "Currently, Aadhaar verification is not available in Hindi. Please continue in English.",
            "Currently, Aadhaar verification is not available in Hindi. Please continue in English.",
            "Currently, Aadhaar verification is not available in Hindi. Please continue in English.",
        ),
        "aadhaar_reverify": (
            "Please ensure your Aadhaar and PAN are linked correctly, then try the verification again.",
            "Please ensure your Aadhaar and PAN are linked correctly, then try the verification again.",
            "Please ensure your Aadhaar and PAN are linked correctly, then try the verification again.",
        ),
        "aadhaar_verification_failure": (
            "Sorry, verification could not be completed due to a system issue. Please try again to continue the process.",
            "Sorry, verification could not be completed due to a system issue. Please try again to continue the process.",
            "Sorry, verification could not be completed due to a system issue. Please try again to continue the process.",
        ),
        "vkyc_pending": (
            "After Aadhaar verification, please complete your video KYC within 72 hours.",
            "After Aadhaar verification, please complete your video KYC within 72 hours.",
            "After Aadhaar verification, please complete your video KYC within 72 hours.",
        ),
        "vkyc_expired": (
            "Your application could not be completed because video KYC was not finished within 72 hours. Please restart the application to continue.",
            "Your application could not be completed because video KYC was not finished within 72 hours. Please restart the application to continue.",
            "Your application could not be completed because video KYC was not finished within 72 hours. Please restart the application to continue.",
        ),
        "offer_eligible_no_docs": (
            "Good news, you are eligible for card offers without additional documents.",
            "Good news, you are eligible for card offers without additional documents.",
            "Good news, you are eligible for card offers without additional documents.",
        ),
        "bank_statement_required": (
            "To continue, we need your bank statement. You can proceed through net banking or upload your statement manually.",
            "To continue, we need your bank statement. You can proceed through net banking or upload your statement manually.",
            "To continue, we need your bank statement. You can proceed through net banking or upload your statement manually.",
        ),
        "bank_not_found_manual_upload": (
            "If your bank is not listed, you can upload your bank statement manually.",
            "If your bank is not listed, you can upload your bank statement manually.",
            "If your bank is not listed, you can upload your bank statement manually.",
        ),
        "salaried_only": (
            "Currently, this process is available only for salaried customers.",
            "Currently, this process is available only for salaried customers.",
            "Currently, this process is available only for salaried customers.",
        ),
        "card_selection_required": (
            "Please choose one of the available card options to continue.",
            "Please choose one of the available card options to continue.",
            "Please choose one of the available card options to continue.",
        ),
        "e_consent_step": (
            "Please review the details and swipe right to proceed.",
            "Please review the details and swipe right to proceed.",
            "Please review the details and swipe right to proceed.",
        ),
        "vkyc_instructions": (
            "For video KYC, please keep your original PAN card ready, allow location access, and sit in front of a plain light background.",
            "For video KYC, please keep your original PAN card ready, allow location access, and sit in front of a plain light background.",
            "For video KYC, please keep your original PAN card ready, allow location access, and sit in front of a plain light background.",
        ),
        "application_complete": (
            "Your application process is complete. Thank you for choosing BOB Card.",
            "Your application process is complete. Thank you for choosing BOB Card.",
            "Your application process is complete. Thank you for choosing BOB Card.",
        ),
        "resume_journey": (
            "Welcome back. You can continue your application from where you left off.",
            "Welcome back. You can continue your application from where you left off.",
            "Welcome back. You can continue your application from where you left off.",
        ),
    }
    selected_prompts = prompts.get(issue_type, prompts["generic_process_help"])
    return selected_prompts[stage_index]


def build_issue_resolution_reply(
    issue_type: IssueType,
    symptom: IssueSymptom,
    language: str = "en-IN",
) -> str:
    language = normalize_language(language)
    deterministic_issue_types = {
        "retry_after_30_days",
        "personal_details_mismatch",
        "max_attempts_exceeded",
        "age_ineligible",
        "technical_error",
        "aadhaar_pan_not_linked",
        "aadhaar_hindi_not_supported",
        "aadhaar_reverify",
        "aadhaar_verification_failure",
        "vkyc_pending",
        "vkyc_expired",
        "offer_eligible_no_docs",
        "bank_statement_required",
        "bank_not_found_manual_upload",
        "salaried_only",
        "card_selection_required",
        "e_consent_step",
        "vkyc_instructions",
        "application_complete",
        "resume_journey",
    }
    if issue_type in deterministic_issue_types:
        return build_issue_help_reply(issue_type, language)

    if language == "hi-IN":
        replies = {
            ("aadhaar_upload", "error_message"): "ठीक है। स्क्रीन पर जो एरर है, वही पढ़कर बताइए।",
            ("aadhaar_upload", "access_issue"): "समझ गई। पूरा संदेश न दिखे तो जो शब्द दिख रहे हैं, वही बताइए।",
            ("aadhaar_upload", "blurred_image"): "ठीक है। Aadhaar की साफ़ फोटो लेकर फिर अपलोड कीजिए।",
            ("aadhaar_upload", "upload_blocked"): "समझ गई। ऐप फिर खोलिए और Aadhaar अपलोड दोबारा कीजिए।",
            ("aadhaar_upload", "incorrect_details"): "ठीक है। नाम और जन्म-तिथि साफ़ दिखने वाली Aadhaar फोटो अपलोड कीजिए।",
            ("pan_upload", "blurred_image"): "ठीक है। PAN की साफ़ फोटो लेकर फिर अपलोड कीजिए।",
            ("pan_upload", "upload_blocked"): "समझ गई। ऐप फिर खोलिए और PAN अपलोड दोबारा कीजिए।",
            ("pan_upload", "error_message"): "ठीक है। PAN चरण का एरर संदेश पढ़कर बताइए।",
            ("photo_upload", "blurred_image"): "ठीक है। अच्छी रोशनी में साफ़ सेल्फी लेकर फिर अपलोड कीजिए।",
            ("photo_upload", "upload_blocked"): "समझ गई। नई सेल्फी लेकर अपलोड फिर से कीजिए।",
            ("photo_upload", "incorrect_details"): "ठीक है। चेहरा बीच में रखकर साफ़ सेल्फी अपलोड कीजिए।",
            ("application_error_issue", "error_message"): "ठीक है। ऐप पर जो एरर दिख रहा है, वही बताइए।",
            ("application_error_issue", "access_issue"): "समझ गई। ऐप बंद करके फिर खोलिए, फिर वही चरण दोबारा कीजिए।",
            ("application_error_issue", "upload_blocked"): "ठीक है। उसी चरण को रीफ्रेश करके फिर सबमिट कीजिए।",
            ("statement_issue", "not_found"): "ठीक है। स्टेटमेंट सेक्शन रीफ्रेश करके फिर देखिए।",
            ("statement_issue", "access_issue"): "समझ गई। स्टेटमेंट फाइल का पासवर्ड प्रारूप फिर जाँचिए।",
            ("invoice_issue", "not_found"): "ठीक है। इनवॉइस सेक्शन रीफ्रेश करके फिर देखिए।",
            ("invoice_issue", "error_message"): "समझ गई। इनवॉइस का एरर संदेश पढ़कर बताइए।",
            ("invoice_issue", "upload_blocked"): "ठीक है। नेटवर्क जाँचकर इनवॉइस डाउनलोड फिर कीजिए।",
            ("refund_issue", "not_found"): "समझ गई। रिफंड रेफरेंस से स्थिति फिर जाँचिए।",
            ("refund_issue", "error_message"): "ठीक है। रिफंड से जुड़ा संदेश या रेफरेंस बताइए।",
            ("refund_issue", "incorrect_details"): "ठीक है। अपेक्षित राशि और दिख रही राशि दोनों बताइए, मैं अगला कदम बताती हूँ।",
            ("card_block_issue", "not_found"): "समझ गई। कार्ड कंट्रोल में ब्लॉक या अनब्लॉक विकल्प फिर देखें।",
            ("card_block_issue", "error_message"): "ठीक है। ब्लॉक या अनब्लॉक का एरर संदेश बताइए।",
            ("address_update_issue", "access_issue"): "समझ गई। OTP सत्यापित करके पता प्रमाण अपलोड करें और फिर भेजें।",
            ("address_update_issue", "upload_blocked"): "ठीक है। पता प्रमाण की साफ़ छवि या पीडीएफ फिर अपलोड करें।",
            ("emi_issue", "not_found"): "समझ गई। पात्र लेन-देन खोलकर EMI विकल्प फिर देखें।",
            ("emi_issue", "error_message"): "ठीक है। EMI अनुरोध का एरर संदेश पढ़कर बताइए।",
            ("otp_issue", "not_found"): "ठीक है। कुछ सेकंड बाद OTP फिर मंगाइए और SMS देखें। OTP साझा न करें।",
            ("otp_issue", "upload_blocked"): "समझ गई। ऐप फिर खोलकर OTP दोबारा मंगाइए। OTP साझा न करें।",
            ("login_issue", "error_message"): "ठीक है। लॉगिन स्क्रीन का एरर संदेश पढ़कर बताइए।",
            ("login_issue", "access_issue"): "समझ गई। पंजीकृत मोबाइल और पासवर्ड या OTP फिर जाँचिए।",
            ("login_issue", "incorrect_details"): "ठीक है। जानकारी ध्यान से फिर भरिए, फिर दोबारा प्रयास कीजिए।",
            ("login_issue", "not_found"): "समझ गई। ऐप रीफ्रेश करके साइन-इन पेज फिर खोलिए।",
            ("application_status_issue", "not_found"): "ठीक है। ट्रैकिंग पेज रीफ्रेश करके स्थिति फिर देखिए।",
            ("application_status_issue", "error_message"): "समझ गई। स्थिति पेज का एरर संदेश पढ़कर बताइए।",
            ("application_status_issue", "access_issue"): "ठीक है। नेटवर्क जाँचकर ट्रैकिंग पेज फिर खोलिए।",
            ("document_upload", "upload_blocked"): "समझ गई। फाइल फिर चुनकर साफ़ कॉपी अपलोड कीजिए।",
            ("document_upload", "error_message"): "ठीक है। दस्तावेज़ अपलोड का एरर संदेश बताइए।",
            ("document_upload", "access_issue"): "समझ गई। जो शब्द दिख रहे हैं, वही पढ़कर बताइए।",
            ("document_upload", "blurred_image"): "ठीक है। दस्तावेज़ की साफ़ कॉपी लेकर फिर अपलोड कीजिए।",
        }
        return replies.get((issue_type, symptom), "ठीक है। अभी स्क्रीन पर क्या दिख रहा है, वही बताइए।")

    replies = {
        ("aadhaar_upload", "error_message"): "No worries. Please read the Aadhaar error message.",
        ("aadhaar_upload", "access_issue"): "If the full message is not visible, share the words you can see.",
        ("aadhaar_upload", "blurred_image"): "Please upload a clear Aadhaar image with visible details.",
        ("aadhaar_upload", "upload_blocked"): "Please reopen the app and retry Aadhaar upload.",
        ("aadhaar_upload", "incorrect_details"): "Please use an Aadhaar image where details are clearly visible.",
        ("pan_upload", "blurred_image"): "Please upload a clear PAN image.",
        ("pan_upload", "upload_blocked"): "Please reopen the app and retry PAN upload once.",
        ("pan_upload", "error_message"): "Please read the PAN upload error message.",
        ("photo_upload", "blurred_image"): "Please retake a clear selfie in good light.",
        ("photo_upload", "upload_blocked"): "Please retry selfie upload once.",
        ("photo_upload", "incorrect_details"): "Please keep your face centered and upload a new selfie.",
        ("application_error_issue", "error_message"): "Please share the app error message shown on screen.",
        ("application_error_issue", "access_issue"): "Please close and reopen the app, then retry the same step.",
        ("application_error_issue", "upload_blocked"): "Please refresh that step and submit again.",
        ("statement_issue", "not_found"): "Please refresh the statement section and check again.",
        ("statement_issue", "access_issue"): "Please verify statement file password format and retry.",
        ("invoice_issue", "not_found"): "Please refresh the invoice section and check again.",
        ("invoice_issue", "error_message"): "Please read the invoice error message.",
        ("invoice_issue", "upload_blocked"): "Please check network and retry invoice download.",
        ("refund_issue", "not_found"): "Please recheck refund status using your reference.",
        ("refund_issue", "error_message"): "Please read the refund-related message or reference.",
        ("refund_issue", "incorrect_details"): "Please share expected amount and shown amount so I can guide next steps.",
        ("card_block_issue", "not_found"): "Please open card controls and check block or unblock option.",
        ("card_block_issue", "error_message"): "Please read the block or unblock error message.",
        ("address_update_issue", "access_issue"): "Please verify OTP, upload address proof, and submit again.",
        ("address_update_issue", "upload_blocked"): "Please choose a clear address proof image or PDF and upload again.",
        ("emi_issue", "not_found"): "Please open the eligible transaction and check EMI option again.",
        ("emi_issue", "error_message"): "Please read the EMI request error message.",
        ("otp_issue", "not_found"): "Please request OTP again and check SMS inbox. Do not share OTP.",
        ("otp_issue", "upload_blocked"): "Please reopen the app and request OTP again. Do not share OTP.",
        ("login_issue", "error_message"): "Please read the login error message.",
        ("login_issue", "access_issue"): "Please verify registered mobile and password or OTP, then sign in again.",
        ("login_issue", "incorrect_details"): "Please re-enter details carefully and try again.",
        ("login_issue", "not_found"): "Please refresh the app and reopen sign-in screen.",
        ("application_status_issue", "not_found"): "Please refresh tracking page and check status again.",
        ("application_status_issue", "error_message"): "Please read the status page error message.",
        ("application_status_issue", "access_issue"): "Please reopen tracking page and retry after checking network.",
        ("document_upload", "upload_blocked"): "Please reselect the file and upload a clear copy.",
        ("document_upload", "error_message"): "Please read the document upload error message.",
        ("document_upload", "access_issue"): "If full message is not visible, share the visible words.",
        ("document_upload", "blurred_image"): "Please upload a clear document copy.",
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
        return "माफ़ कीजिए, मैं आपकी मदद के लिए हूँ। जिस चरण में दिक्कत है, वही फिर से बताइए।"
    return "Sorry, I want to help you quickly. Please repeat the exact step where the issue occurs."


def _contains_any(text: str, choices: tuple[str, ...]) -> bool:
    return any(choice in text for choice in choices)
