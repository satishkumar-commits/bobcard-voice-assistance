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
            "pan_upload": (
                "अब पैन कार्ड सीधा रखिए, सभी कोने दिखाइए, और नाम व जन्म तिथि साफ़ आने के बाद फिर से अपलोड कीजिए।"
            ),
            "aadhaar_upload": (
                "अब आधार कार्ड सीधा रखिए और आगे वाली साफ़ तस्वीर फिर से अपलोड कीजिए।"
            ),
            "photo_upload": (
                "अब अच्छी रोशनी में नई फोटो लीजिए, चेहरा साफ़ रखिए, और फिर उसे अपलोड कीजिए।"
            ),
            "application_error_issue": (
                "अब app बंद करके फिर खोलिए, internet check कीजिए, और वही step दोबारा कीजिए।"
            ),
            "statement_issue": (
                "अब बी ओ बी कार्ड्स ऐप या पोर्टल के स्टेटमेंट सेक्शन में जाइए और स्टेटमेंट जाँचिए। "
                "अगर वहाँ नहीं दिख रहा, तो वही अभी बताइए।"
            ),
            "invoice_issue": (
                "अब ऐप के डॉक्यूमेंट्स या स्टेटमेंट्स सेक्शन में जाइए और इनवॉइस जाँचिए। "
                "अगर वहाँ नहीं दिख रहा, तो वही अभी बताइए।"
            ),
            "refund_issue": (
                "अब व्यापारी की रिफंड पुष्टि जाँचिए और राशि फिर से देखिए। "
                "अगर राशि नहीं दिख रही, तो रिफंड रेफरेंस तैयार रखिए और वही बताइए।"
            ),
            "card_block_issue": (
                "अब ऐप या पोर्टल के कार्ड कंट्रोल सेक्शन में जाइए और ब्लॉक या अनब्लॉक विकल्प खोलिए। "
                "अगर विकल्प नहीं मिल रहा, तो वही अभी बताइए।"
            ),
            "address_update_issue": (
                "अब पता अपडेट प्रक्रिया खोलिए, ओटीपी सत्यापित कीजिए, और पते का प्रमाण तैयार रखिए। "
                "जहाँ प्रक्रिया रुक रही है, वही अभी बताइए।"
            ),
            "emi_issue": (
                "अब ऐप या पोर्टल के सेवा अनुरोध सेक्शन में जाइए और योग्य लेनदेन जाँचिए। "
                "जहाँ ईएमआई का विकल्प नहीं दिख रहा, वही अभी बताइए।"
            ),
            "otp_issue": (
                "अगर ओटीपी नहीं मिल रहा है, तो नेटवर्क सिग्नल और संदेश इनबॉक्स जाँचिए, फिर कुछ सेकंड रुकिए। "
                "अगर फिर भी ओटीपी नहीं आए, तो फिर से ओटीपी भेजें दबाइए। ओटीपी किसी के साथ साझा मत कीजिए।"
            ),
            "login_issue": (
                "अगर लॉगिन में दिक्कत आ रही है, तो पंजीकृत मोबाइल नंबर जाँचिए और ओटीपी या पासवर्ड वाला चरण दोबारा कीजिए।"
            ),
            "application_status_issue": (
                "अगर आवेदन की स्थिति नहीं दिख रही है, तो ऐप या ट्रैकिंग पेज ताज़ा कीजिए और रेफरेंस विवरण के साथ फिर से स्थिति जाँचिए।"
            ),
            "document_upload": (
                "अब दस्तावेज़ की साफ़ कॉपी चुनिए, सभी कोने दिखाइए, और फिर से अपलोड कीजिए।"
            ),
            "generic_process_help": (
                "ठीक है। अभी सिर्फ उस step का नाम बोलिए जहाँ आप अटके हैं।"
            ),
        }
        return replies[issue_type]

    replies = {
        "pan_upload": (
            "Now upload a clear PAN image with all four corners visible and the name and date of birth readable."
        ),
        "aadhaar_upload": (
            "Now keep the Aadhaar card straight and upload the front side again with a clear image."
        ),
        "photo_upload": (
            "Now retake the photo in good light with your face clearly visible and upload it again."
        ),
        "application_error_issue": (
            "Close and reopen the app, check the internet connection, and repeat the same step now."
        ),
        "statement_issue": (
            "Open the statement section in the BOBCards app or portal and check the statement now."
        ),
        "invoice_issue": (
            "Open the documents or statements section in the app and check the invoice now."
        ),
        "refund_issue": (
            "Confirm the refund with the merchant now, then check whether the credit is visible."
        ),
        "card_block_issue": (
            "Open card controls in the app or portal and go to the block or unblock option now."
        ),
        "address_update_issue": (
            "Open the address update flow, complete OTP verification, and keep the address proof ready now."
        ),
        "emi_issue": (
            "Open the service request section and check the eligible transaction for EMI now."
        ),
        "otp_issue": (
            "If the OTP is not arriving, please check network signal and your inbox, wait a few seconds, and then try resend OTP once. Do not share the OTP with anyone."
        ),
        "login_issue": (
            "If you are facing a login problem, please confirm the registered mobile number and repeat the OTP or password step carefully."
        ),
        "application_status_issue": (
            "If the application status is not visible, please refresh the app or tracking page and check the status again with your reference details."
        ),
        "document_upload": (
            "Now choose a clear image or PDF, keep all document corners visible, and upload it again."
        ),
        "generic_process_help": (
            "Understood. Please say only the step name where you are stuck."
        ),
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
            "aadhaar_upload": "ठीक है, Aadhaar upload में दिक्कत है। बताइए फोटो साफ़ नहीं आ रही, upload रुक रहा है, या screen पर error दिख रहा है?",
            "pan_upload": "ठीक है, PAN step में दिक्कत है। बताइए फोटो साफ़ नहीं है, upload रुक रहा है, या कोई error दिख रहा है?",
            "photo_upload": "ठीक है, photo step में दिक्कत है। बताइए फोटो धुंधली है, चेहरा साफ़ नहीं दिख रहा, या upload रुक रहा है?",
            "application_error_issue": "ठीक है, app वाले step में दिक्कत है। बताइए app खुल नहीं रहा, बीच में बंद हो रहा है, या error message दिख रहा है?",
            "statement_issue": "ठीक है, statement में दिक्कत है। बताइए statement दिख नहीं रहा, download नहीं हो रहा, या password के बाद नहीं खुल रहा?",
            "invoice_issue": "ठीक है, invoice में दिक्कत है। बताइए invoice दिख नहीं रहा, download नहीं हो रहा, या error आ रहा है?",
            "refund_issue": "ठीक है, refund वाले हिस्से में दिक्कत है। बताइए राशि नहीं आई, देर हो रही है, या amount नहीं दिख रहा?",
            "card_block_issue": "ठीक है, card block या unblock step में दिक्कत है। बताइए option नहीं मिल रहा, card पहले से blocked दिख रहा है, या error आ रहा है?",
            "address_update_issue": "ठीक है, address update में दिक्कत है। बताइए OTP नहीं आ रहा, document upload नहीं हो रहा, या request submit नहीं हो रहा?",
            "emi_issue": "ठीक है, EMI वाले step में दिक्कत है। बताइए option नहीं मिल रहा, transaction eligible नहीं दिख रही, या request submit नहीं हो रहा?",
            "otp_issue": "ठीक है, OTP में दिक्कत है। बताइए OTP नहीं आ रहा, देर से आ रहा, या resend के बाद भी नहीं मिल रहा?",
            "login_issue": "ठीक है, login में दिक्कत है। बताइए OTP step पर रुक रहा है, password की दिक्कत है, या sign in नहीं हो रहा?",
            "application_status_issue": "ठीक है, application status में दिक्कत है। बताइए status नहीं दिख रही, page नहीं खुल रहा, या details match नहीं कर रहीं?",
            "document_upload": "ठीक है, document upload में दिक्कत है। बताइए file upload नहीं हो रही, साफ़ नहीं दिख रही, या error आ रहा है?",
            "generic_process_help": "ठीक है। जिस step पर दिक्कत आ रही है, वही सीधे बोलिए।",
        }
        return prompts[issue_type]

    prompts = {
        "aadhaar_upload": "Tell me exactly what is happening with Aadhaar: blurry image, stuck upload, or an error message?",
        "pan_upload": "Tell me exactly what is happening with PAN: unclear image, stuck upload, or an error message?",
        "photo_upload": "Tell me exactly what is happening with the photo: blurry image, unclear face, or stuck upload?",
        "application_error_issue": "Tell me exactly what is happening in the app: not opening, crashing, or showing an error message?",
        "statement_issue": "Tell me exactly what is happening with the statement: not visible, not downloading, or not opening?",
        "invoice_issue": "Tell me exactly what is happening with the invoice: not visible, not downloading, or showing an error?",
        "refund_issue": "Tell me exactly what is happening with the refund: missing credit, delay, or amount not visible?",
        "card_block_issue": "Tell me exactly what is happening with block or unblock: option missing, card already blocked, or an error?",
        "address_update_issue": "Tell me exactly what is happening with address update: OTP missing, document upload failing, or request not submitting?",
        "emi_issue": "Tell me exactly what is happening with EMI: option missing, transaction not eligible, or request not submitting?",
        "otp_issue": "Tell me exactly what is happening with OTP: not arriving, arriving late, or still missing after resend?",
        "login_issue": "Tell me exactly what is happening with login: stuck at OTP, password issue, or sign in failing?",
        "application_status_issue": "Tell me exactly what is happening with application status: not visible, page not opening, or details not matching?",
        "document_upload": "Tell me exactly what is happening with the document upload: file not uploading, file unclear, or an error?",
        "generic_process_help": "Please say only the step where you are stuck.",
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
            ("aadhaar_upload", "error_message"): "ठीक है। अभी स्क्रीन पर दिख रहा एरर मैसेज पढ़कर बताइए।",
            ("aadhaar_upload", "access_issue"): "ठीक है। अगर पूरा मैसेज पढ़ा नहीं जा रहा, तो जो शब्द साफ़ दिख रहे हैं वही बोलिए, या बताइए कि लाल निशान किस जगह पर है।",
            ("aadhaar_upload", "blurred_image"): "अब आधार की नई साफ़ फोटो लीजिए, सभी कोने दिखाइए, और फिर अपलोड कीजिए।",
            ("aadhaar_upload", "upload_blocked"): "अब ऐप बंद करके फिर खोलिए, इंटरनेट कनेक्शन जाँचिए, और आधार की आगे वाली तस्वीर फिर से अपलोड कीजिए।",
            ("aadhaar_upload", "incorrect_details"): "अब वही आधार फोटो चुनिए जिसमें नाम और जन्म तिथि साफ़ दिख रहे हों, फिर अपलोड कीजिए।",
            ("pan_upload", "blurred_image"): "अब पैन की साफ़ फोटो लीजिए, सभी कोने दिखाइए, और फिर upload कीजिए।",
            ("pan_upload", "upload_blocked"): "अब ऐप फिर से खोलिए और साफ़ पैन तस्वीर के साथ अपलोड दोबारा कीजिए।",
            ("pan_upload", "error_message"): "ठीक है। अभी पैन अपलोड वाला एरर मैसेज पढ़कर बताइए।",
            ("photo_upload", "blurred_image"): "अब अच्छी रोशनी में नई फोटो लीजिए, चेहरा पूरा फ्रेम में रखिए, और फिर अपलोड कीजिए।",
            ("photo_upload", "upload_blocked"): "अब नई फोटो लेकर ऐप में दोबारा अपलोड कीजिए।",
            ("photo_upload", "incorrect_details"): "अब चेहरा सीधा रखिए, साया हटाइए, और नई फोटो अपलोड कीजिए।",
            ("application_error_issue", "error_message"): "ठीक है। अभी स्क्रीन पर जो एप्लिकेशन एरर दिख रहा है, वह पढ़कर बताइए।",
            ("application_error_issue", "access_issue"): "अब ऐप पूरी तरह बंद कीजिए, फिर खोलिए, इंटरनेट कनेक्शन जाँचिए, और वही चरण दोबारा कीजिए।",
            ("application_error_issue", "upload_blocked"): "अब ऐप फिर से खोलिए और वही अनुरोध वाला चरण दोबारा जमा कीजिए।",
            ("statement_issue", "not_found"): "अब ऐप या पोर्टल के स्टेटमेंट सेक्शन को ताज़ा कीजिए और फिर जाँचिए।",
            ("statement_issue", "access_issue"): "अब स्टेटमेंट पी डी एफ का पासवर्ड डालिए: नाम के पहले चार बड़े अक्षर और जन्मतिथि का दिन और महीना।",
            ("invoice_issue", "not_found"): "अब ऐप में डॉक्यूमेंट्स या डाउनलोड्स सेक्शन ताज़ा कीजिए और इनवॉइस फिर से जाँचिए।",
            ("invoice_issue", "error_message"): "ठीक है। अभी इनवॉइस वाला एरर मैसेज पढ़कर बताइए।",
            ("invoice_issue", "upload_blocked"): "अब इंटरनेट कनेक्शन जाँचिए, ऐप फिर से खोलिए, और इनवॉइस दोबारा डाउनलोड कीजिए।",
            ("refund_issue", "not_found"): "अब व्यापारी का रिफंड रेफरेंस जाँचिए और राशि फिर से देखिए।",
            ("refund_issue", "error_message"): "ठीक है। अभी रिफंड से जुड़ा संदेश या रेफरेंस पढ़कर बताइए।",
            ("card_block_issue", "not_found"): "अब ऐप या पोर्टल में कार्ड कंट्रोल खोलिए और ब्लॉक या अनब्लॉक विकल्प जाँचिए।",
            ("card_block_issue", "error_message"): "ठीक है। अभी कार्ड ब्लॉक या अनब्लॉक वाला एरर बताइए।",
            ("address_update_issue", "access_issue"): "अब ओटीपी सत्यापित कीजिए, साफ़ पते का प्रमाण अपलोड कीजिए, और अनुरोध जमा कीजिए।",
            ("address_update_issue", "upload_blocked"): "अब पते के प्रमाण की साफ़ तस्वीर या पी डी एफ चुनिए और फिर से अपलोड कीजिए।",
            ("emi_issue", "not_found"): "अब योग्य लेनदेन जाँचिए और सेवा अनुरोध सेक्शन में ईएमआई विकल्प देखिए।",
            ("emi_issue", "error_message"): "ठीक है। अभी ईएमआई अनुरोध वाला एरर मैसेज बताइए।",
            ("otp_issue", "not_found"): "अब कुछ सेकंड रुकिए, फिर से ओटीपी भेजें दबाइए, और संदेश इनबॉक्स जाँचिए। ओटीपी किसी से साझा मत कीजिए।",
            ("otp_issue", "upload_blocked"): "अब ऐप फिर से खोलिए और ओटीपी एक बार फिर मँगाइए। ओटीपी किसी से साझा मत कीजिए।",
            ("login_issue", "error_message"): "ठीक है। अभी लॉगिन वाला एरर मैसेज पढ़कर बताइए।",
            ("login_issue", "access_issue"): "अब पंजीकृत मोबाइल नंबर और पासवर्ड या ओटीपी विवरण फिर से जाँचिए और लॉगिन कीजिए।",
            ("login_issue", "incorrect_details"): "अब पासवर्ड ध्यान से फिर डालिए। अगर फिर भी इनकरेक्ट दिख रहा है, तो पासवर्ड रीसेट या ओटीपी वाला विकल्प खोलिए।",
            ("login_issue", "not_found"): "अब ऐप ताज़ा कीजिए, फिर साइन इन स्क्रीन दोबारा खोलिए।",
            ("application_status_issue", "not_found"): "अब ट्रैकिंग पेज ताज़ा कीजिए और रेफरेंस विवरण से स्थिति फिर जाँचिए।",
            ("application_status_issue", "error_message"): "ठीक है। अभी आवेदन की स्थिति वाला एरर मैसेज बताइए।",
            ("application_status_issue", "access_issue"): "अब ट्रैकिंग पेज या ऐप फिर से खोलिए, इंटरनेट कनेक्शन जाँचिए, और रेफरेंस विवरण के साथ स्थिति दोबारा देखिए। अगर पेज फिर भी नहीं खुल रहा, तो वही बताइए।",
            ("document_upload", "upload_blocked"): "अब फ़ाइल फिर से चुनिए, इंटरनेट कनेक्शन जाँचिए, और साफ़ कॉपी अपलोड कीजिए।",
            ("document_upload", "error_message"): "ठीक है। अभी दस्तावेज़ अपलोड वाला एरर मैसेज बताइए।",
            ("document_upload", "access_issue"): "ठीक है। अगर पूरा मैसेज पढ़ा नहीं जा रहा, तो जितना दिख रहा है उतना बोलिए, या बताइए कि दिक्कत फ़ाइल में है या स्क्रीन पर।",
            ("document_upload", "blurred_image"): "अब नई साफ़ दस्तावेज़ कॉपी चुनिए और फिर अपलोड कीजिए।",
        }
        return replies.get((issue_type, symptom), "ठीक है। अभी बताइए कि स्क्रीन पर क्या दिख रहा है।")

    replies = {
        ("aadhaar_upload", "error_message"): "Read the error message on the screen, and I will guide the next step.",
        ("aadhaar_upload", "access_issue"): "If you cannot read the full message, tell me the words you can see or tell me where the red warning is showing.",
        ("aadhaar_upload", "blurred_image"): "Retake the Aadhaar image clearly, keep all corners visible, and upload it again.",
        ("aadhaar_upload", "upload_blocked"): "Reopen the app, check your internet connection, and upload the Aadhaar front image again.",
        ("aadhaar_upload", "incorrect_details"): "Choose the Aadhaar image where the name and date of birth are clearly visible, then upload it again.",
        ("pan_upload", "blurred_image"): "Use a clear PAN image with all four corners visible, then upload it again.",
        ("pan_upload", "upload_blocked"): "Reopen the app and upload the PAN image again with a clear straight photo.",
        ("pan_upload", "error_message"): "Read the PAN upload error message to me.",
        ("photo_upload", "blurred_image"): "Retake the photo in good light, keep your face clear, and upload it again.",
        ("photo_upload", "upload_blocked"): "Retake the photo and upload it again after reopening the app.",
        ("photo_upload", "incorrect_details"): "Keep your face centered and clear, then upload a new photo.",
        ("application_error_issue", "error_message"): "Read the application error on the screen, and I will guide the next step.",
        ("application_error_issue", "access_issue"): "Force close the app, open it again, check the internet connection, and repeat the same step.",
        ("application_error_issue", "upload_blocked"): "Reopen the app and submit the same step again.",
        ("statement_issue", "not_found"): "Refresh the statements section in the BOBCards app or portal and check again.",
        ("statement_issue", "access_issue"): "Use the statement PDF password with the first four uppercase letters of your name and the day and month of birth.",
        ("invoice_issue", "not_found"): "Refresh the documents or downloads section in the app and check the invoice again.",
        ("invoice_issue", "error_message"): "Read the invoice error message to me.",
        ("invoice_issue", "upload_blocked"): "Check the internet connection, reopen the app, and download the invoice again.",
        ("refund_issue", "not_found"): "Check the merchant refund reference and verify the credit again.",
        ("refund_issue", "error_message"): "Read the refund message or reference to me.",
        ("card_block_issue", "not_found"): "Open card controls in the app or portal and check the block or unblock option.",
        ("card_block_issue", "error_message"): "Read the block or unblock error message to me.",
        ("address_update_issue", "access_issue"): "Complete OTP verification, upload a clear address proof, and submit the request again.",
        ("address_update_issue", "upload_blocked"): "Choose a clear address proof image or PDF and upload it again.",
        ("emi_issue", "not_found"): "Check the eligible transaction and then open the service request section for EMI.",
        ("emi_issue", "error_message"): "Read the EMI request error message to me.",
        ("otp_issue", "not_found"): "Wait a few seconds, tap resend OTP once, and check the SMS inbox. Do not share the OTP.",
        ("otp_issue", "upload_blocked"): "Reopen the app and request the OTP once again. Do not share the OTP.",
        ("login_issue", "error_message"): "Read the login error message to me.",
        ("login_issue", "access_issue"): "Check the registered mobile number and the password or OTP details, then sign in again.",
        ("login_issue", "incorrect_details"): "Enter the password carefully again. If it still shows incorrect, open the password reset or OTP option.",
        ("login_issue", "not_found"): "Refresh the app and open the sign-in screen again.",
        ("application_status_issue", "not_found"): "Refresh the tracking page and check the status again with the reference details.",
        ("application_status_issue", "error_message"): "Read the application status error message to me.",
        ("application_status_issue", "access_issue"): "Open the tracking page or app again, check the internet connection, and review the status again with your reference details. If the page still does not open, tell me that.",
        ("document_upload", "upload_blocked"): "Choose the file again, check the internet connection, and upload a clear copy.",
        ("document_upload", "error_message"): "Read the document upload error message to me.",
        ("document_upload", "access_issue"): "If you cannot read the full message, tell me the words you can see or whether the problem is in the file or on the screen.",
        ("document_upload", "blurred_image"): "Choose a clear document copy with all corners visible and upload it again.",
    }
    return replies.get((issue_type, symptom), "Tell me exactly what is visible on the screen.")


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
