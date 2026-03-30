import { WebRTCClientManager } from "./webrtc.js";

const elements = {
  customerNameInput: document.getElementById("customerNameInput"),
  mobileNumberInput: document.getElementById("mobileNumberInput"),
  languageSelect: document.getElementById("languageSelect"),
  demoApplicantSelect: document.getElementById("demoApplicantSelect"),
  placeCallButton: document.getElementById("placeCallButton"),
  callSidInput: document.getElementById("callSidInput"),
  clientIdInput: document.getElementById("clientIdInput"),
  connectWsButton: document.getElementById("connectWsButton"),
  disconnectWsButton: document.getElementById("disconnectWsButton"),
  subscribeButton: document.getElementById("subscribeButton"),
  loadCallsButton: document.getElementById("loadCallsButton"),
  enableMicButton: document.getElementById("enableMicButton"),
  disableMicButton: document.getElementById("disableMicButton"),
  startSessionButton: document.getElementById("startSessionButton"),
  closeSessionButton: document.getElementById("closeSessionButton"),
  wsState: document.getElementById("wsState"),
  micState: document.getElementById("micState"),
  rtcState: document.getElementById("rtcState"),
  callState: document.getElementById("callState"),
  qualityState: document.getElementById("qualityState"),
  fallbackState: document.getElementById("fallbackState"),
  timerState: document.getElementById("timerState"),
  recentCalls: document.getElementById("recentCalls"),
  eventLog: document.getElementById("eventLog"),
  transcriptLog: document.getElementById("transcriptLog"),
  sessionDetails: document.getElementById("sessionDetails"),
  activeCallBadge: document.getElementById("activeCallBadge"),
  conversationStatusBanner: document.getElementById("conversationStatusBanner"),
  journeyStrip: document.getElementById("journeyStrip"),
  processState: document.getElementById("processState"),
  processTimeline: document.getElementById("processTimeline"),
  mainPointsState: document.getElementById("mainPointsState"),
  responsePlanState: document.getElementById("responsePlanState"),
  geminiDecisionState: document.getElementById("geminiDecisionState"),
  ttsStatusState: document.getElementById("ttsStatusState"),
  interruptionStatusState: document.getElementById("interruptionStatusState"),
  callSummaryState: document.getElementById("callSummaryState"),
  sessionBadge: document.getElementById("sessionBadge"),
  localAudio: document.getElementById("localAudio"),
  micProfile: document.getElementById("micProfile"),
  turnsMetric: document.getElementById("turnsMetric"),
  languageMetric: document.getElementById("languageMetric"),
  outcomeMetric: document.getElementById("outcomeMetric"),
  transcriptEmptyState: document.getElementById("transcriptEmptyState"),
  sttLatestMetric: document.getElementById("sttLatestMetric"),
  sttAvgMetric: document.getElementById("sttAvgMetric"),
  geminiLatestMetric: document.getElementById("geminiLatestMetric"),
  geminiAvgMetric: document.getElementById("geminiAvgMetric"),
  ttsLatestMetric: document.getElementById("ttsLatestMetric"),
  ttsAvgMetric: document.getElementById("ttsAvgMetric"),
  sttPipelineState: document.getElementById("sttPipelineState"),
  geminiPipelineState: document.getElementById("geminiPipelineState"),
  ttsPipelineState: document.getElementById("ttsPipelineState"),
};

const baseUrl = window.location.origin;
const websocketUrl = `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/api/ws/realtime`;

let realtimeSocket = null;
let activeCallSid = "";
let transcriptCount = 0;
let pendingSubscriptionCallSid = "";
let transcriptKeys = new Set();
let callLoading = false;
let processEntries = [];
let activeCallPhase = "";
let conversationActivity = {
  customerSpeaking: false,
  assistantThinking: false,
  assistantSpeaking: false,
};
let activeLanguageCode = "hi-IN";
let transcriptAutoScrollPinned = true;
let latencyMetrics = createLatencyMetrics();

const JOURNEY_STAGES = ["requesting", "queued", "connected", "listening", "thinking", "speaking"];

const demoApplicants = [
  { name: "Satish", phone: "+918299805407", language: "hi-IN" },
  { name: "Rajat", phone: "+919910629998", language: "en-IN" },
  { name: "Bhagwati", phone: "+918368532373", language: "hi-IN" },
];

function createLatencyMetrics() {
  return {
    stt: { count: 0, totalMs: 0, latestMs: null },
    gemini: { count: 0, totalMs: 0, latestMs: null },
    tts: { count: 0, totalMs: 0, latestMs: null },
  };
}

function getStepBucket(step) {
  if (step === "sarvam_stt") {
    return "stt";
  }
  if (step === "gemini") {
    return "gemini";
  }
  if (step === "sarvam_tts" || step === "sarvam_tts_cache" || step === "sarvam_tts_first_chunk") {
    return "tts";
  }
  return "";
}

function setPipelinePill(element, label, status) {
  if (!element) {
    return;
  }
  element.textContent = label;
  element.classList.remove("running", "done");
  if (status) {
    element.classList.add(status);
  }
}

function resetLatencyDashboard() {
  latencyMetrics = createLatencyMetrics();
  if (elements.sttLatestMetric) {
    elements.sttLatestMetric.textContent = "-";
  }
  if (elements.sttAvgMetric) {
    elements.sttAvgMetric.textContent = "Avg -";
  }
  if (elements.geminiLatestMetric) {
    elements.geminiLatestMetric.textContent = "-";
  }
  if (elements.geminiAvgMetric) {
    elements.geminiAvgMetric.textContent = "Avg -";
  }
  if (elements.ttsLatestMetric) {
    elements.ttsLatestMetric.textContent = "-";
  }
  if (elements.ttsAvgMetric) {
    elements.ttsAvgMetric.textContent = "Avg -";
  }
  setPipelinePill(elements.sttPipelineState, "STT idle", "");
  setPipelinePill(elements.geminiPipelineState, "Gemini idle", "");
  setPipelinePill(elements.ttsPipelineState, "TTS idle", "");
}

