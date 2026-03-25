const elements = {
  wsState: document.getElementById("wsState"),
  callSidFilter: document.getElementById("callSidFilter"),
  watchCallButton: document.getElementById("watchCallButton"),
  clearFilterButton: document.getElementById("clearFilterButton"),
  refreshCallsButton: document.getElementById("refreshCallsButton"),
  recentCalls: document.getElementById("recentCalls"),
  latencyTableBody: document.getElementById("latencyTableBody"),
  feedSubtitle: document.getElementById("feedSubtitle"),
  activeCallValue: document.getElementById("activeCallValue"),
  sttMetric: document.getElementById("sttMetric"),
  geminiMetric: document.getElementById("geminiMetric"),
  ttsMetric: document.getElementById("ttsMetric"),
  callDurationMetric: document.getElementById("callDurationMetric"),
  geminiOutputMetric: document.getElementById("geminiOutputMetric"),
  savedLogMetric: document.getElementById("savedLogMetric"),
  bargeInMetric: document.getElementById("bargeInMetric"),
  bargeInBlockMetric: document.getElementById("bargeInBlockMetric"),
  sloAlertMetric: document.getElementById("sloAlertMetric"),
  lastSloAlertMetric: document.getElementById("lastSloAlertMetric"),
  rolloutRollbackMetric: document.getElementById("rolloutRollbackMetric"),
  autoScrollToggle: document.getElementById("autoScrollToggle"),
};

const websocketUrl = `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/api/ws/realtime`;
const baseUrl = window.location.origin;

let realtimeSocket = null;
let activeCallSid = "";
let latencyRows = [];
let activeCallStartedAt = "";
let activeCallEndedAt = "";
let latestTimerSeconds = null;
let persistedLogRequestToken = 0;
let bargeInStats = createBargeInStats();
let sloStats = createSloStats();

function createBargeInStats() {
  return {
    confirmed: 0,
    early: 0,
    veryEarly: 0,
    lowSpeech: 0,
    blocked: 0,
    blockedReasons: {},
  };
}

function createSloStats() {
  return {
    total: 0,
    warning: 0,
    critical: 0,
    last: "",
  };
}

function setWsState(state) {
  if (!elements.wsState) {
    return;
  }
  elements.wsState.textContent = state;
  elements.wsState.className = `status-chip ${state === "connected" ? "connected" : "disconnected"}`;
}

function setActiveCall(callSid) {
  activeCallSid = (callSid || "").trim();
  elements.activeCallValue.textContent = activeCallSid || "All calls";
  elements.feedSubtitle.textContent = activeCallSid
    ? `Showing live latency events for ${activeCallSid}.`
    : "Streaming all calls.";
  elements.callSidFilter.value = activeCallSid;
  highlightRecentCall();
  renderLatencyTable();
}

function highlightRecentCall() {
  const cards = elements.recentCalls.querySelectorAll(".recent-call");
  for (const card of cards) {
    card.classList.toggle("active", card.dataset.callSid === activeCallSid);
  }
}

function connectRealtime() {
  if (realtimeSocket && realtimeSocket.readyState === WebSocket.OPEN) {
    return;
  }

  realtimeSocket = new WebSocket(websocketUrl);
  setWsState("connecting");

  realtimeSocket.onopen = () => {
    setWsState("connected");
    if (activeCallSid) {
      realtimeSocket.send(JSON.stringify({ action: "subscribe", call_sid: activeCallSid }));
    }
  };

  realtimeSocket.onclose = () => {
    setWsState("disconnected");
    window.setTimeout(connectRealtime, 1500);
  };

  realtimeSocket.onerror = () => {
    setWsState("disconnected");
  };

  realtimeSocket.onmessage = (message) => {
    const event = JSON.parse(message.data);
    if (event.type === "snapshot") {
      if (event.call_sid === activeCallSid) {
        applyCallSnapshot(event.call_state);
        mergeLatencyEvents(event.latency_events || []);
      }
      return;
    }

    if (event.type === "timer") {
      handleTimerEvent(event);
      return;
    }

    if (event.type === "call_status") {
      handleCallStatusEvent(event);
      return;
    }

    if (event.type === "call_summary") {
      handleCallSummaryEvent(event);
      return;
    }

    if (event.type === "latency") {
      addLatencyEvent(event);
      return;
    }

    if (event.type === "slo_alert") {
      handleSloAlertEvent(event);
      return;
    }

    if (event.type === "rollout_rollback") {
      handleRolloutRollbackEvent(event);
      return;
    }
  };
}

