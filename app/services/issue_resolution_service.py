from dataclasses import dataclass

from app.core.conversation_prompts import BusinessState, CONSENT_CHECK, CONFIRMATION_CLOSING
from app.core.issue_guidance import IssueSymptom, IssueType


@dataclass
class IssueResolutionState:
    call_sid: str
    business_state: BusinessState = CONSENT_CHECK
    issue_type: IssueType | None = None
    symptom: IssueSymptom | None = None
    follow_up_count: int = 0
    response_style: str = "default"
    post_resolution_check_pending: bool = False
    identity_verified: bool = False


class IssueResolutionService:
    def __init__(self) -> None:
        self._states: dict[str, IssueResolutionState] = {}

    def get_state(self, call_sid: str) -> IssueResolutionState:
        if call_sid not in self._states:
            self._states[call_sid] = IssueResolutionState(call_sid=call_sid)
        return self._states[call_sid]

    def set_business_state(self, call_sid: str, business_state: BusinessState) -> IssueResolutionState:
        state = self.get_state(call_sid)
        state.business_state = business_state
        return state

    def register_issue(self, call_sid: str, issue_type: IssueType) -> IssueResolutionState:
        state = self.get_state(call_sid)
        if state.issue_type != issue_type:
            state.issue_type = issue_type
            state.symptom = None
            state.follow_up_count = 0
        state.post_resolution_check_pending = False
        return state

    def register_symptom(self, call_sid: str, symptom: IssueSymptom) -> IssueResolutionState:
        state = self.get_state(call_sid)
        state.symptom = symptom
        state.follow_up_count += 1
        state.post_resolution_check_pending = False
        return state

    def set_response_style(self, call_sid: str, response_style: str) -> IssueResolutionState:
        state = self.get_state(call_sid)
        state.response_style = response_style
        return state

    def mark_identity_verified(self, call_sid: str) -> IssueResolutionState:
        state = self.get_state(call_sid)
        state.identity_verified = True
        return state

    def mark_issue_resolved(self, call_sid: str) -> IssueResolutionState:
        state = self.get_state(call_sid)
        state.business_state = CONFIRMATION_CLOSING
        state.issue_type = None
        state.symptom = None
        state.follow_up_count = 0
        state.post_resolution_check_pending = True
        return state

    def clear_post_resolution_check(self, call_sid: str) -> IssueResolutionState:
        state = self.get_state(call_sid)
        state.post_resolution_check_pending = False
        return state

    def clear_issue(self, call_sid: str) -> IssueResolutionState:
        state = self.get_state(call_sid)
        state.issue_type = None
        state.symptom = None
        state.follow_up_count = 0
        return state

    def reset(self, call_sid: str) -> None:
        self._states.pop(call_sid, None)


_issue_resolution_service: IssueResolutionService | None = None


def get_issue_resolution_service() -> IssueResolutionService:
    global _issue_resolution_service
    if _issue_resolution_service is None:
        _issue_resolution_service = IssueResolutionService()
    return _issue_resolution_service
