export class WebRTCClientManager {
  constructor({ baseUrl, onStateChange, onLog }) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.onStateChange = onStateChange;
    this.onLog = onLog;
    this.peerConnection = null;
    this.localStream = null;
    this.session = null;
    this.clientId = null;
    this.callSid = null;
  }

  async enableMicrophone(audioElement) {
    if (this.localStream) {
      return this.localStream;
    }
    const audioConstraints = {
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
    };
    this.localStream = await navigator.mediaDevices.getUserMedia({
      audio: audioConstraints,
      video: false,
    });
    if (audioElement) {
      audioElement.srcObject = this.localStream;
    }
    this.onStateChange({
      micState: "enabled",
      micProfile: "Echo cancellation, noise suppression, and AGC enabled when supported",
    });
    this.onLog("Microphone access granted.");
    this.onLog("Requested browser mic constraints: echoCancellation, noiseSuppression, autoGainControl.");
    return this.localStream;
  }

  disableMicrophone(audioElement) {
    if (!this.localStream) {
      return;
    }
    for (const track of this.localStream.getTracks()) {
      track.stop();
    }
    if (audioElement) {
      audioElement.srcObject = null;
    }
    this.localStream = null;
    this.onStateChange({
      micState: "off",
      micProfile: "Echo cancellation, noise suppression, and AGC requested",
    });
    this.onLog("Microphone disabled.");
  }

  async startSession({ callSid, clientId, audioElement }) {
    this.callSid = callSid || null;
    this.clientId = clientId || `dashboard-${Date.now()}`;

    const createResponse = await fetch(`${this.baseUrl}/api/webrtc/sessions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        call_sid: this.callSid,
        client_id: this.clientId,
        metadata: {
          source: "dashboard",
          note: "Browser-side WebRTC scaffold awaiting media bridge integration.",
        },
      }),
    });
    this.session = await createResponse.json();
    this.onStateChange({ rtcState: this.session.status, session: this.session });
    this.onLog(`Created WebRTC session ${this.session.session_id}.`);

    await this.ensurePeerConnection(audioElement);
    await this.createAndSendOffer();
    return this.session;
  }

  async ensurePeerConnection(audioElement) {
    if (this.peerConnection) {
      return this.peerConnection;
    }

    const iceServers = (this.session?.ice_servers || []).map((url) => ({ urls: url }));
    this.peerConnection = new RTCPeerConnection({ iceServers });

    this.peerConnection.onconnectionstatechange = () => {
      this.onStateChange({ rtcState: this.peerConnection.connectionState });
      this.onLog(`Peer connection state: ${this.peerConnection.connectionState}`);
    };

    this.peerConnection.oniceconnectionstatechange = () => {
      this.onLog(`ICE connection state: ${this.peerConnection.iceConnectionState}`);
    };

    this.peerConnection.onsignalingstatechange = () => {
      this.onLog(`Signaling state: ${this.peerConnection.signalingState}`);
    };

    this.peerConnection.onicecandidate = async (event) => {
      if (!event.candidate || !this.session) {
        return;
      }
      await fetch(`${this.baseUrl}/api/webrtc/sessions/${this.session.session_id}/ice`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          candidate: event.candidate.candidate,
          sdpMid: event.candidate.sdpMid,
          sdpMLineIndex: event.candidate.sdpMLineIndex,
          usernameFragment: event.candidate.usernameFragment,
          source: "client",
        }),
      });
      this.onLog("Submitted ICE candidate to backend.");
    };

    const stream = await this.enableMicrophone(audioElement);
    for (const track of stream.getAudioTracks()) {
      this.peerConnection.addTrack(track, stream);
    }

    this.peerConnection.addTransceiver("audio", { direction: "recvonly" });
    return this.peerConnection;
  }

  async createAndSendOffer() {
    if (!this.peerConnection || !this.session) {
      throw new Error("Peer connection or WebRTC session is not ready.");
    }

    const offer = await this.peerConnection.createOffer({
      offerToReceiveAudio: true,
    });
    await this.peerConnection.setLocalDescription(offer);

    const offerResponse = await fetch(`${this.baseUrl}/api/webrtc/sessions/${this.session.session_id}/offer`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        type: offer.type,
        sdp: offer.sdp,
      }),
    });
    this.session = await offerResponse.json();
    this.onStateChange({
      rtcState: "offer-sent",
      session: this.session,
    });
    this.onLog("Local offer created and stored on backend.");
    this.onLog("TODO: attach a backend media bridge and return a real answer to complete audio streaming.");
  }

  async refreshSession() {
    if (!this.session) {
      return null;
    }
    const response = await fetch(`${this.baseUrl}/api/webrtc/sessions/${this.session.session_id}`);
    this.session = await response.json();
    this.onStateChange({ rtcState: this.session.status, session: this.session });
    return this.session;
  }

  async closeSession() {
    if (this.session) {
      await fetch(`${this.baseUrl}/api/webrtc/sessions/${this.session.session_id}/close`, {
        method: "POST",
      });
    }

    if (this.peerConnection) {
      this.peerConnection.close();
      this.peerConnection = null;
    }

    this.session = null;
    this.onStateChange({ rtcState: "closed", session: null });
    this.onLog("WebRTC session closed.");
  }
}
