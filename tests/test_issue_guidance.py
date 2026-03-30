import unittest

from app.core.issue_guidance import (
    detect_issue_symptom,
    detect_issue_type,
    normalize_issue_text,
)


class IssueGuidanceTests(unittest.TestCase):
    def test_normalizes_hinglish_variants(self) -> None:
        self.assertEqual(normalize_issue_text("Aadhar log in nahin ho raha"), "aadhaar login nahi ho raha")

    def test_detects_aadhaar_upload(self) -> None:
        self.assertEqual(detect_issue_type("aadhar upload nahi ho raha"), "aadhaar_upload")

    def test_detects_aadhaar_upload_for_devanagari_variant(self) -> None:
        self.assertEqual(detect_issue_type("आधर कार्ड अपलोड नहीं हो रहा"), "aadhaar_upload")

    def test_detects_otp_issue_for_spaced_hindi_letters(self) -> None:
        self.assertEqual(detect_issue_type("ओ टी पी नहीं मिल रहा"), "otp_issue")

    def test_detects_document_upload(self) -> None:
        self.assertEqual(detect_issue_type("I need help with document upload"), "document_upload")

    def test_avoids_pan_false_positive(self) -> None:
        self.assertIsNone(detect_issue_type("I prefer spanish language"))

    def test_detects_incorrect_details_from_amount_mismatch(self) -> None:
        self.assertEqual(
            detect_issue_symptom("Amount shown 100 but should have been 200"),
            "incorrect_details",
        )

    def test_detects_upload_blocked(self) -> None:
        self.assertEqual(detect_issue_symptom("upload ruk gaya"), "upload_blocked")

    def test_detects_access_issue(self) -> None:
        self.assertEqual(detect_issue_symptom("password dalne ke baad page nahi khul raha"), "access_issue")


if __name__ == "__main__":
    unittest.main()