function subscribeToCall(callSid) {
  const normalized = (callSid || "").trim();
  if (realtimeSocket && realtimeSocket.readyState === WebSocket.OPEN) {
    if (activeCallSid) {
      realtimeSocket.send(JSON.stringify({ action: "unsubscribe", call_sid: activeCallSid }));
    }
    if (normalized) {
      realtimeSocket.send(JSON.stringify({ action: "subscribe", call_sid: normalized }));
    }
  }
  latencyRows = [];
  activeCallStartedAt = "";
  activeCallEndedAt = "";
  latestTimerSeconds = null;
  setMetric(elements.sttMetric, "-");
  setMetric(elements.geminiMetric, "-");
  setMetric(elements.ttsMetric, "-");
  setMetric(elements.callDurationMetric, "-");
  setMetric(elements.geminiOutputMetric, "-");
  setMetric(elements.savedLogMetric, normalized ? "loading..." : "live only");
  bargeInStats = createBargeInStats();
  sloStats = createSloStats();
  setMetric(elements.bargeInMetric, "-");
  setMetric(elements.bargeInBlockMetric, "-");
  setMetric(elements.sloAlertMetric, "-");
  setMetric(elements.lastSloAlertMetric, "-");
  setMetric(elements.rolloutRollbackMetric, "-");
  setActiveCall(normalized);
  void loadPersistedLatencyLogs(normalized);
}

function mergeLatencyEvents(events) {
  for (const event of events) {
    addLatencyEvent(event, false);
  }
  renderLatencyTable();
}

function applyCallSnapshot(callState) {
  if (!activeCallSid) {
    return;
  }
  if (!callState || typeof callState !== "object") {
    return;
  }
  activeCallStartedAt = callState.started_at || "";
  activeCallEndedAt = callState.ended_at || "";
  const summaryDuration = callState.call_summary?.duration_seconds;
  if (typeof summaryDuration === "number") {
    latestTimerSeconds = summaryDuration;
  }
  updateDurationMetric();
}

function handleTimerEvent(event) {
  if (!activeCallSid || event.call_sid !== activeCallSid) {
    return;
  }
  if (typeof event.elapsed_seconds === "number") {
    latestTimerSeconds = event.elapsed_seconds;
    setMetric(elements.callDurationMetric, formatDuration(event.elapsed_seconds));
  }
}

function handleCallStatusEvent(event) {
  if (!activeCallSid || event.call_sid !== activeCallSid) {
    return;
  }
  activeCallStartedAt = event.started_at || activeCallStartedAt;
  activeCallEndedAt = event.ended_at || activeCallEndedAt;
  if (activeCallEndedAt) {
    latestTimerSeconds = null;
  }
  updateDurationMetric();
}

function handleCallSummaryEvent(event) {
  if (!activeCallSid || event.call_sid !== activeCallSid) {
    return;
  }
  const durationSeconds = event.call_summary?.duration_seconds;
  if (typeof durationSeconds === "number") {
    latestTimerSeconds = durationSeconds;
    setMetric(elements.callDurationMetric, formatDuration(durationSeconds));
    return;
  }
  updateDurationMetric();
}

function updateDurationMetric() {
  if (!activeCallSid) {
    setMetric(elements.callDurationMetric, "-");
    return;
  }
  if (typeof latestTimerSeconds === "number") {
    setMetric(elements.callDurationMetric, formatDuration(latestTimerSeconds));
    return;
  }

  const startedMs = parseIsoToMillis(activeCallStartedAt);
  if (startedMs == null) {
    setMetric(elements.callDurationMetric, "-");
    return;
  }
  const endedMs = parseIsoToMillis(activeCallEndedAt);
  const endMs = endedMs == null ? Date.now() : endedMs;
  const durationSeconds = Math.max(0, Math.floor((endMs - startedMs) / 1000));
  setMetric(elements.callDurationMetric, formatDuration(durationSeconds));
}

function addLatencyEvent(event, rerender = true) {
  const key = [
    event.call_sid || "",
    event.step || "",
    event.request_sent_at || "",
    event.response_received_at || "",
    event.event_timestamp || "",
    event.timestamp || "",
  ].join("|");

  if (latencyRows.some((item) => item.key === key)) {
    return;
  }

  latencyRows.unshift({ key, event });
  latencyRows = latencyRows.slice(0, 300);
  updateMetrics(event);
  if (rerender) {
    renderLatencyTable();
  }
}

