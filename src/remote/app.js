/* Murmur AI phone companion — local WebSocket UI.
   No analytics, no external scripts, no storage of the PIN or token. */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const statusEl = $("status");
  const pairSection = $("pair-section");
  const controls = $("controls");
  const transcript = $("transcript");
  const approvalSection = $("approval-section");

  const scheme = location.protocol === "https:" ? "wss:" : "ws:";
  let socket = null;
  let token = null;
  let currentApproval = null;

  function setStatus(text) {
    statusEl.textContent = text;
  }

  function addLine(role, text) {
    const p = document.createElement("p");
    p.dataset.role = role;
    const label = document.createElement("strong");
    label.textContent = role === "user" ? "You" : "Murmur";
    p.appendChild(label);
    p.appendChild(document.createTextNode(text || ""));
    transcript.appendChild(p);
    transcript.scrollTop = transcript.scrollHeight;
  }

  function send(payload) {
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      setStatus("Not connected. Reload the page and pair again.");
      return false;
    }
    socket.send(JSON.stringify(payload));
    return true;
  }

  function command(type, extra) {
    if (!token) {
      setStatus("Pair this phone first.");
      return;
    }
    send(Object.assign({ type: type, token: token }, extra || {}));
  }

  function connect() {
    socket = new WebSocket(scheme + "//" + location.host + "/remote/ws");
    socket.addEventListener("open", () => setStatus("Connected to Murmur AI on this network."));
    socket.addEventListener("close", () => {
      token = null;
      pairSection.hidden = false;
      controls.hidden = true;
      setStatus("Disconnected. Reload the page to reconnect.");
    });
    socket.addEventListener("message", (event) => {
      let msg;
      try { msg = JSON.parse(event.data); } catch (_) { return; }
      switch (msg.type) {
        case "pairing_required":
          pairSection.hidden = false;
          controls.hidden = true;
          setStatus("Enter the six-digit code Murmur spoke aloud.");
          break;
        case "paired":
          token = msg.token;
          pairSection.hidden = true;
          controls.hidden = false;
          setStatus("Paired. Say what you would like Murmur to do.");
          break;
        case "transcript":
          addLine(msg.role || "assistant", msg.text || "");
          break;
        case "confirmation_required":
          currentApproval = msg.request_id;
          $("approval-description").textContent = msg.description || "";
          $("approval-command").textContent = msg.command || "";
          approvalSection.hidden = false;
          $("approve").disabled = false;
          $("cancel").disabled = false;
          setStatus("Approval needed. Review the action before choosing.");
          break;
        case "state":
          setStatus(msg.text || msg.status || "Ready.");
          break;
        case "status":
          setStatus(msg.text || "Ready.");
          break;
        case "error":
          setStatus(msg.detail || "Something went wrong.");
          break;
        default:
          break;
      }
    });
    socket.addEventListener("error", () => setStatus("Connection error. Is phone remote still on?"));
  }

  $("pair-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const pin = $("pin").value.replace(/\D/g, "");
    if (pin.length !== 6) {
      setStatus("Enter all six digits.");
      return;
    }
    send({ type: "pair", pin: pin });
  });

  $("command-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const input = $("command");
    const text = input.value.trim();
    if (!text) return;
    addLine("user", text);
    command("command", { text: text });
    input.value = "";
  });

  $("describe").addEventListener("click", () => command("describe"));
  $("stop").addEventListener("click", () => {
    command("stop");
    setStatus("Stopping.");
  });

  function resolveApproval(approved) {
    if (!currentApproval) return;
    $("approve").disabled = true;
    $("cancel").disabled = true;
    command("approve", { request_id: currentApproval, approved: approved });
    currentApproval = null;
    approvalSection.hidden = true;
  }
  $("approve").addEventListener("click", () => resolveApproval(true));
  $("cancel").addEventListener("click", () => resolveApproval(false));

  // ---- Hold-to-talk: capture 16 kHz int16 PCM locally, never upload audio ----
  let mediaStream = null;
  let audioContext = null;
  let processor = null;
  let samples = [];
  let sourceRate = 16000;

  function toBase64(bytes) {
    let binary = "";
    const chunk = 0x8000;
    for (let i = 0; i < bytes.length; i += chunk) {
      binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
    }
    return btoa(binary);
  }

  function resample(input, sourceRate, targetRate) {
    if (sourceRate === targetRate) return input;
    const ratio = sourceRate / targetRate;
    const outLength = Math.floor(input.length / ratio);
    const out = new Float32Array(outLength);
    for (let i = 0; i < outLength; i++) {
      const pos = i * ratio;
      const index = Math.floor(pos);
      const frac = pos - index;
      const a = input[index] || 0;
      const b = input[index + 1] || a;
      out[i] = a + (b - a) * frac;
    }
    return out;
  }

  async function startRecording() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setStatus("Microphone capture is unavailable here. Use the command box.");
      return;
    }
    if (processor) return;
    try {
      mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      audioContext = new (window.AudioContext || window.webkitAudioContext)();
      sourceRate = audioContext.sampleRate || 16000;
      const source = audioContext.createMediaStreamSource(mediaStream);
      samples = [];
      processor = audioContext.createScriptProcessor(4096, 1, 1);
      processor.onaudioprocess = (event) => {
        const channel = event.inputBuffer.getChannelData(0);
        for (let i = 0; i < channel.length; i++) samples.push(channel[i]);
      };
      source.connect(processor);
      processor.connect(audioContext.destination);
      setStatus("Listening… release to send.");
    } catch (_) {
      setStatus("Microphone access was denied. Use the command box.");
    }
  }

  function stopRecording() {
    if (!processor) return;
    try { processor.disconnect(); } catch (_) {}
    try { processor.onaudioprocess = null; } catch (_) {}
    if (mediaStream) mediaStream.getTracks().forEach((track) => track.stop());
    if (audioContext) audioContext.close();
    processor = null;
    mediaStream = null;
    audioContext = null;

    const resampled = resample(new Float32Array(samples), sourceRate, 16000);
    samples = [];
    if (!resampled.length) {
      setStatus("No speech captured. Try again or use the command box.");
      return;
    }
    const pcm = new Int16Array(resampled.length);
    for (let i = 0; i < resampled.length; i++) {
      const value = Math.max(-1, Math.min(1, resampled[i]));
      pcm[i] = value < 0 ? value * 0x8000 : value * 0x7fff;
    }
    addLine("user", "Speaking…");
    command("audio", { data: toBase64(new Uint8Array(pcm.buffer)) });
    setStatus("Sent to Murmur.");
  }

  const talkButton = $("talk");
  talkButton.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    startRecording();
  });
  talkButton.addEventListener("pointerup", (event) => {
    event.preventDefault();
    stopRecording();
  });
  talkButton.addEventListener("pointercancel", stopRecording);
  talkButton.addEventListener("pointerleave", () => { if (processor) stopRecording(); });

  connect();
})();
