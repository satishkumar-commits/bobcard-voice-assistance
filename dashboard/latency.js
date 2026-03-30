const elements = {
  wsState: document.getElementById("wsState"),
  callSidInput: document.getElementById("callSidInput"),
  watchButton: document.getElementById("watchButton"),
  allCallsButton: document.getElementById("allCallsButton"),
  refreshCallsButton: document.getElementById("refreshCallsButton"),
  recentCallsSelect: document.getElementById("recentCallsSelect"),
  backendConversation: document.getElementById("backendConversation"),
  frontendConversation: document.getElementById("frontendConversation"),
  backendLogs: document.getElementById("backendLogs"),
  frontendLogs: document.getElementById("frontendLogs"),
  backendAnalyticsSummary: document.getElementById("backendAnalyticsSummary"),
  frontendAnalyticsSummary: document.getElementById("frontendAnalyticsSummary"),
  backendAnalyticsTable: document.getElementById("backendAnalyticsTable"),
  frontendAnalyticsTable: document.getElementById("frontendAnalyticsTable"),
};

const tabs = Array.from(document.querySelectorAll(".tab"));
const websocketUrl = `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/api/ws/realtime`;
const baseUrl = window.location.origin;

let socket = null;
let activeCallSid = "";
let eventSeen = new Set();
let backendTimeline = [];
let frontendTimeline = [];
let backendLogs = [];
let frontendLogs = [];
let persistedRequestToken = 0;

const MAX_TIMELINE_ITEMS = 260;
const MAX_LOG_ITEMS = 220;

const stepLabelMap = {
  outbound_call_requested: "system.api.request: Received call initiation request",
  twilio_voice_webhook_received: "system.external.twilio.webhook: Status update received",
  twilio_media_stream_start: "system.audio.stream: Customer audio stream started",
  stream_utterance_finalized: "system.audio.stream: Customer utterance finalized",
  sarvam_stt: "system.external.stt.request: Audio sent to STT",
  stt_transcript_ready: "system.external.stt.response: STT transcript ready",
  customer_transcript_received: "system.pipeline.input: Transcript routed to dialog manager",
  assistant_text_ready: "system.external.llm.response: Assistant text prepared",
  sarvam_tts_first_chunk: "system.external.tts.stream: First chunk received",
  sarvam_tts: "system.external.tts.response: Full audio generated",
  assistant_audio_ready: "system.audio.playback: Assistant audio queued",
  barge_in_confirmed: "system.audio.interruption: Barge-in confirmed",
  playback_interrupted: "system.audio.interruption: Playback interrupted",
};

const frontendStepMap = {
  outbound_call_requested: "frontend.ui.action: Call button clicked",
  twilio_media_stream_start: "frontend.audio.stream: Customer audio stream received by frontend",
  assistant_audio_ready: "frontend.audio.playback: System audio received by frontend",
  playback_interrupted: "frontend.audio.interrupt: Playback interrupted",
};

function setWsState(connected) {
  if (!elements.wsState) {
    return;
  }
  elements.wsState.textContent = connected ? "Connected" : "Disconnected";
  elements.wsState.className = `ws-state ${connected ? "connected" : "disconnected"}`;
}

function makeEventKey(event) {
  return [
    event.type || "",
    event.call_sid || "",
    event.step || "",
    event.timestamp || "",
    event.event_timestamp || "",
    event.request_sent_at || "",
    event.response_received_at || "",
    event.text || "",
    event.phase || "",
  ].join("|");
}

function shouldDisplayEvent(event) {
  if (!activeCallSid) {
    return true;
  }
  return event.call_sid === activeCallSid;
}

function resolveEventTime(event) {
  return event.response_received_at || event.event_timestamp || event.timestamp || event.request_sent_at || "";
}

function formatTime(iso) {
  if (!iso) {
    return "-";
  }
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return iso;
  }
  return `${date.toLocaleTimeString()}.${String(date.getMilliseconds()).padStart(3, "0")}`;
}

function formatLatency(ms) {
  if (typeof ms !== "number") {
    return "";
  }
  return `+ ${Math.round(ms)}ms`;
}

function pushLimited(array, item, limit) {
  array.unshift(item);
  if (array.length > limit) {
    array.length = limit;
  }
}