function updateMetrics(event) {
  if (activeCallSid && event.call_sid && event.call_sid !== activeCallSid) {
    return;
  }
  if (event.step === "sarvam_stt" && event.latency_ms != null) {
    setMetric(elements.sttMetric, `${event.latency_ms} ms`);
  }
  if (event.step === "gemini" && event.latency_ms != null) {
    setMetric(elements.geminiMetric, `${event.latency_ms} ms`);
    const geminiOutputParts = [];
    if (event.output_tokens != null) {
      geminiOutputParts.push(`${event.output_tokens} tok`);
    }
    if (event.output_words != null) {
      geminiOutputParts.push(`${event.output_words} words`);
    }
    if (geminiOutputParts.length) {
      setMetric(elements.geminiOutputMetric, geminiOutputParts.join(" / "));
    }
  }
  if ((event.step === "sarvam_tts" || event.step === "sarvam_tts_cache") && event.latency_ms != null) {
    setMetric(elements.ttsMetric, `${event.latency_ms} ms`);
  }
  if (event.step === "sarvam_tts_cache") {
    setMetric(elements.ttsMetric, "cache hit");
  }
  updateBargeInTelemetry(event);
}

function setMetric(element, value) {
  if (element) {
    element.textContent = value;
  }
}

function updateBargeInTelemetry(event) {
  if (event.step === "barge_in_confirmed") {
    bargeInStats.confirmed += 1;
    const playbackMs = Number(event.playback_ms || 0);
    const speechMs = Number(event.speech_ms || 0);
    if (playbackMs > 0 && playbackMs < 1000) {
      bargeInStats.early += 1;
    }
    if (playbackMs > 0 && playbackMs < 500) {
      bargeInStats.veryEarly += 1;
    }
    if (speechMs > 0 && speechMs <= 260) {
      bargeInStats.lowSpeech += 1;
    }
    setMetric(
      elements.bargeInMetric,
      `${bargeInStats.confirmed} | <1s ${bargeInStats.early} | <500ms ${bargeInStats.veryEarly} | <=260ms ${bargeInStats.lowSpeech}`,
    );
    return;
  }

  if (event.step === "barge_in_gate_blocked") {
    bargeInStats.blocked += 1;
    const reason = String(event.reason || "unknown");
    bargeInStats.blockedReasons[reason] = (bargeInStats.blockedReasons[reason] || 0) + 1;
    const topReasons = Object.entries(bargeInStats.blockedReasons)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 2)
      .map(([key, count]) => `${key}:${count}`)
      .join(" | ");
    setMetric(elements.bargeInBlockMetric, `${bargeInStats.blocked}${topReasons ? ` | ${topReasons}` : ""}`);
  }
}

function handleSloAlertEvent(event) {
  if (activeCallSid && event.call_sid && event.call_sid !== activeCallSid) {
    return;
  }
  sloStats.total += 1;
  const severity = String(event.severity || "warning");
  if (severity === "critical") {
    sloStats.critical += 1;
  } else {
    sloStats.warning += 1;
  }
  const metric = String(event.metric || "unknown");
  const breachType = String(event.breach_type || "single");
  const observed = Number(event.observed_ms || 0);
  const threshold = Number(event.threshold_ms || 0);
  const sampleCount = Number(event.sample_count || 0);
  sloStats.last = `${metric} ${breachType} ${observed}ms>${threshold}ms n=${sampleCount}`;
  setMetric(elements.sloAlertMetric, `${sloStats.total} | warn ${sloStats.warning} | crit ${sloStats.critical}`);
  setMetric(elements.lastSloAlertMetric, sloStats.last);
}

function handleRolloutRollbackEvent(event) {
  if (activeCallSid && event.call_sid && event.call_sid !== activeCallSid) {
    return;
  }
  const until = event.rollback_until ? formatTime(event.rollback_until) : "-";
  setMetric(elements.rolloutRollbackMetric, `ACTIVE until ${until}`);
}