function renderLatencyBucket(bucket) {
  const metric = latencyMetrics[bucket];
  if (!metric || metric.latestMs == null) {
    return;
  }
  const avg = Math.round(metric.totalMs / metric.count);
  if (bucket === "stt") {
    if (elements.sttLatestMetric) {
      elements.sttLatestMetric.textContent = `${metric.latestMs} ms`;
    }
    if (elements.sttAvgMetric) {
      elements.sttAvgMetric.textContent = `Avg ${avg} ms`;
    }
  } else if (bucket === "gemini") {
    if (elements.geminiLatestMetric) {
      elements.geminiLatestMetric.textContent = `${metric.latestMs} ms`;
    }
    if (elements.geminiAvgMetric) {
      elements.geminiAvgMetric.textContent = `Avg ${avg} ms`;
    }
  } else if (bucket === "tts") {
    if (elements.ttsLatestMetric) {
      elements.ttsLatestMetric.textContent = `${metric.latestMs} ms`;
    }
    if (elements.ttsAvgMetric) {
      elements.ttsAvgMetric.textContent = `Avg ${avg} ms`;
    }
  }
}

function updateLatencyMetrics(event) {
  if (!event || event.type !== "latency") {
    return;
  }
  if (activeCallSid && event.call_sid && event.call_sid !== activeCallSid) {
    return;
  }

  const bucket = getStepBucket(event.step || "");
  if (!bucket) {
    return;
  }

  const latencyMs = typeof event.latency_ms === "number" ? Math.round(event.latency_ms) : null;
  if (latencyMs != null) {
    latencyMetrics[bucket].latestMs = latencyMs;
    latencyMetrics[bucket].count += 1;
    latencyMetrics[bucket].totalMs += latencyMs;
    renderLatencyBucket(bucket);
  }

  if (bucket === "stt") {
    setPipelinePill(elements.sttPipelineState, "STT done", "done");
  } else if (bucket === "gemini") {
    setPipelinePill(elements.geminiPipelineState, "Gemini done", "done");
  } else if (bucket === "tts") {
    setPipelinePill(elements.ttsPipelineState, "TTS done", "done");
  }
}

function scrollTranscriptToBottom(force = false) {
  if (!elements.transcriptLog) {
    return;
  }
  if (force || transcriptAutoScrollPinned) {
    elements.transcriptLog.scrollTop = elements.transcriptLog.scrollHeight;
  }
}

function setupTranscriptAutoScrollTracking() {
  if (!elements.transcriptLog) {
    return;
  }
  elements.transcriptLog.addEventListener("scroll", () => {
    const nearBottom =
      elements.transcriptLog.scrollTop + elements.transcriptLog.clientHeight >= elements.transcriptLog.scrollHeight - 80;
    transcriptAutoScrollPinned = nearBottom;
  });
}

function initializeDemoApplicants() {
  if (!elements.demoApplicantSelect) {
    return;
  }

  for (const applicant of demoApplicants) {
    const option = document.createElement("option");
    option.value = JSON.stringify(applicant);
    option.textContent = `${applicant.name} · ${applicant.phone}`;
    elements.demoApplicantSelect.appendChild(option);
  }

  elements.demoApplicantSelect.addEventListener("change", () => {
    if (!elements.demoApplicantSelect.value) {
      return;
    }
    const applicant = JSON.parse(elements.demoApplicantSelect.value);
    if (elements.customerNameInput) {
      elements.customerNameInput.value = applicant.name;
    }
    if (elements.mobileNumberInput) {
      elements.mobileNumberInput.value = applicant.phone;
    }
    if (elements.languageSelect) {
      elements.languageSelect.value = applicant.language;
    }
    appendLog(`Loaded demo applicant ${applicant.name}.`);
  });
}

async function placeCustomerCall() {
  if (!elements.mobileNumberInput || !elements.customerNameInput) {
    appendLog("UI inputs are not ready. Please refresh the dashboard.");
    return;
  }
  const mobileNumber = elements.mobileNumberInput.value.trim();
  const customerName = elements.customerNameInput.value.trim();
  const language = elements.languageSelect ? elements.languageSelect.value : "hi-IN";

  if (!mobileNumber) {
    appendLog("Enter the customer's mobile number first.");
    return;
  }

  setCallButtonLoading(true);
  setConversationBanner("loading", "Creating outbound call request...");
  setJourneyStage("requesting");
  appendProcess("Requesting call", `Submitting outbound call for ${mobileNumber}.`);

  if (!realtimeSocket || realtimeSocket.readyState !== WebSocket.OPEN) {
    pendingSubscriptionCallSid = "";
    connectRealtime();
  }

  //start the user calls
  const response = await fetch(`${baseUrl}/api/twilio/outbound-call`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      mobile_number: mobileNumber,
      customer_name: customerName,
      language,
    }),
  });

  const payload = await response.json();
  if (!response.ok) {
    setCallButtonLoading(false);
    setConversationBanner("error", payload.detail || "Unable to start the call.");
    appendProcess("Call failed", payload.detail || "Outbound call request failed.");
    appendLog(`Call start failed: ${payload.detail || "unknown error"}`);
    return;
  }

  if (elements.callSidInput) {
    elements.callSidInput.value = payload.call_sid;
  }
  activeCallSid = payload.call_sid;
  pendingSubscriptionCallSid = payload.call_sid;
  elements.activeCallBadge.textContent = payload.call_sid;
  setState({
    callState: payload.status,
    languageMetric: language,
    outcomeMetric: "-",
  });
  setConversationBanner("loading", `Call queued for ${payload.customer_name || mobileNumber}. Waiting for Twilio to connect...`);
  setJourneyStage("queued");
  appendProcess("Call queued", `Twilio accepted the outbound call request for ${payload.mobile_number}.`);
  appendLog(`Outbound call queued for ${payload.mobile_number} (${payload.customer_name || "no name"}).`);

  if (realtimeSocket && realtimeSocket.readyState === WebSocket.OPEN) {
    clearTranscript({ preserveProcess: true });
    subscribeToRealtimeCall(payload.call_sid);
  }
}

