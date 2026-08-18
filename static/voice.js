const VOICE_STORAGE_KEYS = {
  apiKey: "doubaochat_ark_api_key",
  model: "doubaochat_ark_model",
  voice: "doubaochat_tts_voice",
  autoSpeak: "doubaochat_auto_speak",
  accessToken: "doubaochat_access_token",
};

let activeRecorder = null;
let activeRecognition = null;
const recorderMap = new Map();
let globalLoadingCount = 0;
let micPermissionGranted = false;
let audioOutputUnlocked = false;
let audioUnlockListenerAttached = false;
let playbackAudioContext = null;
let activeTtsToken = 0;
let ttsAbortController = null;

const SILENT_WAV =
  "data:audio/wav;base64,UklGRigAAABXQVZFZm10IBIAAAABAAEARKwAAIhYAQACABAAAABkYXRhAgAAAAEA";

function setGlobalLoadingMessage(message) {
  const textEl = document.getElementById("globalLoadingText");
  if (textEl && message) {
    textEl.textContent = message;
  }
}

function setGlobalLoading(active, message = "请稍候…") {
  const overlay = document.getElementById("globalLoading");
  if (!overlay) return;
  if (message) setGlobalLoadingMessage(message);
  if (active) {
    globalLoadingCount += 1;
    overlay.classList.remove("is-hidden");
    return;
  }
  globalLoadingCount = Math.max(0, globalLoadingCount - 1);
  if (globalLoadingCount === 0) {
    overlay.classList.add("is-hidden");
  }
}

async function withGlobalLoading(message, fn) {
  setGlobalLoading(true, message);
  try {
    return await fn();
  } finally {
    setGlobalLoading(false);
  }
}

function isGlobalLoading() {
  return globalLoadingCount > 0;
}

function loadSettings() {
  return {
    apiKey: sessionStorage.getItem(VOICE_STORAGE_KEYS.apiKey) || "",
    model: sessionStorage.getItem(VOICE_STORAGE_KEYS.model) || "",
    voice: sessionStorage.getItem(VOICE_STORAGE_KEYS.voice) || "zh_female_cancan_mars_bigtts",
    autoSpeak: sessionStorage.getItem(VOICE_STORAGE_KEYS.autoSpeak) === "1",
    accessToken: sessionStorage.getItem(VOICE_STORAGE_KEYS.accessToken) || "",
  };
}

function saveSettings({ apiKey, model, voice, autoSpeak, accessToken }) {
  sessionStorage.setItem(VOICE_STORAGE_KEYS.apiKey, apiKey.trim());
  sessionStorage.setItem(VOICE_STORAGE_KEYS.model, model.trim());
  sessionStorage.setItem(VOICE_STORAGE_KEYS.voice, voice.trim() || "zh_female_cancan_mars_bigtts");
  sessionStorage.setItem(VOICE_STORAGE_KEYS.autoSpeak, autoSpeak ? "1" : "0");
  sessionStorage.setItem(VOICE_STORAGE_KEYS.accessToken, (accessToken || "").trim());
}

function getApiKey() {
  return loadSettings().apiKey;
}

function getModel() {
  return loadSettings().model;
}

function isClientConfigured() {
  const s = loadSettings();
  return Boolean(s.apiKey && s.model);
}

function canUseVoiceApi() {
  if (typeof window.isServerConfigured === "function" && window.isServerConfigured()) {
    return true;
  }
  return Boolean(getApiKey());
}

function authHeaders(extra = {}) {
  const s = loadSettings();
  const headers = { ...extra };
  if (s.apiKey) headers["X-Ark-Api-Key"] = s.apiKey;
  if (s.model) headers["X-Ark-Model"] = s.model;
  if (s.accessToken) headers["Authorization"] = `Bearer ${s.accessToken}`;
  return headers;
}

// 服务端开启访问口令且当前未填写时，统一提示并打开设置弹窗
function onApiUnauthorized() {
  if (typeof showBanner === "function") {
    showBanner("本服务已开启访问口令保护，请在「设置」中填写访问口令后重试", "error");
  }
  openSettingsModal();
  setTimeout(() => document.getElementById("settingsAccessToken")?.focus(), 50);
  throw new Error("需要访问口令，请在设置中填写后重试");
}

function openSettingsModal() {
  const modal = document.getElementById("settingsModal");
  const s = loadSettings();
  document.getElementById("settingsApiKey").value = s.apiKey;
  document.getElementById("settingsModel").value = s.model;
  document.getElementById("settingsVoice").value = s.voice;
  document.getElementById("settingsAutoSpeak").checked = s.autoSpeak;
  document.getElementById("settingsAccessToken").value = s.accessToken;
  modal.classList.remove("hidden");
}

function closeSettingsModal() {
  document.getElementById("settingsModal").classList.add("hidden");
}

function initSettingsUI() {
  document.getElementById("settingsBtn")?.addEventListener("click", openSettingsModal);
  document.getElementById("settingsClose")?.addEventListener("click", closeSettingsModal);
  document.getElementById("settingsModal")?.addEventListener("click", (e) => {
    if (e.target.id === "settingsModal") closeSettingsModal();
  });
  document.getElementById("settingsSave")?.addEventListener("click", () => {
    saveSettings({
      apiKey: document.getElementById("settingsApiKey").value,
      model: document.getElementById("settingsModel").value,
      voice: document.getElementById("settingsVoice").value,
      autoSpeak: document.getElementById("settingsAutoSpeak").checked,
      accessToken: document.getElementById("settingsAccessToken").value,
    });
    closeSettingsModal();
    if (typeof checkHealth === "function") checkHealth();
  });
}

function setVoiceStatus(text) {
  const el = document.getElementById("voiceStatus");
  if (el) {
    el.textContent = text || "";
    el.classList.toggle("hidden", !text);
  }
}