function renderLatencyTable() {
  const visibleRows = latencyRows.filter(({ event }) => {
    if (!activeCallSid) {
      return true;
    }
    return event.call_sid === activeCallSid;
  });

  if (!visibleRows.length) {
    elements.latencyTableBody.innerHTML = `
      <tr class="empty-row">
        <td colspan="5">No latency events available for the current filter.</td>
      </tr>
    `;
    return;
  }

  elements.latencyTableBody.innerHTML = visibleRows
    .map(({ event }) => {
      const timeValue = event.response_received_at || event.event_timestamp || event.timestamp || event.request_sent_at || "-";
      const latencyValue = event.latency_ms != null ? `${event.latency_ms} ms` : "-";
      return `
        <tr>
          <td class="mono">${formatTime(timeValue)}</td>
          <td><span class="step-badge">${escapeHtml(event.step || "-")}</span></td>
          <td class="mono">${escapeHtml(event.call_sid || "global")}</td>
          <td>${escapeHtml(latencyValue)}</td>
          <td class="mono">${escapeHtml(buildDetailText(event))}</td>
        </tr>
      `;
    })
    .join("");

  if (elements.autoScrollToggle.checked) {
    const wrap = elements.latencyTableBody.parentElement?.parentElement;
    if (wrap) {
      wrap.scrollTop = 0;
    }
  }
}

function buildDetailText(event) {
  const hiddenKeys = new Set([
    "type",
    "step",
    "call_sid",
    "timestamp",
    "event_timestamp",
    "request_sent_at",
    "response_received_at",
    "latency_ms",
  ]);
  return Object.entries(event)
    .filter(([key, value]) => !hiddenKeys.has(key) && value !== "" && value != null)
    .map(([key, value]) => `${key}=${value}`)
    .join(" | ");
}

function formatTime(value) {
  if (!value || value === "-") {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return `${date.toLocaleTimeString()}.${String(date.getMilliseconds()).padStart(3, "0")}`;
}

function parseIsoToMillis(value) {
  if (!value) {
    return null;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return null;
  }
  return date.getTime();
}

function formatDuration(totalSeconds) {
  const safeSeconds = Math.max(0, Math.floor(totalSeconds || 0));
  const hours = Math.floor(safeSeconds / 3600);
  const minutes = Math.floor((safeSeconds % 3600) / 60);
  const seconds = safeSeconds % 60;
  if (hours > 0) {
    return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  }
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

async function loadPersistedLatencyLogs(callSid) {
  const normalized = (callSid || "").trim();
  const requestToken = ++persistedLogRequestToken;

  if (!normalized) {
    setMetric(elements.savedLogMetric, "live only");
    return;
  }

  try {
    const response = await fetch(`${baseUrl}/api/webrtc/calls/${encodeURIComponent(normalized)}/latency-logs?limit=500`);
    if (requestToken !== persistedLogRequestToken) {
      return;
    }
    if (!response.ok) {
      setMetric(elements.savedLogMetric, "unavailable");
      return;
    }
    const events = await response.json();
    if (requestToken !== persistedLogRequestToken) {
      return;
    }
    mergeLatencyEvents(Array.isArray(events) ? events : []);
    setMetric(elements.savedLogMetric, `${Array.isArray(events) ? events.length : 0} loaded`);
  } catch {
    setMetric(elements.savedLogMetric, "unavailable");
  }
}

async function loadRecentCalls() {
  const response = await fetch(`${baseUrl}/api/webrtc/calls/recent`);
  if (!response.ok) {
    elements.recentCalls.textContent = "Could not load recent calls.";
    elements.recentCalls.classList.add("empty");
    return;
  }

  const calls = await response.json();
  if (!calls.length) {
    elements.recentCalls.textContent = "No recent calls found.";
    elements.recentCalls.classList.add("empty");
    return;
  }

  elements.recentCalls.classList.remove("empty");
  elements.recentCalls.innerHTML = calls
    .map(
      (call) => `
        <button class="recent-call" type="button" data-call-sid="${escapeHtml(call.call_sid)}">
          <strong>${escapeHtml(call.call_sid)}</strong>
          <span>Status: ${escapeHtml(call.status || "-")}</span>
          <span>Language: ${escapeHtml(call.language || "-")}</span>
          <span>Started: ${escapeHtml(formatTime(call.started_at || ""))}</span>
        </button>
      `,
    )
    .join("");

  for (const card of elements.recentCalls.querySelectorAll(".recent-call")) {
    card.addEventListener("click", () => {
      subscribeToCall(card.dataset.callSid || "");
    });
  }
  highlightRecentCall();
}

elements.watchCallButton?.addEventListener("click", () => {
  subscribeToCall(elements.callSidFilter.value);
});

elements.clearFilterButton?.addEventListener("click", () => {
  subscribeToCall("");
});

elements.refreshCallsButton?.addEventListener("click", () => {
  loadRecentCalls();
});

connectRealtime();
loadRecentCalls();