function appendLog(message, target = elements.eventLog) {
  const entry = document.createElement("div");
  entry.className = "log-entry";
  const timestamp = new Date().toLocaleTimeString();
  entry.textContent = `[${timestamp}] ${message}`;
  target.prepend(entry);
}

function setCallButtonLoading(isLoading) {
  callLoading = isLoading;
  if (!elements.placeCallButton) {
    return;
  }
  elements.placeCallButton.disabled = isLoading;
  elements.placeCallButton.textContent = isLoading ? "Calling..." : "Initiate Call";
}

function appendProcess(title, detail) {
  if (!elements.processTimeline) {
    return;
  }
  const timestamp = new Date().toLocaleTimeString();
  processEntries.unshift({ title, detail, timestamp });
  processEntries = processEntries.slice(0, 10);
  elements.processTimeline.innerHTML = processEntries
    .map(
      (item) => `
        <div class="process-item">
          <strong>${item.title}</strong>
          <span>${item.detail}</span>
          <span>${item.timestamp}</span>
        </div>
      `,
    )
    .join("");
}

function setConversationBanner(kind, text) {
  if (!elements.conversationStatusBanner) {
    return;
  }
  elements.conversationStatusBanner.className = `conversation-banner ${kind}`;
  elements.conversationStatusBanner.textContent = text;
}

function setJourneyStage(activeStage) {
  if (!elements.journeyStrip) {
    return;
  }
  const activeIndex = JOURNEY_STAGES.indexOf(activeStage);
  const steps = elements.journeyStrip.querySelectorAll(".journey-step");
  for (const step of steps) {
    const stage = step.dataset.stage;
    const stageIndex = JOURNEY_STAGES.indexOf(stage);
    step.classList.remove("active", "complete");
    if (activeStage && stageIndex > -1 && activeIndex > -1) {
      if (stageIndex < activeIndex) {
        step.classList.add("complete");
      } else if (stageIndex === activeIndex) {
        step.classList.add("active");
      }
    }
  }
  if (elements.processState) {
    elements.processState.textContent = activeStage || "idle";
  }
}

function formatPhaseLabel(phase) {
  return (phase || "idle").replaceAll("_", " ");
}

function renderMainPoints(mainPoints) {
  if (!elements.mainPointsState) {
    return;
  }
  if (!mainPoints) {
    elements.mainPointsState.textContent = "Waiting for the first customer turn.";
    return;
  }

  const lines = [
    `Intent: ${mainPoints.primary_intent || "-"}`,
    `Language: ${mainPoints.language || "-"}${mainPoints.selected_language ? ` (switch -> ${mainPoints.selected_language})` : ""}`,
    `Consent: ${mainPoints.consent_choice || "-"}`,
    `Issue: ${mainPoints.issue_type || "-"}`,
    `Symptom: ${mainPoints.symptom || "-"}`,
    `Reliable: ${mainPoints.transcript_reliable ? "yes" : "no"}`,
    `Confidence: ${typeof mainPoints.confidence === "number" ? mainPoints.confidence.toFixed(3) : "-"} (${mainPoints.confidence_source || "-"})`,
    `Noisy/Fallback: ${mainPoints.noisy_call ? "noisy" : "clear"} / ${mainPoints.fallback_mode ? "fallback" : "normal"}`,
    `Transcript: ${mainPoints.transcript_preview || "-"}`,
  ];
  elements.mainPointsState.textContent = lines.join("\n");
}

function renderResponsePlan(responsePlan) {
  if (!elements.responsePlanState) {
    return;
  }
  if (!responsePlan) {
    elements.responsePlanState.textContent = "Waiting for the first plan.";
    return;
  }

  const lines = [
    `Route: ${responsePlan.route || "-"}`,
    `Objective: ${responsePlan.objective || "-"}`,
    `Source: ${responsePlan.response_source || "-"}`,
    `Mode: ${responsePlan.reply_mode || "-"}`,
    `Gemini: ${responsePlan.use_gemini ? "yes" : "no"}`,
    `Hangup: ${responsePlan.should_hangup ? "yes" : "no"}`,
    `Issue: ${responsePlan.issue_type || "-"}`,
    `Symptom: ${responsePlan.symptom || "-"}`,
    `Language: ${responsePlan.language || "-"}`,
  ];
  elements.responsePlanState.textContent = lines.join("\n");
}

function renderGeminiDecision(geminiDecision) {
  if (!elements.geminiDecisionState) {
    return;
  }
  if (!geminiDecision) {
    elements.geminiDecisionState.textContent = "Waiting for the first Gemini decision.";
    return;
  }

  const lines = [
    `Source: ${geminiDecision.source || "-"}`,
    `Fallback Used: ${geminiDecision.used_fallback ? "yes" : "no"}`,
    `Fallback Reason: ${geminiDecision.fallback_reason || "-"}`,
    `Provider Success: ${geminiDecision.provider_success ? "yes" : "no"}`,
    `Model: ${geminiDecision.model || "-"}`,
    `Language: ${geminiDecision.language_code || "-"}`,
    `Mode: ${geminiDecision.response_mode || "-"}`,
    `Style: ${geminiDecision.response_style || "-"}`,
    `Issue: ${geminiDecision.active_issue_type || "-"}`,
    `Reply Preview: ${geminiDecision.text_preview || "-"}`,
  ];
  elements.geminiDecisionState.textContent = lines.join("\n");
}

function renderTtsStatus(ttsStatus) {
  if (!elements.ttsStatusState) {
    return;
  }
  if (!ttsStatus) {
    elements.ttsStatusState.textContent = "Waiting for the first TTS event.";
    return;
  }

  const lines = [
    `Stage: ${ttsStatus.stage || "-"}`,
    `Codec: ${ttsStatus.codec || "-"}`,
    `Language: ${ttsStatus.language || "-"}`,
    `Chunk Kind: ${ttsStatus.chunk_kind || "-"}`,
    `Chunk Bytes: ${typeof ttsStatus.chunk_bytes === "number" ? ttsStatus.chunk_bytes : "-"}`,
    `Audio Bytes: ${typeof ttsStatus.audio_bytes === "number" ? ttsStatus.audio_bytes : "-"}`,
    `Text Preview: ${ttsStatus.text_preview || "-"}`,
  ];
  elements.ttsStatusState.textContent = lines.join("\n");
}