function updatePermissionStatusUI() {
  const parts = [];
  parts.push(micPermissionGranted ? "麦克风已授权" : "麦克风未授权");
  parts.push(audioOutputUnlocked ? "扬声器已就绪" : "扬声器待激活（点击页面）");
  setVoiceStatus(parts.join(" · "));
}

function attachAudioUnlockOnFirstGesture() {
  if (audioUnlockListenerAttached || audioOutputUnlocked) return;
  audioUnlockListenerAttached = true;
  const unlockOnce = async () => {
    document.removeEventListener("click", unlockOnce, true);
    document.removeEventListener("touchstart", unlockOnce, true);
    const ok = await unlockAudioOutput();
    if (ok) {
      updatePermissionStatusUI();
      setTimeout(() => {
        if (!isGlobalLoading()) setVoiceStatus("");
      }, 2500);
    }
  };
  document.addEventListener("click", unlockOnce, { capture: true });
  document.addEventListener("touchstart", unlockOnce, { capture: true });
}

function getAudioContextClass() {
  return window.AudioContext || window.webkitAudioContext || null;
}

function primeAudioOnUserGesture() {
  const AudioCtx = getAudioContextClass();
  if (AudioCtx) {
    if (!playbackAudioContext || playbackAudioContext.state === "closed") {
      playbackAudioContext = new AudioCtx();
    }
    if (playbackAudioContext.state === "suspended") {
      playbackAudioContext.resume().catch(() => {});
    }
    audioOutputUnlocked = true;
    return true;
  }
  try {
    const audio = new Audio(SILENT_WAV);
    audio.volume = 0.01;
    const pending = audio.play();
    if (pending) {
      pending
        .then(() => {
          audio.pause();
          audioOutputUnlocked = true;
        })
        .catch(() => {});
    }
    return true;
  } catch {
    return false;
  }
}

async function ensurePlaybackContext() {
  const AudioCtx = getAudioContextClass();
  if (!AudioCtx) return null;
  if (!playbackAudioContext || playbackAudioContext.state === "closed") {
    playbackAudioContext = new AudioCtx();
  }
  if (playbackAudioContext.state === "suspended") {
    await playbackAudioContext.resume();
  }
  audioOutputUnlocked = true;
  return playbackAudioContext;
}

async function unlockAudioOutput() {
  if (audioOutputUnlocked && playbackAudioContext?.state === "running") {
    return true;
  }
  primeAudioOnUserGesture();
  const ctx = await ensurePlaybackContext();
  if (ctx) {
    return true;
  }
  try {
    const audio = new Audio(SILENT_WAV);
    audio.volume = 0.01;
    await audio.play();
    audio.pause();
    audio.currentTime = 0;
    audioOutputUnlocked = true;
    return true;
  } catch {
    return false;
  }
}

async function requestMicrophonePermission() {
  if (!navigator.mediaDevices?.getUserMedia) {
    return false;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    stream.getTracks().forEach((track) => track.stop());
    micPermissionGranted = true;
    return true;
  } catch {
    micPermissionGranted = false;
    return false;
  }
}

function hidePermissionGate() {
  document.getElementById("permissionGate")?.classList.add("hidden");
}

function showPermissionGate() {
  document.getElementById("permissionGate")?.classList.remove("hidden");
}

async function syncPermissionStateFromBrowser() {
  try {
    if (navigator.permissions?.query) {
      const status = await navigator.permissions.query({ name: "microphone" });
      if (status.state === "granted") {
        micPermissionGranted = true;
      }
      status.onchange = () => {
        micPermissionGranted = status.state === "granted";
        updatePermissionStatusUI();
      };
    }
  } catch {
    /* permissions.query not supported */
  }
  if (micPermissionGranted) {
    hidePermissionGate();
  }
}

async function enableVoiceFeatures() {
  await withGlobalLoading("正在请求麦克风与语音播放权限…", async () => {
    const micOk = await requestMicrophonePermission();
    const audioOk = await unlockAudioOutput();

    if (!micOk) {
      showBanner?.(
        "麦克风未授权：请在浏览器地址栏左侧允许麦克风，或点击下方按钮重试。",
        "error"
      );
    }
    if (!audioOk) {
      attachAudioUnlockOnFirstGesture();
    }

    if (micOk || audioOk) {
      sessionStorage.setItem("doubaochat_voice_gate_done", "1");
      hidePermissionGate();
    }

    updatePermissionStatusUI();
    setTimeout(() => {
      if (!isGlobalLoading()) setVoiceStatus("");
    }, 2500);
  });
}

function initPermissionGate() {
  const enableBtn = document.getElementById("enableVoiceBtn");
  const skipBtn = document.getElementById("skipVoiceBtn");
  if (!enableBtn) return;

  const gateDone = sessionStorage.getItem("doubaochat_voice_gate_done") === "1";
  if (gateDone) {
    hidePermissionGate();
  } else {
    showPermissionGate();
  }

  enableBtn.addEventListener("click", () => {
    enableVoiceFeatures();
  });

  skipBtn?.addEventListener("click", () => {
    sessionStorage.setItem("doubaochat_voice_gate_done", "1");
    hidePermissionGate();
    attachAudioUnlockOnFirstGesture();
    setVoiceStatus("已跳过语音授权，需要时可刷新页面重新开启");
    setTimeout(() => setVoiceStatus(""), 3000);
  });
}

async function transcribeWithAsr(blob, filename) {
  const form = new FormData();
  form.append("audio", blob, filename);
  const res = await fetch("/api/asr", {
    method: "POST",
    headers: authHeaders(),
    body: form,
  });
  if (res.status === 401) onApiUnauthorized();
  const data = await res.json();
  if (!res.ok) {
    throw new Error(
      typeof data.detail === "string" ? data.detail : "语音识别失败"
    );
  }
  return data.text;
}