function addBackendCard(text, event, center = true) {
  pushLimited(
    backendTimeline,
    {
      kind: "event",
      text,
      time: resolveEventTime(event),
      latency: formatLatency(event.latency_ms),
      align: center ? "center" : "left",
    },
    MAX_TIMELINE_ITEMS,
  );
}

function addFrontendMessage(text, role, event) {
  pushLimited(
    frontendTimeline,
    {
      kind: "message",
      text,
      role,
      time: resolveEventTime(event),
      latency: formatLatency(event.latency_ms),
    },
    MAX_TIMELINE_ITEMS,
  );
}

function addFrontendEvent(text, event) {
  pushLimited(
    frontendTimeline,
    {
      kind: "event",
      text,
      time: resolveEventTime(event),
      latency: formatLatency(event.latency_ms),
      align: "center",
    },
    MAX_TIMELINE_ITEMS,
  );
}

function appendLog(target, event) {
  pushLimited(target, JSON.stringify(event), MAX_LOG_ITEMS);
}

function ingestEvent(event, skipRender = false) {
  if (!event || typeof event !== "object") {
    return;
  }
  if (!shouldDisplayEvent(event)) {
    return;
  }

  const key = makeEventKey(event);
  if (eventSeen.has(key)) {
    return;
  }
  eventSeen.add(key);

  if (event.type === "latency") {
    const label = stepLabelMap[event.step] || `system.${String(event.step || "unknown")}`;
    addBackendCard(label, event, true);
    if (frontendStepMap[event.step]) {
      addFrontendEvent(frontendStepMap[event.step], event);
    }
    appendLog(backendLogs, event);
  } else if (event.type === "transcript") {
    const speaker = String(event.speaker || "assistant").toLowerCase();
    if (speaker === "customer") {
      addFrontendMessage(event.text || "", "user", event);
    } else {
      addFrontendMessage(event.text || "", "assistant", event);
    }
    appendLog(frontendLogs, event);
  } else if (event.type === "user_speaking") {
    addFrontendEvent("frontend.audio.stream: Customer audio stream received by frontend", event);
    appendLog(frontendLogs, event);
  } else if (event.type === "ai_speaking") {
    addFrontendEvent("frontend.audio.playback: System audio received by frontend", event);
    appendLog(frontendLogs, event);
  } else if (event.type === "call_phase") {
    addBackendCard(`system.pipeline.phase: ${event.phase || "unknown"}`, event, true);
    appendLog(backendLogs, event);
  } else if (event.type === "call_status") {
    addBackendCard(`system.external.twilio.webhook: Status ${event.status || "unknown"}`, event, true);
    appendLog(backendLogs, event);
  } else if (event.type === "response_plan") {
    addBackendCard(`system.dialog.plan: route ${event.response_plan?.route || "unknown"}`, event, true);
    appendLog(backendLogs, event);
  } else if (event.type === "main_points") {
    addBackendCard(`system.dialog.intent: ${event.main_points?.primary_intent || "unknown"}`, event, true);
    appendLog(backendLogs, event);
  } else if (event.type === "barge_in_detected") {
    addFrontendEvent("frontend.audio.interrupt: Barge-in detected", event);
    appendLog(frontendLogs, event);
  } else {
    appendLog(backendLogs, event);
    appendLog(frontendLogs, event);
  }

  if (!skipRender) {
    renderAll();
  }
}

function renderTimeline(container, items) {
  if (!container) {
    return;
  }
  if (!items.length) {
    container.innerHTML = '<div class="timeline-empty">Waiting for live events...</div>';
    return;
  }

  const html = items
    .slice()
    .reverse()
    .map((item) => {
      if (item.kind === "message") {
        return `
          <div class="message-wrap">
            <div class="message-bubble ${item.role}">${escapeHtml(item.text)}</div>
            <div class="meta">${escapeHtml(formatTime(item.time))} ${escapeHtml(item.latency || "")}</div>
          </div>
        `;
      }
      const klass = item.align === "center" ? "event-card center" : "event-card";
      return `
        <div>
          <div class="${klass}">${escapeHtml(item.text)}</div>
          <div class="meta">${escapeHtml(formatTime(item.time))} ${escapeHtml(item.latency || "")}</div>
        </div>
      `;
    })
    .join("");

  container.innerHTML = html;
  container.scrollTop = container.scrollHeight;
}

