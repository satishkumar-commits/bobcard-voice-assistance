import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator

from app.api.routes.twilio import validate_twilio_signature


def _build_app() -> FastAPI:
    app = FastAPI()

    @app.post("/hook")
    async def hook(_: None = Depends(validate_twilio_signature)) -> dict[str, bool]:
        return {"ok": True}

    return app


class TwilioSignatureValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(_build_app())

    def test_allows_request_when_validation_disabled(self) -> None:
        settings = SimpleNamespace(
            twilio_validate_webhook_signature=False,
            twilio_auth_token="",
        )
        with patch("app.api.routes.twilio.get_settings", return_value=settings):
            response = self.client.post("/hook", data={"CallSid": "CA123"})
        self.assertEqual(response.status_code, 200)

    def test_rejects_missing_signature_when_validation_enabled(self) -> None:
        settings = SimpleNamespace(
            twilio_validate_webhook_signature=True,
            twilio_auth_token="secret-token",
        )
        with patch("app.api.routes.twilio.get_settings", return_value=settings):
            response = self.client.post("/hook", data={"CallSid": "CA123"})
        self.assertEqual(response.status_code, 403)

    def test_rejects_invalid_signature_when_validation_enabled(self) -> None:
        settings = SimpleNamespace(
            twilio_validate_webhook_signature=True,
            twilio_auth_token="secret-token",
        )
        with patch("app.api.routes.twilio.get_settings", return_value=settings):
            response = self.client.post(
                "/hook",
                data={"CallSid": "CA123"},
                headers={"X-Twilio-Signature": "invalid"},
            )
        self.assertEqual(response.status_code, 403)

    def test_allows_valid_signature_when_validation_enabled(self) -> None:
        auth_token = "secret-token"
        settings = SimpleNamespace(
            twilio_validate_webhook_signature=True,
            twilio_auth_token=auth_token,
        )
        body = {"CallSid": "CA123", "From": "+919999999999"}
        signature = RequestValidator(auth_token).compute_signature("http://testserver/hook", body)

        with patch("app.api.routes.twilio.get_settings", return_value=settings):
            response = self.client.post(
                "/hook",
                data=body,
                headers={"X-Twilio-Signature": signature},
            )
        self.assertEqual(response.status_code, 200)

    def test_returns_503_when_validation_enabled_but_auth_token_missing(self) -> None:
        settings = SimpleNamespace(
            twilio_validate_webhook_signature=True,
            twilio_auth_token="",
        )
        with patch("app.api.routes.twilio.get_settings", return_value=settings):
            response = self.client.post(
                "/hook",
                data={"CallSid": "CA123"},
                headers={"X-Twilio-Signature": "anything"},
            )
        self.assertEqual(response.status_code, 503)


if __name__ == "__main__":
    unittest.main()