function transcribeWithWebSpeech() {
  return new Promise((resolve, reject) => {
    const SpeechRecognition =
      window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      reject(new Error("当前浏览器不支持 Web Speech，请使用 Chrome/Edge"));
      return;
    }
    const recognition = new SpeechRecognition();
    activeRecognition = recognition;
    recognition.lang = "zh-CN";
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;
    let settled = false;
    const cleanup = () => {
      if (activeRecognition === recognition) {
        activeRecognition = null;
      }
    };
    recognition.onresult = (e) => {
      settled = true;
      resolve(e.results[0][0].transcript);
    };
    recognition.onerror = (e) => {
      settled = true;
      reject(new Error(e.error || "语音识别失败"));
      cleanup();
    };
    recognition.onend = () => {
      cleanup();
      if (!settled) {
        reject(new Error("未识别到语音，请重试"));
      }
    };
    recognition.start();
  });
}

// ===== 互讲页显式录制按钮 =====
// 原先只有麦克风图标在「话筒/方块」间切换，用户不易看出当前是否在录。
// 这里用文字明确区分「开始录制 / 结束录制」，并给出状态提示。
function syncTeachRecordUi(recording) {
  const label = document.getElementById("teachRecordLabel");
  if (label) label.textContent = recording ? "结束录制" : "开始录制";
  const btn = document.getElementById("teachRecordBtn");
  if (btn) {
    btn.classList.toggle("btn-danger", recording);
    btn.classList.toggle("btn-secondary", !recording);
    btn.setAttribute("aria-pressed", recording ? "true" : "false");
  }
  const hint = document.getElementById("teachRecordHint");
  if (hint) {
    hint.textContent = recording
      ? "正在录音，讲完点「结束录制」"
      : "点击开始录制，讲完再点一次结束";
  }
  const status = document.getElementById("recordingStatus");
  if (status) status.textContent = recording ? "录制中" : "识别中…";
}

function setRecordingState(btn, recording) {
  // 互讲页的显式「开始/结束录制」按钮与状态文字
  syncTeachRecordUi(recording);
  if (!btn) return;
  btn.classList.toggle("recording", recording);
  btn.setAttribute("aria-label", recording ? "停止录音" : "开始语音输入");
  btn.title = recording ? "停止录音" : "语音输入";
  // 切换录音/停止图标
  const stopSvg = `<svg class="mic-icon" viewBox="0 0 24 24" width="20" height="20" fill="currentColor" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>`;
  const micSvg = `<svg class="mic-icon" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>`;
  // 仅对 teachMicBtn（SVG 按钮）做图标切换；其他按钮保留原 emoji 逻辑
  if (btn.id === "teachMicBtn") {
    btn.innerHTML = recording ? stopSvg : micSvg;
  } else {
    btn.textContent = recording ? "⏹" : "🎤";
  }
}

// ===== 录音波形可视化 + 计时器 =====
let waveformAnalyser = null;
let waveformStream = null;
let waveformRafId = null;
let recordingStartTime = 0;
let recordingTimerId = null;

function showRecordingPanel() {
  const panel = document.getElementById("recordingPanel");
  if (panel) panel.classList.remove("hidden");
}

function hideRecordingPanel() {
  const panel = document.getElementById("recordingPanel");
  if (panel) panel.classList.add("hidden");
}

function startRecordingTimer() {
  recordingStartTime = Date.now();
  const timerEl = document.getElementById("recordingTimer");
  recordingTimerId = setInterval(() => {
    if (!timerEl) return;
    const elapsed = Math.floor((Date.now() - recordingStartTime) / 1000);
    const mm = String(Math.floor(elapsed / 60)).padStart(2, "0");
    const ss = String(elapsed % 60).padStart(2, "0");
    timerEl.textContent = `${mm}:${ss}`;
  }, 500);
}

function stopRecordingTimer() {
  if (recordingTimerId) {
    clearInterval(recordingTimerId);
    recordingTimerId = null;
  }
  const timerEl = document.getElementById("recordingTimer");
  if (timerEl) timerEl.textContent = "00:00";
}

function startWaveform(stream) {
  const canvas = document.getElementById("waveformCanvas");
  if (!canvas) return;
  const AudioCtx = getAudioContextClass();
  if (!AudioCtx) return;
  try {
    const ctx = new AudioCtx();
    waveformStream = stream;
    const source = ctx.createMediaStreamSource(stream);
    waveformAnalyser = ctx.createAnalyser();
    waveformAnalyser.fftSize = 256;
    source.connect(waveformAnalyser);
    const bufferLength = waveformAnalyser.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);
    const canvasCtx = canvas.getContext("2d");
    const draw = () => {
      waveformRafId = requestAnimationFrame(draw);
      waveformAnalyser.getByteFrequencyData(dataArray);
      canvasCtx.clearRect(0, 0, canvas.width, canvas.height);
      const barCount = 32;
      const barWidth = canvas.width / barCount;
      const step = Math.floor(bufferLength / barCount);
      for (let i = 0; i < barCount; i++) {
        const value = dataArray[i * step] || 0;
        const barHeight = Math.max(2, (value / 255) * canvas.height);
        const x = i * barWidth;
        const y = (canvas.height - barHeight) / 2;
        const gradient = canvasCtx.createLinearGradient(0, y, 0, y + barHeight);
        gradient.addColorStop(0, "#60a5fa");
        gradient.addColorStop(1, "#3b82f6");
        canvasCtx.fillStyle = gradient;
        canvasCtx.fillRect(x + 1, y, barWidth - 2, barHeight);
      }
    };
    draw();
  } catch (err) {
    console.warn("波形可视化初始化失败：", err);
  }
}

function stopWaveform() {
  if (waveformRafId) {
    cancelAnimationFrame(waveformRafId);
    waveformRafId = null;
  }
  waveformAnalyser = null;
  const canvas = document.getElementById("waveformCanvas");
  if (canvas) {
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);
  }
}