function renderLogs(container, logs) {
  if (!container) {
    return;
  }
  if (!logs.length) {
    container.textContent = "Waiting for logs...";
    return;
  }
  container.textContent = logs.slice().reverse().join("\n");
}

function collectBackendAnalytics() {
  const stats = {};
  for (const entry of backendLogs) {
    try {
      const event = JSON.parse(entry);
      if (event.type !== "latency") {
        continue;
      }
      const step = String(event.step || "unknown");
      if (!stats[step]) {
        stats[step] = { count: 0, latest: null, total: 0 };
      }
      stats[step].count += 1;
      if (typeof event.latency_ms === "number") {
        stats[step].latest = Math.round(event.latency_ms);
        stats[step].total += Number(event.latency_ms);
      }
    } catch {
      // ignore malformed
    }
  }
  return stats;
}

function renderBackendAnalytics() {
  const stats = collectBackendAnalytics();
  const rows = Object.entries(stats).sort((a, b) => b[1].count - a[1].count);
  const totalEvents = rows.reduce((sum, [, v]) => sum + v.count, 0);
  const uniqueSteps = rows.length;
  const avgLatency = Math.round(
    rows.reduce((sum, [, v]) => sum + v.total, 0) /
      Math.max(
        1,
        rows.reduce((sum, [, v]) => sum + (v.latest == null ? 0 : v.count), 0),
      ),
  );

  elements.backendAnalyticsSummary.innerHTML = [
    metricCard("Call", activeCallSid || "All"),
    metricCard("Events", String(totalEvents)),
    metricCard("Steps / Avg", `${uniqueSteps} / ${Number.isFinite(avgLatency) ? `${avgLatency} ms` : "-"}`),
  ].join("");

  if (!rows.length) {
    elements.backendAnalyticsTable.innerHTML = '<tr><td colspan="4">No latency events yet.</td></tr>';
    return;
  }

  elements.backendAnalyticsTable.innerHTML = rows
    .map(([step, value]) => {
      const avg = value.count > 0 ? Math.round(value.total / value.count) : 0;
      return `<tr>
        <td>${escapeHtml(step)}</td>
        <td>${value.count}</td>
        <td>${value.latest == null ? "-" : `${value.latest} ms`}</td>
        <td>${value.latest == null ? "-" : `${avg} ms`}</td>
      </tr>`;
    })
    .join("");
}

function collectFrontendAnalytics() {
  const counters = {
    customer_messages: 0,
    assistant_messages: 0,
    frontend_events: 0,
    latest: "-",
  };

  for (const item of frontendTimeline) {
    if (item.kind === "message") {
      if (item.role === "user") {
        counters.customer_messages += 1;
      } else {
        counters.assistant_messages += 1;
      }
    } else {
      counters.frontend_events += 1;
    }
    if (item.time && counters.latest === "-") {
      counters.latest = formatTime(item.time);
    }
  }
  return counters;
}

function renderFrontendAnalytics() {
  const stats = collectFrontendAnalytics();
  elements.frontendAnalyticsSummary.innerHTML = [
    metricCard("Call", activeCallSid || "All"),
    metricCard("Customer / Assistant", `${stats.customer_messages} / ${stats.assistant_messages}`),
    metricCard("UI Events", String(stats.frontend_events)),
  ].join("");

  const rows = [
    ["customer_message", stats.customer_messages],
    ["assistant_message", stats.assistant_messages],
    ["frontend_event", stats.frontend_events],
  ];

  elements.frontendAnalyticsTable.innerHTML = rows
    .map(
      ([name, count]) => `<tr>
        <td>${escapeHtml(name)}</td>
        <td>${count}</td>
        <td>${stats.latest}</td>
        <td>${stats.latest}</td>
      </tr>`,
    )
    .join("");
}

function metricCard(label, value) {
  return `<div class="metric-card"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`;
}

function renderAll() {
  renderTimeline(elements.backendConversation, backendTimeline);
  renderTimeline(elements.frontendConversation, frontendTimeline);
  renderLogs(elements.backendLogs, backendLogs);
  renderLogs(elements.frontendLogs, frontendLogs);
  renderBackendAnalytics();
  renderFrontendAnalytics();
}