function renderInterruptionStatus(interruptionStatus) {
  if (!elements.interruptionStatusState) {
    return;
  }
  if (!interruptionStatus) {
    elements.interruptionStatusState.textContent = "Waiting for the first interruption event.";
    return;
  }

  const lines = [
    `Stage: ${interruptionStatus.stage || "-"}`,
    `Reason: ${interruptionStatus.reason || "-"}`,
    `Count: ${typeof interruptionStatus.count === "number" ? interruptionStatus.count : "-"}`,
    `Speech ms: ${typeof interruptionStatus.speech_ms === "number" ? interruptionStatus.speech_ms : "-"}`,
  ];
  elements.interruptionStatusState.textContent = lines.join("\n");
}

function renderCallSummary(callSummary) {
  if (!elements.callSummaryState) {
    return;
  }
  if (!callSummary) {
    elements.callSummaryState.textContent = "Waiting for the first completed summary.";
    return;
  }

  const lines = [
    `Status: ${callSummary.status || "-"}`,
    `Phase: ${callSummary.phase || "-"}`,
    `Language: ${callSummary.language || "-"}`,
    `Outcome: ${callSummary.final_outcome || "-"}`,
    `Duration: ${typeof callSummary.duration_seconds === "number" ? `${callSummary.duration_seconds}s` : "-"}`,
    `Customer Turns: ${callSummary.customer_turns ?? "-"}`,
    `Assistant Turns: ${callSummary.assistant_turns ?? "-"}`,
    `Total Transcripts: ${callSummary.total_transcripts ?? "-"}`,
    `Gemini Requests/Fallbacks: ${callSummary.gemini_requests ?? 0} / ${callSummary.gemini_fallbacks ?? 0}`,
    `TTS Requests/Playback: ${callSummary.tts_requests ?? 0} / ${callSummary.playback_starts ?? 0}`,
    `Interruptions: ${callSummary.interruptions ?? 0}`,
  ];
  elements.callSummaryState.textContent = lines.join("\n");
}

function applyCallPhase(phase, status) {
  if (!phase || phase === activeCallPhase) {
    return;
  }

  activeCallPhase = phase;
  if (elements.processState) {
    elements.processState.textContent = formatPhaseLabel(phase);
  }

  if (phase === "call_bootstrap") {
    setConversationBanner("loading", "The assistant is preparing the live call session.");
    appendProcess("Call bootstrap", "The call record is ready and Twilio is being moved into the media stream.");
    return;
  }

  if (phase === "greeting") {
    setJourneyStage("connected");
    setConversationBanner("active", "The assistant is delivering the opening greeting.");
    appendProcess("Greeting", "The opening BOBCards greeting is now being played to the caller.");
    return;
  }

  if (phase === "listening" && status !== "completed") {
    setJourneyStage("listening");
    setConversationBanner("active", "Greeting finished. The assistant is ready for the customer's response.");
    appendProcess("Listening", "The assistant is waiting for the next customer turn.");
    return;
  }

  if (phase === "customer_speaking") {
    setJourneyStage("listening");
    setConversationBanner("active", "The customer is speaking. Audio is being buffered live.");
    appendProcess("Customer speaking", "Speech started and the utterance buffer is collecting audio.");
    return;
  }

  if (phase === "silence_detected") {
    setJourneyStage("thinking");
    setConversationBanner("active", "Silence detected. Finalizing the customer's utterance.");
    appendProcess("Silence detected", "The pause threshold was reached and the current utterance is being closed.");
    return;
  }

  if (phase === "utterance_finalized") {
    setJourneyStage("thinking");
    setConversationBanner("active", "Utterance finalized. Preparing it for transcription.");
    appendProcess("Utterance finalized", "A complete customer turn is ready for STT.");
    return;
  }

  if (phase === "transcribing") {
    setPipelinePill(elements.sttPipelineState, "STT running", "running");
    setJourneyStage("thinking");
    setConversationBanner("active", "Transcribing the customer's utterance.");
    appendProcess("Transcribing", "Audio was sent to STT and the transcript is being generated.");
    return;
  }

  if (phase === "main_points_ready") {
    setJourneyStage("thinking");
    setConversationBanner("active", "Main points extracted. The assistant can now prepare the response.");
    appendProcess("Main points ready", "Intent, issue, symptom, and language signals were extracted from the turn.");
    return;
  }

  if (phase === "planning_response") {
    setJourneyStage("thinking");
    setConversationBanner("active", "Planning the next response path.");
    appendProcess("Planning response", "The planner is choosing between prompt, rule, fallback, and Gemini routes.");
    return;
  }

  if (phase === "response_plan_ready") {
    setJourneyStage("thinking");
    setConversationBanner("active", "Response plan ready. The assistant is preparing the selected reply.");
    appendProcess("Response plan ready", "A concrete response route was selected for the next turn.");
    return;
  }

  if (phase === "gemini_requested") {
    setPipelinePill(elements.geminiPipelineState, "Gemini running", "running");
    setJourneyStage("thinking");
    setConversationBanner("active", "Gemini was requested for this turn.");
    appendProcess("Gemini requested", "The planner selected a Gemini-backed response path.");
    return;
  }

  if (phase === "gemini_reply_ready") {
    setJourneyStage("thinking");
    setConversationBanner("active", "Gemini reply validated and ready.");
    appendProcess("Gemini reply ready", "The model response passed validation and can be spoken.");
    return;
  }

  if (phase === "gemini_fallback_used") {
    setJourneyStage("thinking");
    setConversationBanner("active", "Gemini fallback was used for this turn.");
    appendProcess("Gemini fallback", "The Gemini response was replaced with a deterministic fallback.");
    return;
  }

  if (phase === "tts_requested") {
    setPipelinePill(elements.ttsPipelineState, "TTS running", "running");
    setJourneyStage("thinking");
    setConversationBanner("active", "TTS requested. Preparing the spoken reply.");
    appendProcess("TTS requested", "Speech synthesis was requested for the prepared reply.");
    return;
  }

  if (phase === "tts_first_chunk_ready") {
    setJourneyStage("thinking");
    setConversationBanner("active", "The first TTS chunk is ready. Playback is about to begin.");
    appendProcess("TTS first chunk", "The first chunk of synthesized audio is ready for playback.");
    return;
  }

  if (phase === "playback_started") {
    setJourneyStage("speaking");
    setConversationBanner("active", "Playback started. The assistant is speaking now.");
    appendProcess("Playback started", "The synthesized reply is now streaming back to the caller.");
    return;
  }

  if (phase === "barge_in_confirmed") {
    setJourneyStage("listening");
    setConversationBanner("active", "Barge-in confirmed. The caller interrupted the assistant.");
    appendProcess("Barge-in confirmed", "Customer speech crossed the interruption threshold.");
    return;
  }

  if (phase === "playback_cancelling") {
    setJourneyStage("listening");
    setConversationBanner("active", "Cancelling assistant playback.");
    appendProcess("Playback cancelling", "The current audio reply is being stopped to let the caller speak.");
    return;
  }

  if (phase === "playback_interrupted") {
    setJourneyStage("listening");
    setConversationBanner("active", "Playback interrupted. Switching back to caller audio.");
    appendProcess("Playback interrupted", "The live stream cleared the assistant audio buffer.");
    return;
  }

  if (phase === "listening_resumed") {
    setJourneyStage("listening");
    setConversationBanner("active", "Listening resumed after interruption.");
    appendProcess("Listening resumed", "The assistant is back in listening mode after the interruption.");
    return;
  }

  if (phase === "call_summary_ready") {
    setJourneyStage("");
    setConversationBanner("ended", "Call summary is ready.");
    appendProcess("Call summary ready", "The final runtime summary for the call has been assembled.");
    return;
  }

  if (phase === "session_cleanup") {
    setPipelinePill(elements.sttPipelineState, "STT idle", "");
    setPipelinePill(elements.geminiPipelineState, "Gemini idle", "");
    setPipelinePill(elements.ttsPipelineState, "TTS idle", "");
    setJourneyStage("");
    setConversationBanner("ended", "Session cleanup completed.");
    appendProcess("Session cleanup", "Transient runtime state is being finalized for this call.");
  }
}

