# BOBCards Voice Assistant: Development Plan

## 1. Project Overview

This document outlines the development and enhancement plan for the BOBCards Voice Assistant. The project is a production-structured MVP of a phone-based banking voice assistant using Twilio, FastAPI, Sarvam AI for STT/TTS, and Google Gemini for language model capabilities.

The primary goal is to create a robust, reliable, and human-like voice agent that can assist customers with BOB Card registration issues and other banking-related queries over a live phone call.

## 2. Current State Analysis

The MVP is well-structured with a clear separation of concerns.

-   **Core Services**: The application is built around distinct services for Telephony (`twilio_service`), Speech-to-Text (`sarvam_stt_service`), Language Model (`gemini_service`), and Text-to-Speech (`sarvam_tts_service`).
-   **Conversation Logic**: The main orchestration happens in `conversation_service.py`, which manages the call flow, state, and interaction between the different services.
-   **Prompt Engineering**: The agent's persona, goals, and guardrails are well-defined in `prompts.py`. This is the "brain" of the agent's character.
-   **Rule-Based Guidance**: A significant portion of the issue resolution logic is currently handled by a sophisticated rule-based system in `issue_guidance.py`. This provides fast, deterministic responses for common, well-defined problems.
-   **Hybrid AI Model**: The system uses a hybrid approach:
    1.  **Deterministic Rules (`issue_guidance.py`)**: For high-confidence, quick-path resolutions (e.g., "Aadhaar upload failed").
    2.  **Generative AI (`gemini_service.py`)**: For more nuanced, conversational, or less-defined user queries, falling back to the rule-based system if the LLM response is weak.
-   **API & Entrypoints**: The `api/routes/twilio.py` file defines the webhooks for Twilio, serving as the primary entry point for all call-related interactions.
-   **Realtime Dashboard**: A functional dashboard exists (`dashboard/`) for monitoring calls in real-time, with a WebRTC layer scaffolded for future enhancements.
-   **Configuration**: The system is highly configurable via `config.py` and environment variables, allowing for easy changes to models, providers, and behavior.

## 3. Development & Enhancement Plan

This plan is structured in phases to ensure iterative and stable development.

### Phase 1: Stabilize and Test

The immediate priority is to ensure the existing system is robust, reliable, and testable.

1.  **Implement Comprehensive Testing**:
    -   **Unit Tests**: Create unit tests for helper functions and standalone logic, especially within `issue_guidance.py` and `conversation_prompts.py`, to verify the deterministic parts of the system.
    -   **Integration Tests**: Develop integration tests for the main services (`ConversationService`, `GeminiService`, etc.). Mock external dependencies (Twilio, Sarvam, Gemini APIs) to test the service interactions without making live API calls.
    -   **End-to-End (E2E) Tests**: Create a testing script that can place a call (or simulate a webhook) and follow a predefined conversation script to validate the full flow.

2.  **Refine Error Handling & Resilience**:
    -   Systematically review all external API calls (`httpx` requests) and implement a more robust retry mechanism with exponential backoff for transient network errors.
    -   Enhance logging to provide more context on failures, including request/response payloads where appropriate (and safe).

3.  **Add Security Hardening**:
    -   **Twilio Request Validation**: Implement the Twilio request signature validation middleware as mentioned in the `README.md`. This is critical for ensuring that webhooks are genuinely from Twilio.
    -   **Input Sanitization**: While some sanitization is present, conduct a full review to prevent any potential injection or abuse, especially in API endpoints that accept user input.

### Phase 2: Enhance Core Capabilities

Once the system is stable, focus on improving the core user experience and operational efficiency.

1.  **Improve State Management**:
    -   The `README.md` notes that conversation state is managed via SQLite history. For higher call volumes and more complex stateful interactions, evaluate and implement a dedicated in-memory store like Redis.
    -   This will allow for faster state retrieval and the ability to manage more complex session data (e.g., multi-turn issue resolution state) without repeated DB queries.

2.  **Evolve the Hybrid AI Model**:
    -   **Dynamic Prompting**: Instead of relying solely on the static `SYSTEM_PROMPT`, make the prompt generation in `gemini_service.py` more dynamic. Inject the current `issue_type` and `symptom` from `IssueResolutionService` directly into the Gemini prompt to give the LLM better context for generating more specific and helpful replies.
    -   **Reduce LLM "Weak Replies"**: The current `_normalize_reply` function in `gemini_service.py` has logic to discard weak replies. Enhance this by training or fine-tuning the model to avoid these generic responses, or by improving the fallback logic to be more context-aware.

3.  **Implement Full Human Handoff**:
    -   **Define Triggers**: Solidify the triggers for handoff (e.g., specific keywords, high frustration score, max turns exceeded, explicit user request).
    -   **TwiML Logic**: Implement the backend logic to generate the necessary TwiML (`<Dial>` or `<Enqueue>`) to transfer the call to a human agent queue or a direct number.
    -   **API Endpoint**: Create a new API endpoint that the agent can call to initiate the handoff process.

### Phase 3: Expand Features and Scale

With a stable and capable core, the focus can shift to adding new features and preparing for scale.

1.  **Activate WebRTC Layer**:
    -   Complete the implementation of the WebRTC media bridge as scaffolded in `dashboard/app.js` and the `webrtc` API routes.
    -   This will enable agents/developers to listen in on live calls or even participate directly from the browser, which is invaluable for testing, quality assurance, and debugging.

2.  **Expand Language Support**:
    -   The architecture supports multiple languages. Create a clear process for adding a new one.
    -   This involves:
        1.  Adding new prompt translations to `conversation_prompts.py` and `issue_guidance.py`.
        2.  Updating language detection logic in `conversation_service.py`.
        3.  Ensuring the TTS provider (`sarvam_tts_service.py`) supports the new language and voice.

3.  **CI/CD and Deployment Automation**:
    -   Set up a CI/CD pipeline (e.g., using GitHub Actions).
    -   **On Push/PR**: Automatically run linters, formatters, and the full test suite (unit and integration).
    -   **On Merge to Main**: Automatically build and push the Docker image to a container registry and deploy to a staging environment.

4.  **Monitoring and Observability**:
    -   Integrate a dedicated monitoring tool (e.g., Prometheus, Grafana, Datadog).
    -   Export key metrics: call volume, call duration, API latencies (STT, LLM, TTS), error rates, and conversation outcomes (`final_outcome` in the `Call` model).
    -   This will provide critical insights into system performance and user behavior.

---

This plan provides a structured roadmap for evolving the BOBCards Voice Assistant from a strong MVP into a fully-featured, production-ready application. By prioritizing stability and testing first, the project can scale and add features on a solid foundation.