function resetViewState() {
  eventSeen = new Set();
  backendTimeline = [];
  frontendTimeline = [];
  backendLogs = [];
  frontendLogs = [];
  renderAll();
}

function subscribe(callSid) {
  const normalized = String(callSid || "").trim();
  if (socket && socket.readyState === WebSocket.OPEN) {
    if (activeCallSid) {
      socket.send(JSON.stringify({ action: "unsubscribe", call_sid: activeCallSid }));
    }
    if (normalized) {
      socket.send(JSON.stringify({ action: "subscribe", call_sid: normalized }));
    }
  }

  activeCallSid = normalized;
  elements.callSidInput.value = normalized;
  resetViewState();
  void loadPersistedLatencyLogs(normalized);
}

function connect() {
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
    return;
  }

  socket = new WebSocket(websocketUrl);
  setWsState(false);

  socket.onopen = () => {
    setWsState(true);
    if (activeCallSid) {
      socket.send(JSON.stringify({ action: "subscribe", call_sid: activeCallSid }));
    }
  };

  socket.onclose = () => {
    setWsState(false);
    window.setTimeout(connect, 1500);
  };

  socket.onerror = () => {
    setWsState(false);
  };

  socket.onmessage = (msg) => {
    let event;
    try {
      event = JSON.parse(msg.data);
    } catch {
      return;
    }

    if (event.type === "snapshot") {
      const latencyEvents = Array.isArray(event.latency_events) ? event.latency_events : [];
      const transcripts = Array.isArray(event.transcripts) ? event.transcripts : [];
      for (const item of latencyEvents) {
        ingestEvent(item, true);
      }
      for (const item of transcripts) {
        ingestEvent(item, true);
      }
      renderAll();
      return;
    }

    ingestEvent(event);
  };
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

async function loadPersistedLatencyLogs(callSid) {
  const normalized = String(callSid || "").trim();
  const token = ++persistedRequestToken;
  if (!normalized) {
    return;
  }

  try {
    const response = await fetch(`${baseUrl}/api/webrtc/calls/${encodeURIComponent(normalized)}/latency-logs?limit=500`);
    if (token !== persistedRequestToken) {
      return;
    }
    if (!response.ok) {
      return;
    }
    const events = await response.json();
    if (!Array.isArray(events)) {
      return;
    }
    for (const event of events) {
      ingestEvent(event, true);
    }
    renderAll();
  } catch {
    // ignore network errors
  }
}

async function loadRecentCalls() {
  try {
    const response = await fetch(`${baseUrl}/api/webrtc/calls/recent`);
    if (!response.ok) {
      return;
    }
    const calls = await response.json();
    if (!Array.isArray(calls)) {
      return;
    }

    elements.recentCallsSelect.innerHTML = '<option value="">Recent Calls</option>';
    for (const call of calls) {
      const option = document.createElement("option");
      option.value = call.call_sid || "";
      option.textContent = `${call.call_sid || "-"} (${call.status || "-"})`;
      elements.recentCallsSelect.appendChild(option);
    }
  } catch {
    // ignore
  }
}

function wireTabs() {
  for (const tab of tabs) {
    tab.addEventListener("click", () => {
      const pane = tab.dataset.pane;
      const targetTab = tab.dataset.tab;
      if (!pane || !targetTab) {
        return;
      }

      for (const candidate of tabs.filter((item) => item.dataset.pane === pane)) {
        candidate.classList.toggle("active", candidate === tab);
      }

      const paneContents = Array.from(document.querySelectorAll(`[data-pane-content="${pane}"]`));
      for (const content of paneContents) {
        const isActive = content.dataset.tabContent === targetTab;
        content.classList.toggle("hidden", !isActive);
      }
    });
  }
}

elements.watchButton?.addEventListener("click", () => {
  subscribe(elements.callSidInput.value);
});

elements.allCallsButton?.addEventListener("click", () => {
  subscribe("");
});

elements.refreshCallsButton?.addEventListener("click", () => {
  void loadRecentCalls();
});

elements.recentCallsSelect?.addEventListener("change", () => {
  subscribe(elements.recentCallsSelect.value);
});

wireTabs();
connect();
loadRecentCalls();
renderAll();
