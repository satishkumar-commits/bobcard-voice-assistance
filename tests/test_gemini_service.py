import unittest
from unittest import mock

from app.services.gemini_service import GeminiReplyDecision, GeminiService
from app.core.issue_guidance import (
    detect_issue_type,
    detect_issue_symptom,
    build_issue_follow_up_question,
    build_issue_help_reply,
    build_issue_resolution_reply,
)
from app.core.conversation_prompts import (
    build_empty_input_reply,
    build_general_capabilities_reply,
    build_issue_capture_prompt,
)


class TestGeminiServiceNormalizeReply(unittest.TestCase):
    def setUp(self) -> None:
        self.mock_latest_user_text = "user input"
        self.mock_language_code = "en-IN"
        self.mock_response_mode = "normal"
        self.mock_response_style = "default"
        self.mock_active_issue_type = None

    @mock.patch.object(GeminiService, "_fallback_decision")
    def test_normalize_reply_weak_reply_sorry(self, mock_fallback_decision: mock.Mock) -> None:
        text = "Sorry"
        GeminiService._normalize_reply(
            text,
            self.mock_language_code,
            self.mock_latest_user_text,
            self.mock_response_mode,
            self.mock_response_style,
            self.mock_active_issue_type,
        )
        mock_fallback_decision.assert_called_once_with(
            reason="weak_reply",
            latest_user_text=self.mock_latest_user_text,
            language_code=self.mock_language_code,
            response_mode=self.mock_response_mode,
            response_style=self.mock_response_style,
            provider_success=True,
            active_issue_type=self.mock_active_issue_type,
        )

    @mock.patch.object(GeminiService, "_fallback_decision")
    def test_normalize_reply_weak_reply_maaf_kijiye(self, mock_fallback_decision: mock.Mock) -> None:
        text = "Maaf kijiye"
        GeminiService._normalize_reply(
            text,
            self.mock_language_code,
            self.mock_latest_user_text,
            self.mock_response_mode,
            self.mock_response_style,
            self.mock_active_issue_type,
        )
        mock_fallback_decision.assert_called_once_with(
            reason="weak_reply",
            latest_user_text=self.mock_latest_user_text,
            language_code=self.mock_language_code,
            response_mode=self.mock_response_mode,
            response_style=self.mock_response_style,
            provider_success=True,
            active_issue_type=self.mock_active_issue_type,
        )

    @mock.patch.object(GeminiService, "_fallback_decision")
    def test_normalize_reply_disallowed_transfer_english(self, mock_fallback_decision: mock.Mock) -> None:
        text = "I will transfer you to a human agent"
        GeminiService._normalize_reply(
            text,
            self.mock_language_code,
            self.mock_latest_user_text,
            self.mock_response_mode,
            self.mock_response_style,
            self.mock_active_issue_type,
        )
        mock_fallback_decision.assert_called_once_with(
            reason="disallowed_transfer",
            latest_user_text=self.mock_latest_user_text,
            language_code=self.mock_language_code,
            response_mode=self.mock_response_mode,
            response_style=self.mock_response_style,
            provider_success=True,
            active_issue_type=self.mock_active_issue_type,
        )

    @mock.patch.object(GeminiService, "_fallback_decision")
    def test_normalize_reply_disallowed_transfer_hindi(self, mock_fallback_decision: mock.Mock) -> None:
        text = "human agent se connect"
        GeminiService._normalize_reply(
            text,
            self.mock_language_code,
            self.mock_latest_user_text,
            self.mock_response_mode,
            self.mock_response_style,
            self.mock_active_issue_type,
        )
        mock_fallback_decision.assert_called_once_with(
            reason="disallowed_transfer",
            latest_user_text=self.mock_latest_user_text,
            language_code=self.mock_language_code,
            response_mode=self.mock_response_mode,
            response_style=self.mock_response_style,
            provider_success=True,
            active_issue_type=self.mock_active_issue_type,
        )

    @mock.patch.object(GeminiService, "_fallback_decision")
    def test_normalize_reply_weak_generic_try_again_later(self, mock_fallback_decision: mock.Mock) -> None:
        text = "Please try again later"
        GeminiService._normalize_reply(
            text,
            self.mock_language_code,
            self.mock_latest_user_text,
            self.mock_response_mode,
            self.mock_response_style,
            self.mock_active_issue_type,
        )
        mock_fallback_decision.assert_called_once_with(
            reason="weak_generic",
            latest_user_text=self.mock_latest_user_text,
            language_code=self.mock_language_code,
            response_mode=self.mock_response_mode,
            response_style=self.mock_response_style,
            provider_success=True,
            active_issue_type=self.mock_active_issue_type,
        )

    @mock.patch.object(GeminiService, "_fallback_decision")
    def test_normalize_reply_issue_capture_loop(self, mock_fallback_decision: mock.Mock) -> None:
        with mock.patch.object(
            GeminiService, "_looks_like_issue_capture_prompt", return_value=True
        ):
            text = "Where you are stuck"
            GeminiService._normalize_reply(
                text,
                self.mock_language_code,
                self.mock_latest_user_text,
                self.mock_response_mode,
                self.mock_response_style,
                self.mock_active_issue_type,
            )
            mock_fallback_decision.assert_called_once_with(
                reason="issue_capture_loop",
                latest_user_text=self.mock_latest_user_text,
                language_code=self.mock_language_code,
                response_mode=self.mock_response_mode,
                response_style=self.mock_response_style,
                provider_success=True,
                active_issue_type=self.mock_active_issue_type,
            )

    @mock.patch.object(GeminiService, "_fallback_decision")
    def test_normalize_reply_off_language_hi(self, mock_fallback_decision: mock.Mock) -> None:
        # Simulate hi-IN expecting Devanagari, but getting Latin or mixed
        with mock.patch("app.utils.helpers.contains_devanagari", return_value=False) as mock_devanagari, \
             mock.patch("app.utils.helpers.contains_latin", return_value=True) as mock_latin:
            text = "Hello, how can I help you?"
            GeminiService._normalize_reply(
                text,
                "hi-IN",
                self.mock_latest_user_text,
                self.mock_response_mode,
                self.mock_response_style,
                self.mock_active_issue_type,
            )
            mock_fallback_decision.assert_called_once_with(
                reason="off_language_hi",
                latest_user_text=self.mock_latest_user_text,
                language_code="hi-IN",
                response_mode=self.mock_response_mode,
                response_style=self.mock_response_style,
                provider_success=True,
                active_issue_type=self.mock_active_issue_type,
            )

    @mock.patch.object(GeminiService, "_fallback_decision")
    def test_normalize_reply_off_language_en(self, mock_fallback_decision: mock.Mock) -> None:
        # Simulate en-IN expecting Latin, but getting Devanagari
        with mock.patch("app.utils.helpers.contains_devanagari", return_value=True):
            text = "नमस्ते, मैं आपकी कैसे मदद कर सकता हूँ?"
            GeminiService._normalize_reply(
                text,
                "en-IN",
                self.mock_latest_user_text,
                self.mock_response_mode,
                self.mock_response_style,
                self.mock_active_issue_type,
            )
            mock_fallback_decision.assert_called_once_with(
                reason="off_language_en",
                latest_user_text=self.mock_latest_user_text,
                language_code="en-IN",
                response_mode=self.mock_response_mode,
                response_style=self.mock_response_style,
                provider_success=True,
                active_issue_type=self.mock_active_issue_type,
            )

    def test_normalize_reply_valid_response(self) -> None:
        text = "This is a valid and helpful response."
        result = GeminiService._normalize_reply(
            text,
            self.mock_language_code,
            self.mock_latest_user_text,
            self.mock_response_mode,
            self.mock_response_style,
            self.mock_active_issue_type,
        )
        self.assertIsInstance(result, GeminiReplyDecision)
        self.assertEqual(result.text, text)
        self.assertEqual(result.source, "gemini")
        self.assertFalse(result.used_fallback)
        self.assertIsNone(result.fallback_reason)
        self.assertTrue(result.provider_success)

    def test_normalize_reply_strips_language_labels(self) -> None:
        text = "(English) This is a valid response."
        result = GeminiService._normalize_reply(
            text,
            self.mock_language_code,
            self.mock_latest_user_text,
            self.mock_response_mode,
            self.mock_response_style,
            self.mock_active_issue_type,
        )
        self.assertEqual(result.text, "This is a valid response.")

    def test_normalize_reply_strips_language_labels_case_insensitive(self) -> None:
        text = "ENGLISH: This is a valid response."
        result = GeminiService._normalize_reply(
            text,
            self.mock_language_code,
            self.mock_latest_user_text,
            self.mock_response_mode,
            self.mock_response_style,
            self.mock_active_issue_type,
        )
        self.assertEqual(result.text, "This is a valid response.")

    def test_normalize_reply_strips_multiple_language_labels(self) -> None:
        text = "(Hindi) (English) This is a valid response."
        result = GeminiService._normalize_reply(
            text,
            self.mock_language_code,
            self.mock_latest_user_text,
            self.mock_response_mode,
            self.mock_response_style,
            self.mock_active_issue_type,
        )
        self.assertEqual(result.text, "This is a valid response.")