async function startSpeechCapture(buttonId, inputId, autoSubmit = false) {
  const btn = document.getElementById(buttonId);
  const input = document.getElementById(inputId);
  if (!btn || !input) return;
  if (isGlobalLoading()) {
    showBanner?.("请等待当前操作完成", "error");
    return;
  }
  if (!canUseVoiceApi()) {
    openSettingsModal();
    showBanner?.("请先填写 API Key 与模型 ID，或在服务端配置 .env", "error");
    return;
  }
  if (!micPermissionGranted) {
    const ok = await requestMicrophonePermission();
    if (!ok) {
      showBanner?.("请先允许麦克风权限后再录音", "error");
      return;
    }
  }

  const current = recorderMap.get(buttonId);
  if (current?.recording) {
    if (current.stop) {
      current.stop();
    } else {
      // getUserMedia 授权对话框期间 stop 尚未就绪。此前这里因 stop 为 null 而
      // 不进停止分支，直接往下走又启动了第二路录音，导致麦克风流与
      // recorder 泄漏。现在改为标记待停止，recorder.start() 后立即收尾。
      current.pendingStop = true;
      setVoiceStatus("正在取消录音…");
    }
    return;
  }

  setRecordingState(btn, true);
  setVoiceStatus("正在录音，再次点击结束…");
  recorderMap.set(buttonId, { recording: true, stop: null });
  // 讲题页显示波形 + 计时器
  if (buttonId === "teachMicBtn") {
    showRecordingPanel();
    startRecordingTimer();
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const chunks = [];
    const recorder = new MediaRecorder(stream, { mimeType: "audio/webm" });
    activeRecorder = recorder;
    // 讲题页启动波形可视化
    if (buttonId === "teachMicBtn") {
      startWaveform(stream);
    }
    recorder.ondataavailable = (evt) => {
      if (evt.data.size > 0) chunks.push(evt.data);
    };
    recorder.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      recorderMap.set(buttonId, { recording: false, stop: null });
      setRecordingState(btn, false);
      if (buttonId === "teachMicBtn") {
        stopWaveform();
        stopRecordingTimer();
        hideRecordingPanel();
      }
      setVoiceStatus("识别中…");
      await withGlobalLoading("正在识别语音…", async () => {
        try {
          const blob = new Blob(chunks, { type: "audio/webm" });
          const text = await transcribeWithAsr(blob, "recording.webm");
          input.value = text.trim();
          if (autoSubmit) input.dispatchEvent(new Event("change"));
          setVoiceStatus("");
        } catch (asrErr) {
          setVoiceStatus("ASR 失败，尝试 Web Speech…");
          setGlobalLoadingMessage("正在识别语音（备用）…");
          try {
            const text = await transcribeWithWebSpeech();
            input.value = text.trim();
            if (autoSubmit) input.dispatchEvent(new Event("change"));
            setVoiceStatus("");
          } catch (wsErr) {
            setVoiceStatus("");
            showBanner?.(
              `${asrErr.message}；降级失败：${wsErr.message}`,
              "error"
            );
          }
        }
      });
    };
    recorder.onerror = () => {
      recorderMap.set(buttonId, { recording: false, stop: null });
      setRecordingState(btn, false);
      if (buttonId === "teachMicBtn") {
        stopWaveform();
        stopRecordingTimer();
        hideRecordingPanel();
      }
      showBanner?.("录音器异常，请重试", "error");
    };
    recorder.start();
    const entry = recorderMap.get(buttonId);
    recorderMap.set(buttonId, {
      recording: true,
      stop: () => recorder.stop(),
    });
    // 授权等待期间用户已经再点了一次，立即停止，避免录音停不下来
    if (entry?.pendingStop) {
      recorder.stop();
    }
  } catch (err) {
    recorderMap.set(buttonId, { recording: false, stop: null });
    setRecordingState(btn, false);
    if (buttonId === "teachMicBtn") {
      stopWaveform();
      stopRecordingTimer();
      hideRecordingPanel();
    }
    try {
      setVoiceStatus("无法访问麦克风，尝试 Web Speech…");
      await withGlobalLoading("正在识别语音…", async () => {
        const text = await transcribeWithWebSpeech();
        input.value = text.trim();
        if (autoSubmit) input.dispatchEvent(new Event("change"));
        setVoiceStatus("");
      });
    } catch (wsErr) {
      showBanner?.(
        `无法访问麦克风：${err.message}；Web Speech：${wsErr.message}`,
        "error"
      );
    }
  }
}

function segmentToAudioSrc(segment) {
  if (!segment) return null;
  if (segment.audio_url) return segment.audio_url;
  if (segment.audio_base64) {
    return `data:audio/mpeg;base64,${segment.audio_base64}`;
  }
  return null;
}

function normalizeTtsSegments(data) {
  if (Array.isArray(data.segments) && data.segments.length) {
    return data.segments
      .map((seg) => segmentToAudioSrc(seg))
      .filter(Boolean);
  }
  const single = segmentToAudioSrc(data);
  return single ? [single] : [];
}

async function loadAudioArrayBuffer(src) {
  const response = await fetch(src);
  if (!response.ok) {
    throw new Error("无法加载音频数据");
  }
  return response.arrayBuffer();
}

