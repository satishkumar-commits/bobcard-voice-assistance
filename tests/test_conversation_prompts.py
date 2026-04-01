import unittest

from app.core.conversation_prompts import (
    build_general_capabilities_reply,
    build_human_handoff_reply,
    build_link_sent_confirmation_prompt,
    build_link_share_confirmation_prompt,
    build_opening_greeting,
    build_process_restart_link_reply,
    detect_auth_denial,
    detect_auth_confirmation,
    detect_consent_choice,
    detect_escalation_request,
    detect_language_preference,
    detect_resolution_choice,
    is_short_valid_intent,
    should_advance_on_affirmative,
    wants_goodbye,
)


class ConversationPromptsTests(unittest.TestCase):
    def test_consent_does_not_false_match_no_inside_other_words(self) -> None:
        self.assertEqual(detect_consent_choice("knowledge"), "unknown")

    def test_detects_consent_granted(self) -> None:
        self.assertEqual(detect_consent_choice("Yes, we can talk now"), "granted")

    def test_hello_does_not_auto_grant_consent(self) -> None:
        self.assertEqual(detect_consent_choice("hello", current_stage="consent_check"), "unknown")

    def test_detects_opt_out(self) -> None:
        self.assertEqual(detect_consent_choice("Please do not call me"), "opt_out")

    def test_no_maps_to_callback_only_in_consent_stage(self) -> None:
        self.assertEqual(detect_consent_choice("नहीं", current_stage="consent_check"), "callback")
        self.assertEqual(detect_consent_choice("नहीं", current_stage="identity_verification"), "unknown")

    def test_detect_auth_denial_supports_hindi_short_no(self) -> None:
        self.assertTrue(detect_auth_denial("नहीं"))
        self.assertTrue(detect_auth_denial("ना"))

    def test_detect_auth_denial_ignores_trailing_na_particle(self) -> None:
        self.assertFalse(detect_auth_denial("फ्रॉड हो सकता है ना"))

    def test_goodbye_detection(self) -> None:
        self.assertTrue(wants_goodbye("thanks bye"))
        self.assertFalse(wants_goodbye("this is a notebook issue"))

    def test_detects_escalation(self) -> None:
        self.assertTrue(detect_escalation_request("I want to speak to agent"))

    def test_language_preference_and_blocklist(self) -> None:
        self.assertEqual(detect_language_preference("english please"), "en-IN")
        self.assertIsNone(detect_language_preference("otp status issue"))

    def test_opening_uses_bob_card_branding(self) -> None:
        greeting = build_opening_greeting(name="Satish", language="en-IN", agent_name="Maya")
        self.assertIn("BOB Card", greeting)
        self.assertIn("BOBCards", greeting)
        self.assertIn("incomplete", greeting)
        self.assertIn("help you complete it", greeting)

    def test_general_capabilities_supports_style_selection(self) -> None:
        first = build_general_capabilities_reply("hi-IN", response_style="default")
        second = build_general_capabilities_reply("hi-IN", response_style="hinglish")
        self.assertNotEqual(first, "")
        self.assertNotEqual(second, "")
        self.assertNotEqual(first, second)
        self.assertIn("BOB Card", first)

    def test_general_capabilities_english_mentions_services(self) -> None:
        text = build_general_capabilities_reply("en-IN")
        self.assertIn("BOB Card", text)
        self.assertIn("application", text)

    def test_hindi_opening_includes_recording_disclosure(self) -> None:
        greeting = build_opening_greeting(language="hi-IN", agent_name="माया")
        self.assertIn("रिकॉर्ड", greeting)
        self.assertIn("एआई वॉइस सहायक", greeting)
        self.assertIn("आवेदन", greeting)
        self.assertIn("अधूरा", greeting)

    def test_handoff_reply_connects_human_agent(self) -> None:
        reply = build_human_handoff_reply("hi-IN")
        self.assertIn("मानव एजेंट", reply)
        self.assertNotIn("लिंक", reply)

    def test_resolution_choice_detects_hindi_done_phrase(self) -> None:
        self.assertEqual(detect_resolution_choice("हो गया"), "no_more_help")

    def test_resolution_choice_does_not_false_match_no_in_words(self) -> None:
        self.assertEqual(detect_resolution_choice("knowledge"), "unknown")

    def test_short_valid_intent_detects_hindi_done_phrase(self) -> None:
        self.assertTrue(is_short_valid_intent("हो गया"))

    def test_restart_link_reply_prompt(self) -> None:
        reply = build_process_restart_link_reply("hi-IN")
        self.assertIn("लिंक", reply)
        self.assertIn("फिर से", reply)

    def test_link_share_prompt_takes_consent_first(self) -> None:
        reply = build_link_share_confirmation_prompt("hi-IN")
        self.assertIn("क्या मैं आपको", reply)
        self.assertIn("हाँ या नहीं", reply)

    def test_link_sent_prompt_checks_receipt_after_consent(self) -> None:
        reply = build_link_sent_confirmation_prompt("hi-IN")
        self.assertIn("लिंक शेयर", reply)
        self.assertIn("मिला या नहीं मिला", reply)

    def test_identity_affirmation_phrase_with_boliye_advances(self) -> None:
        self.assertTrue(should_advance_on_affirmative("जी हाँ बोलिए", current_phase="identity_verification"))
        self.assertTrue(detect_auth_confirmation("जी हाँ बोलिए", current_phase="identity_verification"))

    def test_identity_confirmation_does_not_accept_plain_hello(self) -> None:
        self.assertFalse(detect_auth_confirmation("hello", current_phase="identity_verification"))


if __name__ == "__main__":
    unittest.main()
