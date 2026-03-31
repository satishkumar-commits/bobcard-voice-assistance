"""Compatibility flow module for conversation state helpers.

The runtime imports currently use ``conversation_prompts.py``.
This module re-exports the flow/state utilities so callers can use
``app.core.conversation`` as the canonical location.
"""

from app.core.conversation_prompts import (
    AADHAAR_VERIFICATION,
    ADDRESS_CAPTURE,
    AGE_ELIGIBILITY_CHECK,
    APPLICATION_COMPLETE,
    CARD_SELECTION,
    CIBIL_FETCH,
    CONSENT_CHECK,
    CONTEXT_SETTING,
    E_CONSENT,
    IDENTITY_VERIFICATION,
    ISSUE_CAPTURE,
    LANGUAGE_SELECTION,
    OFFER_ELIGIBILITY,
    OPENING,
    PERSONAL_DETAILS_VALIDATION,
    RESUME_JOURNEY,
    TERMINAL_REJECTION,
    VKYC_COMPLETE,
    VKYC_PENDING,
    build_flow_response,
    is_valid_short_response,
    next_phase_after_address_capture,
    next_phase_after_card_selection,
    next_phase_after_cibil_fetch,
    next_phase_after_e_consent,
    should_advance_on_affirmative,
)

__all__ = [
    "OPENING",
    "CONSENT_CHECK",
    "LANGUAGE_SELECTION",
    "IDENTITY_VERIFICATION",
    "CONTEXT_SETTING",
    "ISSUE_CAPTURE",
    "PERSONAL_DETAILS_VALIDATION",
    "AGE_ELIGIBILITY_CHECK",
    "AADHAAR_VERIFICATION",
    "ADDRESS_CAPTURE",
    "CIBIL_FETCH",
    "OFFER_ELIGIBILITY",
    "CARD_SELECTION",
    "E_CONSENT",
    "VKYC_PENDING",
    "VKYC_COMPLETE",
    "APPLICATION_COMPLETE",
    "TERMINAL_REJECTION",
    "RESUME_JOURNEY",
    "is_valid_short_response",
    "should_advance_on_affirmative",
    "build_flow_response",
    "next_phase_after_address_capture",
    "next_phase_after_cibil_fetch",
    "next_phase_after_card_selection",
    "next_phase_after_e_consent",
]