function removeLoader(role) {
  const existing = elements.transcriptLog.querySelector(`.transcript-entry.loader.${role}`);
  if (existing) {
    existing.remove();
  }
}

function showLoader(role, label) {
  if (!elements.transcriptLog) {
    return;
  }

  removeLoader(role);
  if (elements.transcriptEmptyState) {
    elements.transcriptEmptyState.style.display = "none";
  }

  const row = document.createElement("div");
  row.className = `transcript-entry loader ${role}`;
  const speakerLabel = role === "assistant" ? "BOBCards AI" : "Customer";
  row.innerHTML = `
    <span class="speaker">${speakerLabel}</span>
    <div class="loader-pill">
      <span class="typing-dots" aria-hidden="true">
        <i></i><i></i><i></i>
      </span>
      <span class="loader-label">${label}</span>
    </div>
  `;
  elements.transcriptLog.appendChild(row);
  scrollTranscriptToBottom();
}

function updateConversationActivity() {
  if (conversationActivity.customerSpeaking) {
    showLoader("customer", "Listening...");
    setJourneyStage("listening");
    setConversationBanner("active", "Customer is speaking. Capturing the response...");
    appendProcess("Customer speaking", "Live audio is being captured for transcription.");
  } else {
    removeLoader("customer");
  }

  if (conversationActivity.assistantThinking || conversationActivity.assistantSpeaking) {
    const label = conversationActivity.assistantSpeaking ? "Speaking..." : "Thinking...";
    showLoader("assistant", label);
    setJourneyStage(conversationActivity.assistantSpeaking ? "speaking" : "thinking");
    setConversationBanner(
      "active",
      conversationActivity.assistantSpeaking
        ? "AI is speaking the next response."
        : "AI is analyzing the user's problem and preparing the next step.",
    );
  } else {
    removeLoader("assistant");
  }
}

function renderTranscript(event) {
  const transcriptKey = `${event.speaker}|${event.timestamp}|${event.text}`;
  if (transcriptKeys.has(transcriptKey)) {
    return;
  }
  transcriptKeys.add(transcriptKey);

  if (elements.transcriptEmptyState) {
    elements.transcriptEmptyState.style.display = "none";
  }
  const turnMeta = classifyTurn(event);
  const row = document.createElement("div");
  row.className = `transcript-entry ${event.speaker === "assistant" ? "assistant" : "customer"}`;
  const speakerLabel = event.speaker === "assistant" ? "BOBCards AI" : "Customer";
  row.innerHTML = `
    <span class="speaker">${speakerLabel}</span>
    <p>${event.text}</p>
    <div class="turn-meta">
      <time>${new Date(event.timestamp).toLocaleTimeString()}</time>
      <span class="turn-chip language">${turnMeta.language}</span>
      ${turnMeta.tag ? `<span class="turn-chip type">${turnMeta.tag}</span>` : ""}
    </div>
  `;

  removeLoader(event.speaker === "assistant" ? "assistant" : "customer");
  elements.transcriptLog.appendChild(row);
  scrollTranscriptToBottom();
  transcriptCount += 1;
  if (elements.turnsMetric) {
    elements.turnsMetric.textContent = String(transcriptCount);
  }
}

function formatElapsed(seconds) {
  const mins = String(Math.floor(seconds / 60)).padStart(2, "0");
  const secs = String(seconds % 60).padStart(2, "0");
  return `${mins}:${secs}`;
}