class TestGeminiServiceFallbackDecision(unittest.TestCase):
    def setUp(self) -> None:
        self.mock_latest_user_text = "user query"
        self.mock_language_code = "en-IN"
        self.mock_response_mode = "normal"
        self.mock_response_style = "default"
        self.mock_active_issue_type = None

    @mock.patch("app.core.issue_guidance.detect_issue_type", return_value="aadhaar_upload")
    @mock.patch("app.core.issue_guidance.detect_issue_symptom", return_value="upload_blocked")
    @mock.patch("app.core.conversation_prompts.build_issue_resolution_reply", return_value="Please upload again.")
    def test_fallback_decision_issue_resolution_reply(
        self,
        mock_build_issue_resolution_reply: mock.Mock,
        mock_detect_issue_symptom: mock.Mock,
        mock_detect_issue_type: mock.Mock,
    ) -> None:
        decision = GeminiService._fallback_decision(
            reason="test_reason",
            latest_user_text=self.mock_latest_user_text,
            language_code=self.mock_language_code,
            response_mode=self.mock_response_mode,
            response_style=self.mock_response_style,
            active_issue_type=self.mock_active_issue_type,
        )
        mock_detect_issue_type.assert_called_once_with(self.mock_latest_user_text)
        mock_detect_issue_symptom.assert_called_once_with(self.mock_latest_user_text)
        mock_build_issue_resolution_reply.assert_called_once_with(
            "aadhaar_upload", "upload_blocked", self.mock_language_code
        )
        self.assertEqual(decision.text, "Please upload again.")
        self.assertTrue(decision.used_fallback)
        self.assertEqual(decision.fallback_reason, "test_reason")
        self.assertEqual(decision.source, "fallback")

    @mock.patch("app.core.issue_guidance.detect_issue_type", return_value="generic_process_help")
    @mock.patch("app.core.issue_guidance.detect_issue_symptom", return_value=None)
    @mock.patch.object(GeminiService, "_looks_like_guidance_request", return_value=True)
    @mock.patch("app.core.conversation_prompts.build_issue_help_reply", return_value="Here is how to get help.")
    def test_fallback_decision_issue_help_reply(
        self,
        mock_build_issue_help_reply: mock.Mock,
        mock_looks_like_guidance_request: mock.Mock,
        mock_detect_issue_symptom: mock.Mock,
        mock_detect_issue_type: mock.Mock,
    ) -> None:
        decision = GeminiService._fallback_decision(
            reason="test_reason",
            latest_user_text=self.mock_latest_user_text,
            language_code=self.mock_language_code,
            response_mode=self.mock_response_mode,
            response_style=self.mock_response_style,
            active_issue_type=self.mock_active_issue_type,
        )
        mock_build_issue_help_reply.assert_called_once_with(
            "generic_process_help", self.mock_language_code
        )
        self.assertEqual(decision.text, "Here is how to get help.")

    @mock.patch("app.core.issue_guidance.detect_issue_type", return_value="some_issue")
    @mock.patch("app.core.issue_guidance.detect_issue_symptom", return_value=None)
    @mock.patch("app.core.conversation_prompts.build_issue_follow_up_question", return_value="Can you tell me more?")
    def test_fallback_decision_issue_follow_up_question(
        self,
        mock_build_issue_follow_up_question: mock.Mock,
        mock_detect_issue_symptom: mock.Mock,
        mock_detect_issue_type: mock.Mock,
    ) -> None:
        decision = GeminiService._fallback_decision(
            reason="test_reason",
            latest_user_text=self.mock_latest_user_text,
            language_code=self.mock_language_code,
            response_mode=self.mock_response_mode,
            response_style=self.mock_response_style,
            active_issue_type=self.mock_active_issue_type,
        )
        mock_build_issue_follow_up_question.assert_called_once_with(
            "some_issue", self.mock_language_code
        )
        self.assertEqual(decision.text, "Can you tell me more?")

    @mock.patch("app.core.issue_guidance.detect_issue_type", return_value=None)
    @mock.patch.object(GeminiService, "_looks_like_general_banking_question", return_value=True)
    @mock.patch("app.core.conversation_prompts.build_general_capabilities_reply", return_value="I can help with banking.")
    def test_fallback_decision_general_banking_question(
        self,
        mock_build_general_capabilities_reply: mock.Mock,
        mock_looks_like_general_banking_question: mock.Mock,
        mock_detect_issue_type: mock.Mock,
    ) -> None:
        decision = GeminiService._fallback_decision(
            reason="test_reason",
            latest_user_text=self.mock_latest_user_text,
            language_code=self.mock_language_code,
            response_mode=self.mock_response_mode,
            response_style=self.mock_response_style,
            active_issue_type=self.mock_active_issue_type,
        )
        mock_looks_like_general_banking_question.assert_called_once_with(self.mock_latest_user_text)
        mock_build_general_capabilities_reply.assert_called_once_with(
            self.mock_language_code, response_style=self.mock_response_style
        )
        self.assertEqual(decision.text, "I can help with banking.")

    @mock.patch("app.core.issue_guidance.detect_issue_type", return_value=None)
    @mock.patch.object(GeminiService, "_looks_like_general_banking_question", return_value=False)
    @mock.patch("app.core.conversation_prompts.build_issue_capture_prompt", return_value="What is your issue?")
    def test_fallback_decision_issue_capture_prompt(
        self,
        mock_build_issue_capture_prompt: mock.Mock,
        mock_looks_like_general_banking_question: mock.Mock,
        mock_detect_issue_type: mock.Mock,
    ) -> None:
        decision = GeminiService._fallback_decision(
            reason="test_reason",
            latest_user_text=self.mock_latest_user_text,
            language_code=self.mock_language_code,
            response_mode=self.mock_response_mode,
            response_style=self.mock_response_style,
            active_issue_type=self.mock_active_issue_type,
        )
        mock_build_issue_capture_prompt.assert_called_once_with(self.mock_language_code)
        self.assertEqual(decision.text, "What is your issue?")

    @mock.patch("app.core.issue_guidance.detect_issue_type", return_value=None)
    @mock.patch.object(GeminiService, "_looks_like_general_banking_question", return_value=False)
    @mock.patch("app.core.conversation_prompts.build_empty_input_reply", return_value="Sorry, I didn't hear that.")
    def test_fallback_decision_empty_user_text(
        self,
        mock_build_empty_input_reply: mock.Mock,
        mock_looks_like_general_banking_question: mock.Mock,
        mock_detect_issue_type: mock.Mock,
    ) -> None:
        decision = GeminiService._fallback_decision(
            reason="test_reason",
            latest_user_text="",  # Empty user text
            language_code=self.mock_language_code,
            response_mode=self.mock_response_mode,
            response_style=self.mock_response_style,
            active_issue_type=self.mock_active_issue_type,
        )
        mock_build_empty_input_reply.assert_called_once_with(self.mock_language_code)
        self.assertEqual(decision.text, "Sorry, I didn't hear that.")


if __name__ == "__main__":
    unittest.main()