async function playAudioSrc(src, token) {
  const ctx = await ensurePlaybackContext();
  if (ctx) {
    try {
      const arrayBuffer = await loadAudioArrayBuffer(src);
      if (token !== activeTtsToken) return;
      const decoded = await ctx.decodeAudioData(arrayBuffer.slice(0));
      if (token !== activeTtsToken) return;
      await new Promise((resolve, reject) => {
        const source = ctx.createBufferSource();
        source.buffer = decoded;
        source.connect(ctx.destination);
        source.onended = resolve;
        try {
          source.start(0);
        } catch (err) {
          reject(err);
        }
      });
      return;
    } catch (err) {
      if (err?.name === "AbortError") throw err;
      console.warn("WebAudio 播放失败，尝试 HTML Audio：", err);
    }
  }

  const audio = new Audio(src);
  if (token !== activeTtsToken) return;
  try {
    await audio.play();
  } catch (err) {
    const msg =
      err?.name === "NotAllowedError"
        ? "浏览器阻止了自动播放，请再次点击「播报讲解」"
        : err?.message || "音频播放失败";
    throw new Error(msg);
  }
  await new Promise((resolve, reject) => {
    audio.onended = resolve;
    audio.onerror = () => reject(new Error("音频播放失败"));
  });
}

async function playTts(text) {
  if (!text?.trim()) {
    showBanner?.("没有可播报的内容", "error");
    return;
  }
  if (!canUseVoiceApi()) {
    openSettingsModal();
    showBanner?.("请先填写 API Key 与模型 ID，或在服务端配置 .env", "error");
    return;
  }

  // 必须在第一次 await 之前保留用户点击带来的播放权限
  primeAudioOnUserGesture();

  const myToken = ++activeTtsToken;
  if (ttsAbortController) {
    ttsAbortController.abort();
  }
  ttsAbortController = new AbortController();
  const { signal } = ttsAbortController;

  const s = loadSettings();
  let synthesisLoadingActive = false;
  setGlobalLoading(true, "正在合成语音…");
  synthesisLoadingActive = true;
  setVoiceStatus("正在合成语音…");
  try {
    const res = await fetch("/api/tts", {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        text: text.trim(),
        voice: s.voice,
        rate: 1.0,
      }),
      signal,
    });
    if (res.status === 401) onApiUnauthorized();
    if (myToken !== activeTtsToken) return;

    const data = await res.json();
    if (!res.ok) {
      throw new Error(
        typeof data.detail === "string" ? data.detail : "语音合成失败"
      );
    }
    const sources = normalizeTtsSegments(data);
    if (!sources.length) throw new Error("未返回音频数据");

    // 合成完成后解除全屏 loading，播放期间不阻塞页面操作
    setGlobalLoading(false);
    synthesisLoadingActive = false;

    const total = sources.length;
    const chunkCount = data.chunk_count || total;
    if (chunkCount > 1) {
      showBanner?.(`讲解较长，将分 ${chunkCount} 段连续播报`, "ok", 2500);
    }

    for (let i = 0; i < total; i += 1) {
      if (myToken !== activeTtsToken) return;
      setVoiceStatus(
        total > 1 ? `播放中 ${i + 1} / ${total}` : "播放中…"
      );
      await playAudioSrc(sources[i], myToken);
    }
    setVoiceStatus("");
  } catch (err) {
    if (err?.name === "AbortError") {
      return;
    }
    setVoiceStatus("");
    showBanner?.(err.message || "语音播报失败", "error");
  } finally {
    if (synthesisLoadingActive && myToken === activeTtsToken) {
      setGlobalLoading(false);
    }
  }
}

function maybeAutoSpeak(text) {
  const clean = (text || "").trim();
  if (!clean) return;
  const s = loadSettings();
  // 生成讲解完成后已无用户点击手势，自动播报常被浏览器拦截
  if (!s.autoSpeak) return;
  if (!audioOutputUnlocked) {
    setVoiceStatus("讲解已生成，请点击「播报讲解」收听");
    setTimeout(() => {
      if (!isGlobalLoading()) setVoiceStatus("");
    }, 4000);
    return;
  }
  playTts(clean);
}

// ===== Karaoke 播报：句子级高亮 + 暂停/停止 =====
let ttsPaused = false;
let ttsPlaying = false;

function splitTextForKaraoke(text) {
  return (text || "")
    .split(/(?<=[。！？；\n])/)
    .map((s) => s.trim())
    .filter(Boolean);
}

async function playTtsKaraoke(text, _container, callbacks = {}) {
  if (!text?.trim()) {
    showBanner?.("没有可播报的内容", "error");
    return;
  }
  if (!canUseVoiceApi()) {
    openSettingsModal();
    showBanner?.("请先填写 API Key 与模型 ID，或在服务端配置 .env", "error");
    return;
  }
  primeAudioOnUserGesture();

  const myToken = ++activeTtsToken;
  if (ttsAbortController) {
    ttsAbortController.abort();
  }
  ttsAbortController = new AbortController();
  const { signal } = ttsAbortController;
  ttsPaused = false;
  ttsPlaying = true;

  const sentences = splitTextForKaraoke(text);
  const s = loadSettings();
  let synthesisLoadingActive = false;
  setGlobalLoading(true, "正在合成语音…");
  synthesisLoadingActive = true;
  setVoiceStatus("正在合成语音…");
  callbacks.onStatus?.("正在合成语音…");
  try {
    const res = await fetch("/api/tts", {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        text: text.trim(),
        voice: s.voice,
        rate: 1.0,
      }),
      signal,
    });
    if (res.status === 401) onApiUnauthorized();
    if (myToken !== activeTtsToken) return;

    const data = await res.json();
    if (!res.ok) {
      throw new Error(
        typeof data.detail === "string" ? data.detail : "语音合成失败"
      );
    }
    const sources = normalizeTtsSegments(data);
    if (!sources.length) throw new Error("未返回音频数据");

    setGlobalLoading(false);
    synthesisLoadingActive = false;

    const total = sources.length;
    const chunkCount = data.chunk_count || total;
    if (chunkCount > 1) {
      showBanner?.(`讲解较长，将分 ${chunkCount} 段连续播报`, "ok", 2500);
    }

    for (let i = 0; i < total; i += 1) {
      if (myToken !== activeTtsToken) return;
      // 暂停时等待恢复
      while (ttsPaused && myToken === activeTtsToken) {
        await new Promise((r) => setTimeout(r, 200));
      }
      if (myToken !== activeTtsToken) return;
      // 高亮当前句子
      if (sentences[i]) {
        callbacks.onSentence?.(i);
      }
      const statusMsg = total > 1 ? `播放中 ${i + 1} / ${total}` : "播放中…";
      setVoiceStatus(statusMsg);
      callbacks.onStatus?.(statusMsg);
      await playAudioSrc(sources[i], myToken);
    }
    setVoiceStatus("");
    ttsPlaying = false;
    callbacks.onSentence?.(-1);
    callbacks.onEnd?.();
  } catch (err) {
    if (err?.name === "AbortError") {
      ttsPlaying = false;
      return;
    }
    setVoiceStatus("");
    ttsPlaying = false;
    showBanner?.(err.message || "语音播报失败", "error");
    callbacks.onEnd?.();
  } finally {
    if (synthesisLoadingActive && myToken === activeTtsToken) {
      setGlobalLoading(false);
    }
  }
}