function setState(updates) {
  if (updates.wsState) {
    elements.wsState.textContent = updates.wsState;
  }
  if (updates.micState) {
    elements.micState.textContent = updates.micState;
  }
  if (updates.rtcState) {
    elements.rtcState.textContent = updates.rtcState;
  }
  if (updates.callState) {
    elements.callState.textContent = updates.callState;
  }
  if (updates.languageMetric) {
    elements.languageMetric.textContent = updates.languageMetric;
    activeLanguageCode = updates.languageMetric;
  }
  if (updates.outcomeMetric) {
    elements.outcomeMetric.textContent = updates.outcomeMetric;
  }
  if (updates.qualityState) {
    elements.qualityState.textContent = updates.qualityState;
  }
  if (updates.fallbackState) {
    elements.fallbackState.textContent = updates.fallbackState;
  }
  if (typeof updates.elapsedSeconds === "number") {
    elements.timerState.textContent = formatElapsed(updates.elapsedSeconds);
  }
  if (updates.micProfile) {
    elements.micProfile.textContent = updates.micProfile;
  }
  if (updates.session && elements.sessionDetails && elements.sessionBadge) {
    elements.sessionDetails.textContent = JSON.stringify(updates.session, null, 2);
    elements.sessionBadge.textContent = updates.session.session_id || "No session";
  }
}

function classifyTurn(event) {
  const text = (event.text || "").toLowerCase();
  const language = event.language || event.language_code || activeLanguageCode || elements.languageMetric.textContent || "hi-IN";
  let tag = "";

  if (event.speaker === "assistant") {
    if (
      text.includes("दो मिनट बात करना ठीक रहेगा") ||
      text.includes("good time to speak") ||
      text.includes("एआई वॉइस असिस्टेंट")
    ) {
      tag = "greeting";
    } else if (text.includes("किस जगह पर आपको परेशानी") || text.includes("which step is causing trouble")) {
      tag = "issue-capture";
    } else if (text.includes("दोबारा बोलिए") || text.includes("please repeat")) {
      tag = "clarify";
    } else if (text.includes("एरर मैसेज") || text.includes("error message")) {
      tag = "resolution";
    } else {
      tag = "response";
    }
  } else {
    if (
      text.includes("जी हाँ") ||
      text.includes("हाँ") ||
      text.includes("baat kar sakte") ||
      text.includes("we can talk") ||
      text.includes("yes")
    ) {
      tag = "consent";
    } else if (text.includes("एरर") || text.includes("problem") || text.includes("प्रॉब्लम")) {
      tag = "issue";
    }
  }

  return { language, tag };
}

function clearTranscript(options = {}) {
  const {
    preserveProcess = false,
    preserveMainPoints = false,
    preserveResponsePlan = false,
    preserveGeminiDecision = false,
    preserveTtsStatus = false,
    preserveInterruptionStatus = false,
    preserveCallSummary = false,
    preserveLatency = false,
  } = options;
  elements.transcriptLog.innerHTML = "";
  transcriptAutoScrollPinned = true;
  transcriptCount = 0;
  transcriptKeys = new Set();
  activeCallPhase = "";
  if (!preserveLatency) {
    resetLatencyDashboard();
  }
  if (!preserveProcess) {
    processEntries = [];
    if (elements.processTimeline) {
      elements.processTimeline.innerHTML = "";
    }
  }
  conversationActivity = {
    customerSpeaking: false,
    assistantThinking: false,
    assistantSpeaking: false,
  };
  if (elements.turnsMetric) {
    elements.turnsMetric.textContent = "0";
  }
  if (elements.transcriptEmptyState) {
    elements.transcriptEmptyState.style.display = "";
  }
  scrollTranscriptToBottom(true);
  if (!preserveMainPoints) {
    renderMainPoints(null);
  }
  if (!preserveResponsePlan) {
    renderResponsePlan(null);
  }
  if (!preserveGeminiDecision) {
    renderGeminiDecision(null);
  }
  if (!preserveTtsStatus) {
    renderTtsStatus(null);
  }
  if (!preserveInterruptionStatus) {
    renderInterruptionStatus(null);
  }
  if (!preserveCallSummary) {
    renderCallSummary(null);
  }
  if (!preserveProcess) {
    setJourneyStage("");
    setConversationBanner("idle", "Waiting for a call to start.");
  }
}

async function loadConversationHistory(callSid, options = {}) {
  const { preserveLatency = false } = options;
  if (!callSid) {
    return;
  }

  const response = await fetch(`${baseUrl}/api/webrtc/calls/${encodeURIComponent(callSid)}/conversation`);
  if (!response.ok) {
    appendLog(`Could not load conversation history for ${callSid}.`);
    return;
  }

  const events = await response.json();
  clearTranscript({
    preserveProcess: true,
    preserveMainPoints: true,
    preserveResponsePlan: true,
    preserveGeminiDecision: true,
    preserveTtsStatus: true,
    preserveInterruptionStatus: true,
    preserveCallSummary: true,
    preserveLatency,
  });
  for (const event of events) {
    renderTranscript(event);
  }

  if (!events.length && elements.transcriptEmptyState) {
    elements.transcriptEmptyState.style.display = "";
  }
}

function subscribeToRealtimeCall(callSid) {
  if (!realtimeSocket || realtimeSocket.readyState !== WebSocket.OPEN || !callSid) {
    pendingSubscriptionCallSid = callSid || pendingSubscriptionCallSid;
    return;
  }

  pendingSubscriptionCallSid = "";
  realtimeSocket.send(JSON.stringify({ action: "subscribe", call_sid: callSid }));
  appendLog(`Subscribed to ${callSid}.`);
}

