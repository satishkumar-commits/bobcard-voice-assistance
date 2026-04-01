import unittest
from pathlib import Path


class TurnOrchestrationGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stream_source = Path("app/services/twilio_media_stream_service.py").read_text(encoding="utf-8")
        self.conversation_source = Path("app/services/conversation_service.py").read_text(encoding="utf-8")

    def test_media_stream_uses_turn_ids_for_stale_invalidation(self) -> None:
        self.assertIn("turn_id: int", self.stream_source)
        self.assertIn("def _activate_new_turn(", self.stream_source)
        self.assertIn('"step": "assistant_turn_invalidated"', self.stream_source)
        self.assertIn("if not self._is_turn_current(session, response_epoch):", self.stream_source)

    def test_media_stream_drops_stale_audio_chunks(self) -> None:
        self.assertIn('"step": "assistant_audio_chunk_dropped"', self.stream_source)
        self.assertIn('"reason": "stale_turn_before_send"', self.stream_source)
        self.assertIn('"reason": "stale_turn_during_send"', self.stream_source)

    def test_conversation_adds_transcript_classification_gate(self) -> None:
        self.assertIn("class TranscriptClassification:", self.conversation_source)
        self.assertIn("def _classify_transcript(", self.conversation_source)
        self.assertIn('if transcript_classification.label in {"empty", "weak"}:', self.conversation_source)
        self.assertIn('if transcript_classification.label == "off_path":', self.conversation_source)

    def test_trust_objection_has_dedicated_hold_route(self) -> None:
        self.assertIn("def _looks_like_trust_or_fraud_objection", self.conversation_source)
        self.assertIn("def _build_trust_reassurance_reply", self.conversation_source)
        self.assertIn("def _handle_trust_objection_hold(", self.conversation_source)
        self.assertIn("def _build_trust_safe_fallback_reply(", self.conversation_source)
        self.assertIn('route = "trust_reassurance_hold"', self.conversation_source)
        self.assertIn('"step": "trust_objection_hold"', self.conversation_source)
        self.assertIn('"step": "trust_objection_safe_fallback"', self.conversation_source)

    def test_state_transition_requires_explicit_exit_intent(self) -> None:
        self.assertIn("def _has_explicit_state_exit_intent(", self.conversation_source)
        self.assertIn('route = "state_hold_reprompt"', self.conversation_source)
        self.assertIn("language_selection_requires_explicit_choice", self.conversation_source)


if __name__ == "__main__":
    unittest.main()