function toggleTtsPause() {
  if (!ttsPlaying) return null;
  ttsPaused = !ttsPaused;
  return ttsPaused;
}

function stopTts() {
  ttsPaused = false;
  ttsPlaying = false;
  if (ttsAbortController) {
    ttsAbortController.abort();
  }
  setVoiceStatus("");
}

// ===== Lesson 分段播放引擎（HTML5 audio，段级高亮 + 整篇 seek） =====
// 与简单 playTts 路径解耦：用单个持久 <audio> 元素驱动顺序播放，
// 暂停/继续/停止段内即时生效，进度条可跨段拖动。
let lessonSegments = [];          // [{text, audioSrc, duration, metaLoaded}]
let lessonCurrentIndex = -1;
let lessonIsPlaying = false;
let lessonIsPaused = false;
let lessonTotalDuration = 0;
let lessonCumStart = [];          // cumStart[i] = sum(durations[0..i-1])
let lessonPlayToken = 0;          // 播放期重入守卫
let lessonPrefetchToken = 0;      // 预取期重入守卫
let lessonPrefetchAbort = null;
let lessonAudioEl = null;
let lessonCallbacks = {};
let lessonPendingPlay = false;

function formatLessonTime(sec) {
  if (!Number.isFinite(sec) || sec < 0) sec = 0;
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

// 用临时 <audio preload=metadata> 探测单段时长，base64 data URL 在主流浏览器可靠
function probeAudioDuration(src) {
  return new Promise((resolve) => {
    const a = document.createElement("audio");
    a.preload = "metadata";
    let done = false;
    const finish = (v) => {
      if (done) return;
      done = true;
      try { a.removeAttribute("src"); a.load(); } catch (_) {}
      resolve(v);
    };
    a.addEventListener("loadedmetadata", () => {
      const d = a.duration;
      finish(Number.isFinite(d) && d > 0 ? d : 0);
    });
    a.addEventListener("error", () => finish(0));
    setTimeout(() => finish(0), 8000);
    a.src = src;
  });
}

async function preloadSegmentDurations(prefetchToken) {
  const CONCURRENCY = 8;
  let idx = 0;
  async function worker() {
    while (idx < lessonSegments.length) {
      const i = idx++;
      if (prefetchToken !== lessonPrefetchToken) return;
      lessonSegments[i].duration = await probeAudioDuration(lessonSegments[i].audioSrc);
      lessonSegments[i].metaLoaded = true;
    }
  }
  const n = Math.min(CONCURRENCY, lessonSegments.length);
  await Promise.all(Array.from({ length: n }, worker));
}

function computeLessonTimeline() {
  lessonCumStart = [0];
  for (let i = 0; i < lessonSegments.length; i++) {
    lessonCumStart.push(lessonCumStart[i] + (lessonSegments[i].duration || 0));
  }
  lessonTotalDuration = lessonCumStart[lessonSegments.length] || 0;
}

function ensureLessonAudioEl() {
  if (lessonAudioEl) return lessonAudioEl;
  lessonAudioEl = new Audio();
  lessonAudioEl.style.display = "none";
  document.body.appendChild(lessonAudioEl);
  lessonAudioEl.addEventListener("timeupdate", onLessonTimeUpdate);
  lessonAudioEl.addEventListener("ended", onLessonEnded);
  // play 事件统一校正状态；pause 状态由 toggleLessonPlayback 显式管理，
  // 避免 setLessonSrc 内部 a.pause() 误判为用户暂停
  lessonAudioEl.addEventListener("play", () => {
    lessonIsPlaying = true;
    lessonIsPaused = false;
  });
  return lessonAudioEl;
}

function lessonPlayStatusMsg() {
  const total = lessonSegments.length;
  if (!total) return "播放中…";
  return total > 1 ? `播放中 ${lessonCurrentIndex + 1} / ${total}` : "播放中…";
}

// 生成讲解后自动预取全部音频段并预载时长
async function prefetchLessonAudio(text, callbacks = {}) {
  const clean = (text || "").trim();
  if (!clean) return;
  const myToken = ++lessonPrefetchToken;
  if (lessonPrefetchAbort) lessonPrefetchAbort.abort();
  lessonPrefetchAbort = new AbortController();
  lessonCallbacks = callbacks;
  // 重新生成讲解时停掉旧播放
  stopLessonPlayback(false);

  callbacks.onStatus?.("正在合成语音…");
  try {
    const s = loadSettings();
    const res = await fetch("/api/tts", {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ text: clean, voice: s.voice, rate: 1.0 }),
      signal: lessonPrefetchAbort.signal,
    });
    if (res.status === 401) { onApiUnauthorized(); return; }
    if (myToken !== lessonPrefetchToken) return;
    const data = await res.json();
    if (!res.ok) {
      throw new Error(typeof data.detail === "string" ? data.detail : "语音合成失败");
    }
    const segs = (data.segments || [])
      .map((seg) => ({
        text: seg.text || "",
        audioSrc: segmentToAudioSrc(seg),
        duration: 0,
        metaLoaded: false,
      }))
      .filter((seg) => seg.audioSrc);
    if (!segs.length) throw new Error("未返回音频数据");
    lessonSegments = segs;
    await preloadSegmentDurations(myToken);
    if (myToken !== lessonPrefetchToken) return;
    computeLessonTimeline();
    const segTexts = lessonSegments.map((seg) => seg.text);
    callbacks.onReady?.(segTexts, {
      total: lessonTotalDuration,
      count: lessonSegments.length,
    });
    callbacks.onStatus?.(
      lessonTotalDuration > 0
        ? `语音就绪（${lessonSegments.length} 段，约 ${formatLessonTime(lessonTotalDuration)}）`
        : `语音就绪（${lessonSegments.length} 段）`
    );
    if (lessonPendingPlay) {
      lessonPendingPlay = false;
      playLessonAudio();
    }
  } catch (err) {
    if (err?.name === "AbortError") return;
    callbacks.onStatus?.("");
    showBanner?.(err.message || "语音预取失败", "error");
  }
}