function connectRealtime() {
  if (realtimeSocket && realtimeSocket.readyState === WebSocket.OPEN) {
    return;
  }

  realtimeSocket = new WebSocket(websocketUrl);
  setState({ wsState: "connecting" });

  realtimeSocket.onopen = () => {
    setState({ wsState: "connected" });
    appendLog("Realtime WebSocket connected.");
    if (pendingSubscriptionCallSid || activeCallSid) {
      subscribeToRealtimeCall(pendingSubscriptionCallSid || activeCallSid);
    }
  };

  realtimeSocket.onclose = () => {
    setState({ wsState: "disconnected" });
    appendLog("Realtime WebSocket disconnected.");
  };

  realtimeSocket.onerror = () => {
    appendLog("Realtime WebSocket error.");
  };

  realtimeSocket.onmessage = (message) => {
    const event = JSON.parse(message.data);
    if (event.type === "snapshot") {
      elements.callState.textContent = event.call_state?.status || "unknown";
      elements.activeCallBadge.textContent = event.call_sid || "No active call";
      setState({
        languageMetric: event.call_state?.language || elements.languageMetric.textContent,
        outcomeMetric: event.call_state?.final_outcome || "-",
      });
      if (event.call_state?.audio_quality) {
        setState({
          qualityState: event.call_state.audio_quality.last_quality_label || "clear",
          fallbackState: event.call_state.audio_quality.fallback_mode ? "on" : "off",
        });
      }
      if ((event.transcripts || []).length) {
        clearTranscript();
        for (const transcript of event.transcripts || []) {
          renderTranscript(transcript);
        }
      } else {
        loadConversationHistory(event.call_sid, { preserveLatency: true });
      }
      for (const latencyEvent of event.latency_events || []) {
        updateLatencyMetrics(latencyEvent);
      }
      renderMainPoints(event.call_state?.main_points || null);
      renderResponsePlan(event.call_state?.response_plan || null);
      renderGeminiDecision(event.call_state?.gemini_decision || null);
      renderTtsStatus(event.call_state?.tts_status || null);
      renderInterruptionStatus(event.call_state?.interruption_status || null);
      renderCallSummary(event.call_state?.call_summary || null);
      applyCallPhase(event.call_state?.phase, event.call_state?.status);
      appendLog(`Loaded snapshot for ${event.call_sid}.`);
      if (event.call_state?.status === "completed") {
        setConversationBanner("ended", "This call has already ended.");
      } else if (event.call_state?.status === "in-progress") {
        setJourneyStage("connected");
        setConversationBanner("active", "Call connected. Waiting for the next live turn.");
      }
      return;
    }

    if (event.type === "transcript") {
      if (event.speaker === "customer") {
        conversationActivity.customerSpeaking = false;
        conversationActivity.assistantThinking = true;
        conversationActivity.assistantSpeaking = false;
        appendProcess("Customer response received", "Transcription completed. Preparing AI response.");
      } else {
        conversationActivity.assistantThinking = false;
        conversationActivity.assistantSpeaking = false;
        appendProcess("AI response delivered", "The reply was generated and played back to the caller.");
      }
      updateConversationActivity();
      renderTranscript(event);
      appendLog(`${event.speaker === "assistant" ? "AI" : "Customer"}: ${event.text}`);
      return;
    }

    if (event.type === "call_status") {
      setState({
        callState: event.status,
        languageMetric: event.language || elements.languageMetric.textContent,
        outcomeMetric: event.final_outcome || elements.outcomeMetric.textContent,
      });
      applyCallPhase(event.phase, event.status);
      if (event.status === "queued" || event.status === "ringing") {
        setJourneyStage("queued");
        setConversationBanner("loading", "Call is queued and waiting to connect.");
        appendProcess("Call queued", `Call status changed to ${event.status}.`);
      } else if (event.status === "in-progress") {
        setCallButtonLoading(false);
        setJourneyStage("connected");
        setConversationBanner("active", "Call connected. Greeting and live conversation are in progress.");
        appendProcess("Call connected", "Twilio reports the call is now in progress.");
      }
      if (event.status === "completed" || event.status === "failed" || event.status === "canceled" || event.status === "busy" || event.status === "no-answer") {
        conversationActivity.customerSpeaking = false;
        conversationActivity.assistantThinking = false;
        conversationActivity.assistantSpeaking = false;
        updateConversationActivity();
        setCallButtonLoading(false);
        setJourneyStage("");
        const endMessage =
          event.status === "completed"
            ? "Call ended. The customer may have disconnected or the call finished normally."
            : `Call ended with status ${event.status}.`;
        setConversationBanner(event.status === "completed" ? "ended" : "error", endMessage);
        appendProcess("Call ended", endMessage);
      }
      appendLog(`Call ${event.call_sid} status changed to ${event.status}.`);
      return;
    }

    if (event.type === "call_phase") {
      applyCallPhase(event.phase, event.status);
      appendLog(`Call phase changed to ${formatPhaseLabel(event.phase)}.`);
      return;
    }

    if (event.type === "main_points") {
      renderMainPoints(event.main_points || null);
      appendLog("Main points extracted for the latest customer turn.");
      return;
    }

    if (event.type === "response_plan") {
      renderResponsePlan(event.response_plan || null);
      appendLog(`Response plan selected: ${event.response_plan?.route || "unknown"}.`);
      return;
    }

    if (event.type === "gemini_decision") {
      renderGeminiDecision(event.gemini_decision || null);
      appendLog(`Gemini decision: ${event.gemini_decision?.source || "unknown"}.`);
      return;
    }

    if (event.type === "tts_status") {
      renderTtsStatus(event.tts_status || null);
      appendLog(`TTS status: ${event.tts_status?.stage || "unknown"}.`);
      return;
    }

    if (event.type === "interruption_status") {
      renderInterruptionStatus(event.interruption_status || null);
      appendLog(`Interruption status: ${event.interruption_status?.stage || "unknown"}.`);
      return;
    }

    if (event.type === "call_summary") {
      renderCallSummary(event.call_summary || null);
      appendLog("Call summary updated.");
      return;
    }

    if (event.type === "audio_quality") {
      setState({
        qualityState: event.audio_quality?.last_quality_label || "clear",
        fallbackState: event.audio_quality?.fallback_mode ? "on" : "off",
      });
      appendLog(`Audio quality: ${event.audio_quality?.last_quality_label || "clear"}`);
      return;
    }

    if (event.type === "timer") {
      setState({ elapsedSeconds: event.elapsed_seconds });
      return;
    }

    if (event.type === "speaking" || event.type === "user_speaking" || event.type === "ai_speaking") {
      if (event.role === "customer" || event.type === "user_speaking") {
        conversationActivity.customerSpeaking = Boolean(event.is_speaking);
        if (event.is_speaking) {
          conversationActivity.assistantThinking = false;
          conversationActivity.assistantSpeaking = false;
        }
      } else if (event.role === "assistant" || event.type === "ai_speaking") {
        conversationActivity.assistantSpeaking = Boolean(event.is_speaking);
        if (event.is_speaking) {
          conversationActivity.assistantThinking = false;
        }
      }
      updateConversationActivity();
      appendLog(`${event.role} speaking: ${event.is_speaking}`);
      return;
    }

    if (event.type === "barge_in_detected") {
      appendLog("Barge-in detected. Future playback interruption hook can attach here.");
      return;
    }

    if (event.type === "webrtc_session" || event.type === "webrtc_signal") {
      appendLog(`${event.type}: ${JSON.stringify(event)}`);
      return;
    }

    if (event.type === "latency") {
      updateLatencyMetrics(event);
      return;
    }

    appendLog(`Event: ${JSON.stringify(event)}`);
  };
}