function playLessonAudio(callbacks) {
  if (callbacks) lessonCallbacks = { ...lessonCallbacks, ...callbacks };
  if (!lessonSegments.length) {
    // 预取未完成：登记待播，onReady 内自动启动
    lessonPendingPlay = true;
    lessonCallbacks.onStatus?.("正在合成语音，请稍候…");
    return;
  }
  primeAudioOnUserGesture();
  const myToken = ++lessonPlayToken;
  lessonIsPlaying = true;
  lessonIsPaused = false;
  if (lessonCurrentIndex < 0) lessonCurrentIndex = 0;
  ensureLessonAudioEl();
  highlightLessonSegment(lessonCurrentIndex);
  lessonCallbacks.onStatus?.(lessonPlayStatusMsg());
  setLessonSrc(lessonCurrentIndex, 0, true, myToken);
}

// 切换到第 j 段并可选 seek + 续播
function setLessonSrc(j, seekOffset = 0, forcePlay = false, token = lessonPlayToken) {
  const a = ensureLessonAudioEl();
  lessonCurrentIndex = j;
  a.pause();
  a.src = lessonSegments[j].audioSrc;
  const onMeta = () => {
    a.removeEventListener("loadedmetadata", onMeta);
    if (token !== lessonPlayToken) return;
    if (seekOffset > 0 && seekOffset < (a.duration || 0)) {
      try { a.currentTime = seekOffset; } catch (_) {}
    }
    if (forcePlay && lessonIsPlaying && !lessonIsPaused) {
      a.play().catch((err) => {
        if (err?.name === "NotAllowedError") {
          lessonCallbacks.onStatus?.("请点击「播报讲解」开始播放");
        }
      });
    }
  };
  a.addEventListener("loadedmetadata", onMeta);
}

function onLessonEnded() {
  if (lessonCurrentIndex < lessonSegments.length - 1) {
    const next = lessonCurrentIndex + 1;
    lessonCurrentIndex = next;
    highlightLessonSegment(next);
    lessonCallbacks.onStatus?.(lessonPlayStatusMsg());
    setLessonSrc(next, 0, true);
  } else {
    finishLesson();
  }
}

function onLessonTimeUpdate() {
  if (lessonCurrentIndex < 0) return;
  const now = (lessonCumStart[lessonCurrentIndex] || 0) + (lessonAudioEl.currentTime || 0);
  lessonCallbacks.onProgress?.(now, lessonTotalDuration);
}

function toggleLessonPause() {
  if (!lessonIsPlaying || !lessonAudioEl) return null;
  if (lessonIsPaused) {
    lessonIsPaused = false;
    lessonAudioEl.play().catch(() => {
      lessonCallbacks.onStatus?.("请点击「播报讲解」开始播放");
    });
    return false; // 已恢复
  }
  lessonIsPaused = true;
  lessonAudioEl.pause();
  return true; // 已暂停
}

function stopLessonPlayback(triggerOnEnd = true) {
  lessonPlayToken++;
  lessonIsPlaying = false;
  lessonIsPaused = false;
  lessonCurrentIndex = -1;
  lessonPendingPlay = false;
  if (lessonAudioEl) {
    lessonAudioEl.pause();
    lessonAudioEl.removeAttribute("src");
    try { lessonAudioEl.load(); } catch (_) {}
  }
  if (triggerOnEnd) lessonCallbacks.onEnd?.();
}

function finishLesson() {
  lessonIsPlaying = false;
  lessonIsPaused = false;
  lessonCurrentIndex = -1;
  if (lessonAudioEl) {
    lessonAudioEl.pause();
    lessonAudioEl.removeAttribute("src");
    try { lessonAudioEl.load(); } catch (_) {}
  }
  lessonCallbacks.onSegment?.(-1);
  lessonCallbacks.onStatus?.("");
  lessonCallbacks.onProgress?.(0, lessonTotalDuration);
  lessonCallbacks.onEnd?.();
}

function highlightLessonSegment(i) {
  lessonCallbacks.onSegment?.(i);
}

// 整篇拖动：targetOverall 秒 → 定位段 j + 段内 offset
function seekLesson(targetOverall) {
  if (!lessonSegments.length || lessonTotalDuration <= 0) return;
  let j = 0;
  for (let k = 0; k < lessonSegments.length; k++) {
    if ((lessonCumStart[k] || 0) <= targetOverall + 0.001) j = k;
    else break;
  }
  const offset = Math.max(0, targetOverall - (lessonCumStart[j] || 0));
  const forcePlay = lessonIsPlaying && !lessonIsPaused;
  if (j !== lessonCurrentIndex) {
    highlightLessonSegment(j);
    setLessonSrc(j, offset, forcePlay);
  } else if (lessonAudioEl) {
    try { lessonAudioEl.currentTime = offset; } catch (_) {}
  }
  // 暂停态拖拽：仅更新位置不续播，手动推一次进度显示
  if (!forcePlay) {
    lessonCallbacks.onProgress?.(targetOverall, lessonTotalDuration);
  }
}

function seekLessonSegment(delta) {
  if (!lessonSegments.length) return;
  const cur = lessonCurrentIndex < 0 ? 0 : lessonCurrentIndex;
  const target = Math.min(lessonSegments.length - 1, Math.max(0, cur + delta));
  if (target === lessonCurrentIndex) return;
  const forcePlay = lessonIsPlaying && !lessonIsPaused;
  highlightLessonSegment(target);
  setLessonSrc(target, 0, forcePlay);
  lessonCallbacks.onStatus?.(lessonPlayStatusMsg());
}

function bindSpeechButtonToInput(buttonId, inputId, autoSubmit = false) {
  const btn = document.getElementById(buttonId);
  if (!btn) return;
  if (btn.dataset.voiceBound === buttonId) return;
  btn.dataset.voiceBound = buttonId;
  btn.addEventListener("click", () => {
    startSpeechCapture(buttonId, inputId, autoSubmit);
  });
}

function initVoiceUI() {
  if (window.__voiceUiInitialized) return;
  window.__voiceUiInitialized = true;
  initSettingsUI();
  initPermissionGate();
  syncPermissionStateFromBrowser();
  attachAudioUnlockOnFirstGesture();
  bindSpeechButtonToInput("teachMicBtn", "teachInput", false);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initVoiceUI);
} else {
  initVoiceUI();
}

window.playTts = playTts;
window.playTtsKaraoke = playTtsKaraoke;
window.toggleTtsPause = toggleTtsPause;
window.stopTts = stopTts;
// ===== 互讲页：录制按钮 + 回复播放控制 =====
// 记录最近一条 AI 回复，供「播放回复」重播（此前只有 autoSpeak 自动播一次，
// 没听清就再也没法重听，也没有暂停手段）。
let lastTeachReply = "";
let teachPlaying = false;

function setTeachReplyText(text) {
  lastTeachReply = (text || "").trim();
  const playBtn = document.getElementById("teachPlayBtn");
  const status = document.getElementById("teachAudioStatus");
  if (playBtn) playBtn.disabled = !lastTeachReply;
  if (status) {
    status.textContent = lastTeachReply ? "可播放 AI 同学的回复" : "暂无可播放的回复";
  }
}

function syncTeachAudioUi(playing) {
  teachPlaying = playing;
  const playBtn = document.getElementById("teachPlayBtn");
  const pauseBtn = document.getElementById("teachPauseBtn");
  if (playBtn) playBtn.classList.toggle("hidden", playing);
  if (pauseBtn) pauseBtn.classList.toggle("hidden", !playing);
  const status = document.getElementById("teachAudioStatus");
  if (status && lastTeachReply) {
    status.textContent = playing ? "播放中…" : "已暂停，点「播放回复」继续";
  }
}

function bindTeachControls() {
  const recordBtn = document.getElementById("teachRecordBtn");
  if (recordBtn && recordBtn.dataset.bound !== "1") {
    recordBtn.dataset.bound = "1";
    // 与麦克风图标按钮共用同一套录音状态（recorderMap 以 teachMicBtn 为键），
    // 这样两个入口互不冲突，点哪个都能停。
    recordBtn.addEventListener("click", () => {
      startSpeechCapture("teachMicBtn", "teachInput", false);
    });
  }
  const playBtn = document.getElementById("teachPlayBtn");
  if (playBtn && playBtn.dataset.bound !== "1") {
    playBtn.dataset.bound = "1";
    playBtn.addEventListener("click", async () => {
      if (!lastTeachReply) return;
      // 已在播放中途暂停过，则继续；否则从头合成播放
      if (teachPlaying) return;
      syncTeachAudioUi(true);
      try {
        await playTts(lastTeachReply);
      } finally {
        syncTeachAudioUi(false);
      }
    });
  }
  const pauseBtn = document.getElementById("teachPauseBtn");
  if (pauseBtn && pauseBtn.dataset.bound !== "1") {
    pauseBtn.dataset.bound = "1";
    pauseBtn.addEventListener("click", () => {
      toggleTtsPause();
      syncTeachAudioUi(false);
    });
  }
}

document.addEventListener("DOMContentLoaded", bindTeachControls);

window.setTeachReplyText = setTeachReplyText;
window.bindTeachControls = bindTeachControls;
window.prefetchLessonAudio = prefetchLessonAudio;
window.playLessonAudio = playLessonAudio;
window.toggleLessonPause = toggleLessonPause;
window.stopLessonPlayback = stopLessonPlayback;
window.seekLesson = seekLesson;
window.seekLessonSegment = seekLessonSegment;
window.formatLessonTime = formatLessonTime;
window.setGlobalLoading = setGlobalLoading;
window.setGlobalLoadingMessage = setGlobalLoadingMessage;
window.withGlobalLoading = withGlobalLoading;
window.isGlobalLoading = isGlobalLoading;
window.maybeAutoSpeak = maybeAutoSpeak;
window.bindSpeechButtonToInput = bindSpeechButtonToInput;
window.openSettingsModal = openSettingsModal;
window.closeSettingsModal = closeSettingsModal;
window.authHeaders = authHeaders;
window.onApiUnauthorized = onApiUnauthorized;
window.isClientConfigured = isClientConfigured;
window.getModel = getModel;
window.enableVoiceFeatures = enableVoiceFeatures;
window.primeAudioOnUserGesture = primeAudioOnUserGesture;
window.isMicPermissionGranted = () => micPermissionGranted;
window.isAudioOutputUnlocked = () => audioOutputUnlocked;
window.canUseVoiceApi = canUseVoiceApi;