function disconnectRealtime() {
  if (!realtimeSocket) {
    return;
  }
  realtimeSocket.close();
  realtimeSocket = null;
}

function subscribeToCall() {
  const callSid = elements.callSidInput ? elements.callSidInput.value.trim() : activeCallSid;
  if (!callSid) {
    appendLog("Enter a Call SID to subscribe.");
    return;
  }

  activeCallSid = callSid;
  elements.activeCallBadge.textContent = callSid;
  loadConversationHistory(callSid);
  setConversationBanner("loading", `Subscribing to ${callSid} for live updates...`);
  if (!realtimeSocket || realtimeSocket.readyState !== WebSocket.OPEN) {
    pendingSubscriptionCallSid = callSid;
    connectRealtime();
    appendLog(`Connecting dashboard and preparing subscription for ${callSid}.`);
    return;
  }

  subscribeToRealtimeCall(callSid);
}

async function loadRecentCalls() {
  const response = await fetch(`${baseUrl}/api/webrtc/calls/recent`);
  const calls = await response.json();

  if (!calls.length) {
    elements.recentCalls.className = "call-list empty";
    elements.recentCalls.textContent = "No recent calls found.";
    return;
  }

  elements.recentCalls.className = "call-list";
  elements.recentCalls.innerHTML = "";
  for (const call of calls) {
    const button = document.createElement("button");
    button.className = "call-item";
    button.innerHTML = `
      <strong>${call.call_sid}</strong>
      <span>${call.status}</span>
      <small>${call.from_number || "Unknown caller"} · ${call.language || "-"}</small>
    `;
    button.addEventListener("click", () => {
      if (elements.callSidInput) {
        elements.callSidInput.value = call.call_sid;
      }
      setState({
        callState: call.status,
        languageMetric: call.language || "-",
        outcomeMetric: call.final_outcome || "-",
      });
      activeCallSid = call.call_sid;
      elements.activeCallBadge.textContent = call.call_sid;
      setConversationBanner(
        call.status === "completed" ? "ended" : "active",
        call.status === "completed" ? "This historical call has already ended." : `Viewing live updates for ${call.call_sid}.`,
      );
      appendLog(`Selected ${call.call_sid}.`);
      loadConversationHistory(call.call_sid);
      if (realtimeSocket && realtimeSocket.readyState === WebSocket.OPEN) {
        subscribeToRealtimeCall(call.call_sid);
      }
    });
    elements.recentCalls.appendChild(button);
  }
}

const webrtcManager = new WebRTCClientManager({
  baseUrl,
  onStateChange: setState,
  onLog: appendLog,
});

initializeDemoApplicants();
setupTranscriptAutoScrollTracking();
resetLatencyDashboard();
connectRealtime();
loadRecentCalls();
if (elements.connectWsButton) {
  elements.connectWsButton.addEventListener("click", connectRealtime);
}
if (elements.disconnectWsButton) {
  elements.disconnectWsButton.addEventListener("click", disconnectRealtime);
}
if (elements.placeCallButton) {
  elements.placeCallButton.addEventListener("click", placeCustomerCall);
}
if (elements.subscribeButton) {
  elements.subscribeButton.addEventListener("click", subscribeToCall);
}
if (elements.loadCallsButton) {
  elements.loadCallsButton.addEventListener("click", loadRecentCalls);
}

if (elements.enableMicButton) {
  elements.enableMicButton.addEventListener("click", async () => {
    try {
      await webrtcManager.enableMicrophone(elements.localAudio);
    } catch (error) {
      appendLog(`Microphone error: ${error.message}`);
    }
  });
}

if (elements.disableMicButton) {
  elements.disableMicButton.addEventListener("click", () => {
    webrtcManager.disableMicrophone(elements.localAudio);
  });
}

if (elements.startSessionButton) {
  elements.startSessionButton.addEventListener("click", async () => {
    try {
      const session = await webrtcManager.startSession({
        callSid: (elements.callSidInput ? elements.callSidInput.value.trim() : "") || activeCallSid || null,
        clientId: elements.clientIdInput ? elements.clientIdInput.value.trim() || null : null,
        audioElement: elements.localAudio,
      });
      if (elements.sessionBadge) {
        elements.sessionBadge.textContent = session.session_id;
      }
    } catch (error) {
      appendLog(`WebRTC session error: ${error.message}`);
    }
  });
}

if (elements.closeSessionButton) {
  elements.closeSessionButton.addEventListener("click", async () => {
    await webrtcManager.closeSession();
    if (elements.sessionBadge) {
      elements.sessionBadge.textContent = "No session";
    }
  });
}
