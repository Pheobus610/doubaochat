const STEPS = ["grade", "upload", "lesson", "quiz", "analysis", "teach"];

const STEP_META = {
  grade: { title: "选择年级与科目", nextLabel: "下一步：上传 PDF" },
  upload: { title: "上传 PDF", nextLabel: "下一步：听讲解", prevLabel: "上一步：选年级" },
  lesson: { title: "听讲解", nextLabel: "下一步：做题", prevLabel: "上一步：上传" },
  quiz: { title: "做题", nextLabel: "下一步：错题分析", prevLabel: "上一步：讲解" },
  analysis: { title: "错题分析", nextLabel: "下一步：向 AI 讲题", prevLabel: "上一步：做题" },
  teach: { title: "向 AI 讲题", nextLabel: "完成学习", prevLabel: "上一步：分析" },
};

const FLOW_STORAGE_KEY = "doubaochat_flow_state";
const MAX_TEACH_STUDENT_ROUNDS = 2;

const state = {
  files: [],
  clientId: localStorage.getItem("doubaochat_client_id") || null,
  serverConfigured: false,
  grade: "",
  subject: "",
  sessionReady: false,
  lessonText: "",
  lessonKnowledgePoints: [],
  quizQuestions: [],
  quizIndex: 0,
  answerResults: {},
  correctCount: 0,
  wrongCount: 0,
  variantQuestions: [],
  variantIndex: 0,
  variantAnswerResults: {},
  analysisSummary: "",
  analysisReasons: [],
  wrongQuestions: [],
  analysisDone: false,
  teachUnlocked: false,
  teachInvite: "",
  teachTurns: [],
  teachStudentRounds: 0,
  learningCompleted: false,
  currentStep: "grade",
  maxReachedIndex: 0,
};

const statusBanner = document.getElementById("statusBanner");
const gradeSummaryText = document.getElementById("gradeSummaryText");
const gradeSelectionCard = document.getElementById("gradeSelectionCard");
const uploadGradeHint = document.getElementById("uploadGradeHint");
const dropZone = document.getElementById("dropZone");
const fileInput = document.getElementById("fileInput");
const fileList = document.getElementById("fileList");
const startSessionBtn = document.getElementById("startSessionBtn");
const explainBtn = document.getElementById("explainBtn");
const playLessonBtn = document.getElementById("playLessonBtn");
const lessonBox = document.getElementById("lessonBox");
const generateQuizBtn = document.getElementById("generateQuizBtn");
const quizProgress = document.getElementById("quizProgress");
const quizBox = document.getElementById("quizBox");
const analyzeBtn = document.getElementById("analyzeBtn");
const analysisReasonBox = document.getElementById("analysisReasonBox");
const variantQuizBox = document.getElementById("variantQuizBox");
const variantProgress = document.getElementById("variantProgress");
const inviteTeachBtn = document.getElementById("inviteTeachBtn");
const teachUnlockBadge = document.getElementById("teachUnlockBadge");
const teachRoundBadge = document.getElementById("teachRoundBadge");
const teachChatLog = document.getElementById("teachChatLog");
const teachInput = document.getElementById("teachInput");
const teachMicBtn = document.getElementById("teachMicBtn");
const teachSubmitBtn = document.getElementById("teachSubmitBtn");
const learningCompleteModal = document.getElementById("learningCompleteModal");
const learningCompleteMessage = document.getElementById("learningCompleteMessage");
const learningCompleteClose = document.getElementById("learningCompleteClose");
const navPrevBtn = document.getElementById("navPrevBtn");
const navNextBtn = document.getElementById("navNextBtn");
const stepper = document.getElementById("stepper");

function stepIndex(step) {
  const idx = STEPS.indexOf(step);
  return idx >= 0 ? idx : 0;
}

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function showBanner(text, type = "error", autoHideMs = 0) {
  statusBanner.textContent = text;
  statusBanner.className = `status-banner ${type}`;
  statusBanner.classList.remove("hidden");
  if (autoHideMs > 0) {
    setTimeout(() => hideBanner(), autoHideMs);
  }
}

function hideBanner() {
  statusBanner.classList.add("hidden");
}

function canUseApi() {
  if (state.serverConfigured) return true;
  return typeof window.isClientConfigured === "function" && window.isClientConfigured();
}

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

function persistState() {
  const payload = {
    grade: state.grade,
    subject: state.subject,
    clientId: state.clientId,
    sessionReady: state.sessionReady,
    lessonText: state.lessonText ? state.lessonText.slice(0, 2000) : "",
    quizQuestions: state.quizQuestions,
    quizIndex: state.quizIndex,
    correctCount: state.correctCount,
    wrongCount: state.wrongCount,
    variantQuestions: state.variantQuestions,
    variantIndex: state.variantIndex,
    variantAnswerResults: state.variantAnswerResults,
    analysisSummary: state.analysisSummary,
    analysisReasons: state.analysisReasons,
    wrongQuestions: state.wrongQuestions,
    analysisDone: state.analysisDone,
    teachUnlocked: state.teachUnlocked,
    teachInvite: state.teachInvite,
    teachTurns: state.teachTurns,
    teachStudentRounds: state.teachStudentRounds,
    learningCompleted: state.learningCompleted,
    files: state.files.map((f) => ({
      filename: f.filename,
      size: f.size,
      file_id: f.file_id,
      uploading: false,
    })),
    currentStep: state.currentStep,
    maxReachedIndex: state.maxReachedIndex,
  };
  sessionStorage.setItem(FLOW_STORAGE_KEY, JSON.stringify(payload));
}

function restoreState() {
  try {
    const raw = sessionStorage.getItem(FLOW_STORAGE_KEY);
    if (!raw) return;
    const data = JSON.parse(raw);
    if (data.grade) state.grade = data.grade;
    if (data.subject) state.subject = data.subject;
    if (data.clientId) state.clientId = data.clientId;
    state.sessionReady = Boolean(data.sessionReady);
    state.lessonText = data.lessonText || "";
    state.quizQuestions = data.quizQuestions || [];
    state.quizIndex = data.quizIndex || 0;
    state.correctCount = data.correctCount || 0;
    state.wrongCount = data.wrongCount || 0;
    state.variantQuestions = data.variantQuestions || [];
    state.variantIndex = data.variantIndex || 0;
    state.variantAnswerResults = data.variantAnswerResults || {};
    state.analysisSummary = data.analysisSummary || "";
    state.analysisReasons = data.analysisReasons || [];
    state.wrongQuestions = data.wrongQuestions || [];
    state.analysisDone = Boolean(data.analysisDone);
    state.teachUnlocked = Boolean(data.teachUnlocked);
    state.teachInvite = data.teachInvite || "";
    state.teachTurns = data.teachTurns || [];
    state.teachStudentRounds = data.teachStudentRounds || 0;
    state.learningCompleted = Boolean(data.learningCompleted);
    state.files = data.files || [];
    state.maxReachedIndex = data.maxReachedIndex || 0;
    if (data.currentStep && STEPS.includes(data.currentStep)) {
      state.currentStep = data.currentStep;
    }
    if (state.lessonText && lessonBox) {
      renderLessonText(state.lessonText);
    }
  } catch {
    /* ignore corrupt storage */
  }
}

function parseRoute() {
  const hash = (location.hash || "").replace(/^#\/?/, "").trim();
  if (!hash) return "grade";
  const step = hash.split("/")[0];
  return STEPS.includes(step) ? step : "grade";
}

function canEnterStep(step) {
  const targetIdx = stepIndex(step);
  return targetIdx <= state.maxReachedIndex;
}

function meetsGate(step) {
  switch (step) {
    case "grade":
      return Boolean(state.grade && state.subject);
    case "upload":
      return state.sessionReady && getUploadedFileIds().length > 0;
    case "lesson":
      return Boolean(state.lessonText.trim());
    case "quiz":
      return state.quizQuestions.length > 0;
    case "analysis":
      return state.quizQuestions.length > 0;
    case "teach":
      return Boolean(state.lessonText.trim());
    default:
      return false;
  }
}

function updateMaxReached(step) {
  const idx = stepIndex(step);
  if (idx > state.maxReachedIndex) {
    state.maxReachedIndex = idx;
  }
}

function isQuizCompleted() {
  return state.quizQuestions.length > 0 && state.quizIndex >= state.quizQuestions.length;
}

function shouldSkipAnalysis() {
  return isQuizCompleted() && state.wrongCount === 0;
}

function skipAnalysisToTeach(message) {
  updateMaxReached("analysis");
  updateMaxReached("teach");
  persistState();
  if (message) {
    showBanner(message, "ok", 3000);
  }
  navigateTo("teach", { replace: true });
}

function renderGradeSummary() {
  if (!gradeSummaryText || !gradeSelectionCard) return;
  if (!state.grade && !state.subject) {
    gradeSummaryText.textContent = "尚未选择年级与科目";
    gradeSelectionCard.classList.remove("selected");
    return;
  }
  if (state.grade && state.subject) {
    gradeSummaryText.textContent = `已选：${state.grade} · ${state.subject}`;
    gradeSelectionCard.classList.add("selected");
  } else if (state.grade) {
    gradeSummaryText.textContent = `已选年级：${state.grade}，请选择科目`;
    gradeSelectionCard.classList.remove("selected");
  } else {
    gradeSummaryText.textContent = `已选科目：${state.subject}，请选择年级`;
    gradeSelectionCard.classList.remove("selected");
  }
  if (uploadGradeHint && state.grade && state.subject) {
    uploadGradeHint.textContent = `当前学习：${state.grade} · ${state.subject}`;
  }
}

function syncGradeSubjectButtons() {
  document.querySelectorAll(".grade-btn").forEach((btn) => {
    const selected = btn.dataset.grade === state.grade;
    btn.classList.toggle("is-selected", selected);
    btn.setAttribute("aria-pressed", selected ? "true" : "false");
  });
  document.querySelectorAll(".subject-btn").forEach((btn) => {
    const selected = btn.dataset.subject === state.subject;
    btn.classList.toggle("is-selected", selected);
    btn.setAttribute("aria-pressed", selected ? "true" : "false");
  });
}

function onGradeSubjectChanged(changedLabel) {
  renderGradeSummary();
  if (state.grade && state.subject) {
    state.maxReachedIndex = Math.max(state.maxReachedIndex, stepIndex("upload"));
    showBanner(`已选择 ${state.grade} · ${state.subject}`, "ok", 2000);
  } else {
    showBanner(`已选择${changedLabel}`, "ok", 1500);
  }
  persistState();
  updateNavButtons();
}

function selectGrade(grade) {
  state.grade = grade;
  syncGradeSubjectButtons();
  onGradeSubjectChanged(grade);
}

function selectSubject(subject) {
  state.subject = subject;
  syncGradeSubjectButtons();
  onGradeSubjectChanged(subject);
}

function renderStepper() {
  if (!stepper) return;
  const currentIdx = stepIndex(state.currentStep);
  stepper.querySelectorAll(".stepper-item").forEach((btn) => {
    const step = btn.dataset.step;
    const idx = stepIndex(step);
    btn.classList.toggle("active", step === state.currentStep);
    btn.classList.toggle("done", idx < currentIdx || (idx <= state.maxReachedIndex && meetsGate(step)));
    btn.disabled = idx > state.maxReachedIndex;
  });
}

function showPage(step) {
  state.currentStep = step;
  document.querySelectorAll(".page-panel").forEach((panel) => {
    panel.classList.toggle("is-active", panel.dataset.step === step);
  });
  renderStepper();
  updateNavButtons();
  if (step === "analysis") {
    if (shouldSkipAnalysis()) {
      skipAnalysisToTeach("全部答对，已跳过错题分析");
      return;
    }
    if (state.analysisDone) {
      renderAnalysisReason();
      if (state.variantQuestions.length) {
        renderCurrentVariant();
      }
    }
  }
  if (step === "teach") {
    if (typeof window.bindSpeechButtonToInput === "function") {
      window.bindSpeechButtonToInput("teachMicBtn", "teachInput", false);
    }
    renderTeachChat();
    updateTeachRoundUI();
  }
  if (step === "quiz" && state.quizQuestions.length) {
    renderCurrentQuestion();
  }
  persistState();
}

function navigateTo(step, { replace = false } = {}) {
  if (typeof window.isGlobalLoading === "function" && window.isGlobalLoading()) return;
  if (!STEPS.includes(step)) step = "grade";
  if (!canEnterStep(step) && step !== "grade") {
    showBanner("请先完成前面的步骤", "error");
    return;
  }
  const hash = `#/${step}`;
  if (replace) {
    history.replaceState({ step }, "", hash);
  } else {
    history.pushState({ step }, "", hash);
  }
  showPage(step);
}

function updateNavButtons() {
  const step = state.currentStep;
  const idx = stepIndex(step);
  const meta = STEP_META[step];

  if (navPrevBtn) {
    if (idx === 0) {
      navPrevBtn.classList.add("hidden");
    } else {
      navPrevBtn.classList.remove("hidden");
      navPrevBtn.textContent = meta.prevLabel || "上一步";
    }
  }

  if (navNextBtn) {
    let nextLabel = meta.nextLabel || "下一步";
    if (step === "quiz" && shouldSkipAnalysis()) {
      nextLabel = "下一步：向 AI 讲题";
    }
    navNextBtn.textContent = nextLabel;
    const canNext = meetsGate(step);
    navNextBtn.disabled = !canNext;
    if (step === "teach") {
      navNextBtn.disabled = false;
      navNextBtn.textContent = "完成学习";
    }
  }
}

function goNext() {
  const idx = stepIndex(state.currentStep);
  if (!meetsGate(state.currentStep) && state.currentStep !== "teach") {
    showBanner("请先完成当前步骤要求", "error");
    return;
  }
  if (state.currentStep === "teach") {
    if (state.learningCompleted) {
      showLearningCompleteModal();
    } else {
      const remaining = MAX_TEACH_STUDENT_ROUNDS - state.teachStudentRounds;
      showBanner(`还需完成 ${remaining} 轮互讲`, "error");
    }
    return;
  }
  if (state.currentStep === "quiz" && shouldSkipAnalysis()) {
    skipAnalysisToTeach("全部答对，已跳过错题分析");
    return;
  }
  const next = STEPS[idx + 1];
  updateMaxReached(next);
  navigateTo(next);
}

function goPrev() {
  const idx = stepIndex(state.currentStep);
  if (idx > 0) {
    navigateTo(STEPS[idx - 1]);
  }
}

function setTeachUnlock(unlocked) {
  state.teachUnlocked = Boolean(unlocked);
  teachUnlockBadge.textContent = unlocked ? "已解锁" : "未解锁";
  teachUnlockBadge.className = `unlock-badge ${unlocked ? "unlocked" : "locked"}`;
  inviteTeachBtn.classList.toggle("btn-primary", unlocked);
  inviteTeachBtn.classList.toggle("btn-secondary", !unlocked);
  updateTeachRoundUI();
  persistState();
}

function teachChatLabel(turn) {
  if (turn.role === "student") {
    return turn.round ? `第 ${turn.round} 轮 · 你的讲解` : "你的讲解";
  }
  return turn.round ? `第 ${turn.round} 轮 · AI 老师` : "AI 老师";
}

function renderTeachChat() {
  if (!teachChatLog) return;
  if (!state.teachTurns.length) {
    teachChatLog.innerHTML =
      '<p class="teach-chat-placeholder hint-text">可先获取 AI 邀请，或直接向 AI 讲解（最多 2 轮）。</p>';
    return;
  }
  teachChatLog.innerHTML = state.teachTurns
    .map((turn) => {
      const roleClass = turn.role === "student" ? "student" : "ai";
      return `
        <div class="chat-bubble ${roleClass}">
          <span class="chat-meta">${escapeHtml(teachChatLabel(turn))}</span>
          ${escapeHtml(turn.content || "")}
        </div>
      `;
    })
    .join("");
  teachChatLog.scrollTop = teachChatLog.scrollHeight;
}

function updateTeachRoundUI() {
  if (teachRoundBadge) {
    teachRoundBadge.textContent = `互讲 ${state.teachStudentRounds} / ${MAX_TEACH_STUDENT_ROUNDS} 轮`;
  }
  const done =
    state.learningCompleted || state.teachStudentRounds >= MAX_TEACH_STUDENT_ROUNDS;
  const locked = !state.teachUnlocked;
  if (teachInput) teachInput.disabled = done || locked;
  if (teachMicBtn) teachMicBtn.disabled = done || locked;
  if (teachSubmitBtn) {
    teachSubmitBtn.disabled = done || locked;
    if (done) {
      teachSubmitBtn.textContent = "互讲已结束";
    } else if (locked) {
      teachSubmitBtn.textContent = "未解锁互讲";
    } else {
      const nextRound = state.teachStudentRounds + 1;
      teachSubmitBtn.textContent = `提交第 ${nextRound} 轮讲解`;
    }
  }
}

function showLearningCompleteModal() {
  if (!learningCompleteModal) return;
  const gradeHint = state.grade ? `${state.grade} · ${state.subject}` : "本次";
  if (learningCompleteMessage) {
    learningCompleteMessage.textContent = `你已完成 ${MAX_TEACH_STUDENT_ROUNDS} 轮向 AI 讲题，${gradeHint}学习流程结束。辛苦了！`;
  }
  learningCompleteModal.classList.remove("hidden");
}

function hideLearningCompleteModal() {
  learningCompleteModal?.classList.add("hidden");
}

function resetTeachState() {
  state.teachTurns = [];
  state.teachStudentRounds = 0;
  state.learningCompleted = false;
  state.teachInvite = "";
  renderTeachChat();
  updateTeachRoundUI();
}

function renderFileList() {
  fileList.innerHTML = "";
  state.files.forEach((f, index) => {
    const li = document.createElement("li");
    li.className = `file-item${f.uploading ? " uploading" : ""}`;
    li.innerHTML = `
      <div>
        <div class="name">${escapeHtml(f.filename)}</div>
        <div class="meta">${f.uploading ? "上传中…" : formatSize(f.size)}</div>
      </div>
      <button type="button" class="remove" aria-label="移除" data-index="${index}">×</button>
    `;
    fileList.appendChild(li);
  });
  fileList.querySelectorAll(".remove").forEach((btn) => {
    btn.addEventListener("click", () => {
      const i = Number(btn.dataset.index);
      state.files.splice(i, 1);
      renderFileList();
      persistState();
      updateNavButtons();
    });
  });
}

function getUploadedFileIds() {
  return state.files.filter((f) => f.file_id && !f.uploading).map((f) => f.file_id);
}

async function checkHealth() {
  try {
    const res = await fetch("/api/health");
    const data = await res.json();
    state.serverConfigured = Boolean(data.configured);
    window.isServerConfigured = () => state.serverConfigured;
    const clientOk =
      typeof window.isClientConfigured === "function" && window.isClientConfigured();
    if (state.serverConfigured || clientOk) {
      const model =
        (typeof window.getModel === "function" && window.getModel()) || data.model || "—";
      showBanner(`已连接 · 模型 ${model}`, "ok", 2500);
      return;
    }
    showBanner(data.message || "请先在设置中填写 API Key 与模型 ID", "error");
  } catch {
    showBanner("无法连接后端，请确认服务已启动", "error");
  }
}

async function apiPost(path, payload, loadingMessage = "请稍候…") {
  const run = async () => {
    const headers =
      typeof window.authHeaders === "function"
        ? window.authHeaders({ "Content-Type": "application/json" })
        : { "Content-Type": "application/json" };
    const res = await fetch(path, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
    });
    const text = await res.text();
    let data = {};
    if (text) {
      try {
        data = JSON.parse(text);
      } catch (e) {
        throw new Error(`响应解析失败 (${res.status}): ${text.slice(0, 200)}`);
      }
    }
    if (!res.ok) {
      const detail =
        typeof data.detail === "string"
          ? data.detail
          : data.error || JSON.stringify(data.detail || data);
      // 会话失效（服务重启 / 过期）：清除旧 clientId，引导重新开始
      if (res.status === 404 && detail.includes("会话不存在")) {
        state.clientId = null;
        localStorage.removeItem("doubaochat_client_id");
        state.sessionReady = false;
        persistState();
        updateNavButtons();
        navigateTo("upload");
      }
      throw new Error(detail || `请求失败 (${res.status})`);
    }
    return data;
  };
  if (typeof window.withGlobalLoading === "function") {
    return window.withGlobalLoading(loadingMessage, run);
  }
  return run();
}

async function uploadFile(file) {
  if (!file.name.toLowerCase().endsWith(".pdf")) {
    showBanner("仅支持 PDF 文件", "error");
    return;
  }
  if (!canUseApi()) {
    window.openSettingsModal?.();
    showBanner("请先填写 API Key 与模型 ID", "error");
    return;
  }
  const entry = {
    filename: file.name,
    size: file.size,
    file_id: null,
    uploading: true,
  };
  state.files.push(entry);
  renderFileList();
  persistState();
  const form = new FormData();
  form.append("file", file);
  const doUpload = async () => {
    const headers = typeof window.authHeaders === "function" ? window.authHeaders() : {};
    const res = await fetch("/api/upload", { method: "POST", headers, body: form });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(typeof data.detail === "string" ? data.detail : "上传失败");
    }
    entry.file_id = data.file_id;
    entry.size = data.size;
    entry.uploading = false;
    renderFileList();
    persistState();
    updateNavButtons();
  };
  try {
    if (typeof window.withGlobalLoading === "function") {
      await window.withGlobalLoading("正在上传 PDF…", doUpload);
    } else {
      await doUpload();
    }
  } catch (err) {
    state.files = state.files.filter((f) => f !== entry);
    renderFileList();
    persistState();
    showBanner(err.message || "上传失败", "error");
  }
}

function handleFiles(fileListLike) {
  const files = Array.from(fileListLike || []).filter((f) =>
    f.name.toLowerCase().endsWith(".pdf")
  );
  files.forEach(uploadFile);
}

function optionLetter(index) {
  return ["A", "B", "C", "D"][index] || "";
}

function normOpt(s) {
  return (s || "").trim();
}

function buildAnswerControls(question, ids, answeredResult) {
  const { answerInputId, micBtnId, fillSubmitBtnId } = ids;
  const disabled = answeredResult ? "disabled" : "";
  const userAns = answeredResult ? normOpt(answeredResult.user_answer) : "";

  if (question.type === "choice") {
    const correctAns = normOpt(question.answer);
    return `
      <div class="answer-grid">
        ${["A", "B", "C", "D"]
          .map((opt) => {
            let extra = "";
            if (answeredResult) {
              if (opt === correctAns) extra = " is-correct";
              else if (opt === userAns) extra = " is-wrong";
            }
            return `<button type="button" class="btn btn-secondary option-btn${extra}" data-answer="${opt}" ${disabled}><span class="opt-key">${opt}</span></button>`;
          })
          .join("")}
      </div>
    `;
  }
  if (question.type === "judge") {
    const correctAns = normOpt(question.answer);
    const opts = [
      { v: "对", label: "对" },
      { v: "错", label: "错" },
    ];
    return `
      <div class="answer-grid">
        ${opts
          .map((opt) => {
            let extra = "";
            if (answeredResult) {
              if (opt.v === correctAns) extra = " is-correct";
              else if (opt.v === userAns) extra = " is-wrong";
            }
            return `<button type="button" class="btn btn-secondary option-btn${extra}" data-answer="${opt.v}" ${disabled}>${opt.label}</button>`;
          })
          .join("")}
      </div>
    `;
  }
  return `
    <div class="answer-inline">
      <input type="text" id="${answerInputId}" placeholder="请输入答案" value="${answeredResult ? escapeHtml(answeredResult.user_answer || "") : ""}" ${disabled} />
      <button type="button" id="${micBtnId}" class="btn btn-icon" title="语音输入" aria-label="语音输入" ${disabled}>🎤</button>
    </div>
    ${answeredResult ? "" : `<button type="button" id="${fillSubmitBtnId}" class="btn btn-secondary">提交填空答案</button>`}
  `;
}

function renderQuestionCard(container, question, meta, onSubmit, opts = {}) {
  const ids = {
    answerInputId: meta.answerInputId || "answerInput",
    micBtnId: meta.micBtnId || "answerMicBtn",
    fillSubmitBtnId: meta.fillSubmitBtnId || "fillSubmitBtn",
    feedbackId: meta.feedbackId || "answerFeedback",
  };
  const answeredResult = opts.answeredResult || null;
  const isLast = opts.isLast || false;
  const answerControls = buildAnswerControls(question, ids, answeredResult);
  const feedbackHtml = answeredResult
    ? `<div id="${ids.feedbackId}" class="answer-feedback ${answeredResult.correct ? "ok" : "error"}">${answeredResult.correct ? "✓ 回答正确" : "✗ 回答不正确"}：${escapeHtml(answeredResult.feedback || "")}</div>
       <div class="question-actions">
         <button type="button" class="btn btn-primary next-question-btn">${isLast ? "完成答题" : "下一题"} <span aria-hidden="true">→</span></button>
       </div>`
    : `<div id="${ids.feedbackId}" class="answer-feedback hint-text">等待作答…${question.type === "choice" ? "（可按 A/B/C/D 键）" : ""}</div>`;
  container.innerHTML = `
    <div class="question-card">
      <div class="question-meta">${escapeHtml(meta.progressLabel)} · ${escapeHtml(question.type_label || "")}</div>
      <div class="question-title">${escapeHtml(question.question_text || "")}</div>
      ${
        question.options && question.options.length
          ? `<ul class="options-list">${question.options
              .map((it, i) => `<li><span class="opt-key">${optionLetter(i)}</span> ${escapeHtml(it.replace(/^[A-D][.、:]\s*/, ""))}</li>`)
              .join("")}</ul>`
          : ""
      }
      ${answerControls}
      ${feedbackHtml}
    </div>
  `;
  container.querySelectorAll(".option-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.disabled) return;
      onSubmit(btn.dataset.answer || "");
    });
  });
  const fillSubmitBtn = document.getElementById(ids.fillSubmitBtnId);
  if (fillSubmitBtn) {
    fillSubmitBtn.addEventListener("click", () => {
      const val = document.getElementById(ids.answerInputId)?.value || "";
      onSubmit(val);
    });
  }
  const nextBtn = container.querySelector(".next-question-btn");
  if (nextBtn && typeof opts.onNext === "function") {
    nextBtn.addEventListener("click", opts.onNext);
  }
  if (question.type === "fill" && !answeredResult && typeof window.bindSpeechButtonToInput === "function") {
    window.bindSpeechButtonToInput(ids.micBtnId, ids.answerInputId, false);
  }
  // 填空题回车提交
  const fillInput = document.getElementById(ids.answerInputId);
  if (fillInput && !answeredResult) {
    fillInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        onSubmit(fillInput.value || "");
      }
    });
  }
}

function getQuizAnsweredCount() {
  return Object.keys(state.answerResults).length;
}

function renderQuizDashboard() {
  const dashboard = document.getElementById("quizDashboard");
  if (!dashboard) return;
  const total = state.quizQuestions.length;
  if (!total) {
    dashboard.classList.add("hidden");
    return;
  }
  dashboard.classList.remove("hidden");
  const answered = getQuizAnsweredCount();
  const pct = total ? Math.round((answered / total) * 100) : 0;
  const bar = document.getElementById("quizProgressBar");
  if (bar) bar.style.width = `${pct}%`;
  const answeredEl = document.getElementById("quizAnsweredCount");
  if (answeredEl) answeredEl.textContent = `${answered}/${total}`;
  const correctEl = document.getElementById("quizCorrectCount");
  if (correctEl) correctEl.textContent = String(state.correctCount);
  const wrongEl = document.getElementById("quizWrongCount");
  if (wrongEl) wrongEl.textContent = String(state.wrongCount);
  const rateEl = document.getElementById("quizAccuracy");
  if (rateEl) {
    rateEl.textContent = answered ? `${Math.round((state.correctCount / answered) * 100)}%` : "—";
  }
}

function setQuestionActions(question) {
  const answeredResult = state.answerResults[question.id] || null;
  const isLast = state.quizIndex >= state.quizQuestions.length - 1;
  renderQuestionCard(
    quizBox,
    question,
    {
      progressLabel: `题目 ${state.quizIndex + 1} / ${state.quizQuestions.length}`,
      answerInputId: "answerInput",
      micBtnId: "answerMicBtn",
      fillSubmitBtnId: "fillSubmitBtn",
      feedbackId: "answerFeedback",
    },
    submitAnswer,
    { answeredResult, isLast, onNext: goNextQuestion }
  );
}

function goNextQuestion() {
  if (state.quizIndex < state.quizQuestions.length - 1) {
    state.quizIndex += 1;
    renderCurrentQuestion();
    updateNavButtons();
  } else {
    renderCurrentQuestion();
    updateNavButtons();
  }
}

// 选择题/判断题键盘快捷键
document.addEventListener("keydown", (e) => {
  if (state.currentStep !== "quiz" && state.currentStep !== "analysis") return;
  if (isQuizInputFocused()) return;
  const target = e.target;
  if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA")) return;
  const key = e.key.toUpperCase();
  const inVariant = state.currentStep === "analysis";
  const questions = inVariant ? state.variantQuestions : state.quizQuestions;
  const idx = inVariant ? state.variantIndex : state.quizIndex;
  const results = inVariant ? state.variantAnswerResults : state.answerResults;
  if (!questions.length) return;
  const q = questions[idx];
  if (!q) return;
  // 已答则用 Enter/→ 进入下一题
  if (results[q.id]) {
    if (e.key === "Enter" || e.key === "ArrowRight") {
      e.preventDefault();
      if (inVariant) goNextVariant();
      else goNextQuestion();
    }
    return;
  }
  if (q.type === "choice" && /^[A-D]$/.test(key)) {
    e.preventDefault();
    if (inVariant) submitVariantAnswer(key);
    else submitAnswer(key);
  } else if (q.type === "judge") {
    if (key === "T" || e.key === "1") {
      e.preventDefault();
      if (inVariant) submitVariantAnswer("对");
      else submitAnswer("对");
    } else if (key === "F" || e.key === "0") {
      e.preventDefault();
      if (inVariant) submitVariantAnswer("错");
      else submitAnswer("错");
    }
  }
});

function isQuizInputFocused() {
  const active = document.activeElement;
  return active && active.tagName === "INPUT" && active.id !== "teachInput";
}

// 错因类型 → 图标 + 颜色
const ERROR_TYPE_MAP = {
  "粗心": { icon: "⚠", cls: "err-careless", label: "粗心大意" },
  "知识点": { icon: "📚", cls: "err-knowledge", label: "知识点未掌握" },
  "审题": { icon: "🔍", cls: "err-reading", label: "审题问题" },
  "计算": { icon: "🔢", cls: "err-calc", label: "计算错误" },
  "概念": { icon: "💡", cls: "err-concept", label: "概念混淆" },
};

function matchErrorType(category) {
  const cat = (category || "").trim();
  for (const key of Object.keys(ERROR_TYPE_MAP)) {
    if (cat.includes(key)) return ERROR_TYPE_MAP[key];
  }
  return { icon: "📝", cls: "err-other", label: cat || "其他" };
}

function renderAnalysisReason() {
  if (!analysisReasonBox) return;
  if (!state.analysisSummary && !state.analysisReasons.length) {
    analysisReasonBox.textContent = "暂无分析结果。请点击「生成错题分析」。";
    return;
  }
  const parts = [];
  if (state.analysisSummary) {
    parts.push(`<div class="analysis-summary">${escapeHtml(state.analysisSummary)}</div>`);
  }
  if (state.analysisReasons.length) {
    parts.push('<div class="error-reason-list">');
    state.analysisReasons.forEach((item) => {
      const type = matchErrorType(item.category);
      parts.push(`
        <div class="error-reason-item ${type.cls}">
          <span class="error-reason-icon" aria-hidden="true">${type.icon}</span>
          <div class="error-reason-body">
            <span class="error-reason-tag">${escapeHtml(type.label)}</span>
            <span class="error-reason-detail">${escapeHtml(item.detail || "")}</span>
          </div>
        </div>
      `);
    });
    parts.push('</div>');
  }
  // 错题列表
  if (state.wrongQuestions.length) {
    parts.push('<div class="wrong-question-list">');
    parts.push('<h4 class="wrong-list-title">本次错题</h4>');
    state.wrongQuestions.forEach((q, i) => {
      parts.push(`
        <div class="wrong-question-item">
          <span class="wrong-q-index">${i + 1}</span>
          <div class="wrong-q-body">
            <div class="wrong-q-text">${escapeHtml(q.question_text || "")}</div>
            <div class="wrong-q-meta">
              ${q.knowledge_point ? `<span class="wrong-q-kp">知识点：${escapeHtml(q.knowledge_point)}</span>` : ""}
              <span class="wrong-q-ans">你的答案：<span class="wrong-user-ans">${escapeHtml(q.user_answer || "")}</span></span>
              <span class="wrong-q-ans">正确答案：<span class="wrong-correct-ans">${escapeHtml(q.standard_answer || "")}</span></span>
            </div>
          </div>
        </div>
      `);
    });
    parts.push('</div>');
  }
  analysisReasonBox.innerHTML = parts.join("");
}

function renderCurrentVariant() {
  if (!variantQuizBox || !variantProgress) return;
  if (!state.variantQuestions.length) {
    variantQuizBox.classList.add("hidden");
    variantQuizBox.innerHTML = "";
    variantProgress.textContent = "暂无变式题";
    return;
  }
  variantQuizBox.classList.remove("hidden");
  if (state.variantIndex >= state.variantQuestions.length) {
    variantProgress.textContent = `变式题已全部完成（共 ${state.variantQuestions.length} 题）`;
    variantQuizBox.innerHTML = `
      <div class="content-box">
        变式巩固已完成。可点击「下一步」进入向 AI 讲题。
      </div>
    `;
    updateNavButtons();
    return;
  }
  const q = state.variantQuestions[state.variantIndex];
  variantProgress.textContent = `变式题：第 ${state.variantIndex + 1} / ${state.variantQuestions.length} 题`;
  const answeredResult = state.variantAnswerResults[q.id] || null;
  const isLast = state.variantIndex >= state.variantQuestions.length - 1;
  // 关联错题提示
  const relatedWrong = state.wrongQuestions[state.variantIndex];
  const relatedHint = relatedWrong
    ? `<div class="variant-related">变式自错题 ${state.variantIndex + 1}：${escapeHtml((relatedWrong.question_text || "").slice(0, 40))}${(relatedWrong.question_text || "").length > 40 ? "…" : ""}</div>`
    : "";
  renderQuestionCard(
    variantQuizBox,
    q,
    {
      progressLabel: `变式题 ${state.variantIndex + 1} / ${state.variantQuestions.length}`,
      answerInputId: "variantAnswerInput",
      micBtnId: "variantMicBtn",
      fillSubmitBtnId: "variantFillSubmitBtn",
      feedbackId: "variantAnswerFeedback",
    },
    submitVariantAnswer,
    { answeredResult, isLast, onNext: goNextVariant }
  );
  // 在题目卡片前插入关联提示
  if (relatedHint) {
    variantQuizBox.insertAdjacentHTML("afterbegin", relatedHint);
  }
}

function renderCurrentQuestion() {
  renderQuizDashboard();
  if (!state.quizQuestions.length) {
    quizBox.innerHTML = `<p class="hint-text">生成题目后在此作答。</p>`;
    quizProgress.textContent = "未开始";
    updateNavButtons();
    return;
  }
  if (state.quizIndex >= state.quizQuestions.length) {
    quizProgress.textContent = `已完成，答对 ${state.correctCount} 题，答错 ${state.wrongCount} 题`;
    const nextHint = shouldSkipAnalysis()
      ? "全部答对！可点击「下一步」直接进入向 AI 讲题。"
      : "题目已全部完成。可点击「下一步」进行错题分析。";
    quizBox.innerHTML = `<div class="content-box">${nextHint}</div>`;
    updateNavButtons();
    return;
  }
  const q = state.quizQuestions[state.quizIndex];
  quizProgress.textContent = `进行中：第 ${state.quizIndex + 1} / ${state.quizQuestions.length} 题`;
  setQuestionActions(q);
}

async function submitAnswer(answerText) {
  const currentQuestion = state.quizQuestions[state.quizIndex];
  if (state.answerResults[currentQuestion.id]) {
    showBanner("本题已作答，请点击「下一题」", "error");
    return;
  }
  const normalized = (answerText || "").trim();
  if (!normalized) {
    showBanner("答案不能为空", "error");
    return;
  }
  try {
    const data = await apiPost(
      "/api/quiz/answer",
      {
        client_id: state.clientId,
        question_id: currentQuestion.id,
        answer_text: normalized,
      },
      "正在判题…"
    );
    state.answerResults[currentQuestion.id] = data;
    state.correctCount = data.stats.correct_count;
    state.wrongCount = data.stats.wrong_count;
    setTeachUnlock(data.teach_unlocked);
    renderQuizDashboard();
    setQuestionActions(currentQuestion);
    window.maybeAutoSpeak?.(
      `${data.correct ? "很好，回答正确。" : "继续加油。"}${data.feedback}`
    );
    persistState();
  } catch (err) {
    showBanner(err.message || "提交答案失败", "error");
  }
}

async function submitVariantAnswer(answerText) {
  const currentQuestion = state.variantQuestions[state.variantIndex];
  if (state.variantAnswerResults[currentQuestion.id]) {
    showBanner("本题已作答，请点击「下一题」", "error");
    return;
  }
  const normalized = (answerText || "").trim();
  if (!normalized) {
    showBanner("答案不能为空", "error");
    return;
  }
  try {
    const data = await apiPost(
      "/api/variants/answer",
      {
        client_id: state.clientId,
        question_id: currentQuestion.id,
        answer_text: normalized,
      },
      "正在判题…"
    );
    state.variantAnswerResults[currentQuestion.id] = data;
    renderCurrentVariant();
    window.maybeAutoSpeak?.(
      `${data.correct ? "很好，回答正确。" : "继续加油。"}${data.feedback}`
    );
    persistState();
  } catch (err) {
    showBanner(err.message || "提交变式题答案失败", "error");
  }
}

function goNextVariant() {
  if (state.variantIndex < state.variantQuestions.length - 1) {
    state.variantIndex += 1;
    renderCurrentVariant();
    updateNavButtons();
  } else {
    renderCurrentVariant();
    updateNavButtons();
  }
}

document.querySelectorAll(".grade-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    selectGrade(btn.dataset.grade || "");
  });
});

document.querySelectorAll(".subject-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    selectSubject(btn.dataset.subject || "");
  });
});

stepper?.querySelectorAll(".stepper-item").forEach((btn) => {
  btn.addEventListener("click", () => {
    const step = btn.dataset.step;
    if (btn.disabled) return;
    navigateTo(step);
  });
});

navPrevBtn?.addEventListener("click", goPrev);
navNextBtn?.addEventListener("click", goNext);

window.addEventListener("popstate", () => {
  const step = parseRoute();
  showPage(step);
});

dropZone.addEventListener("dragover", (e) => {
  e.preventDefault();
  dropZone.classList.add("dragover");
});
dropZone.addEventListener("dragleave", () => {
  dropZone.classList.remove("dragover");
});
dropZone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropZone.classList.remove("dragover");
  handleFiles(e.dataTransfer.files);
});
fileInput.addEventListener("change", () => {
  handleFiles(fileInput.files);
  fileInput.value = "";
});

startSessionBtn.addEventListener("click", async () => {
  if (!state.grade || !state.subject) {
    showBanner("请先选择年级与科目", "error");
    navigateTo("grade");
    return;
  }
  if (!canUseApi()) {
    window.openSettingsModal?.();
    showBanner("请先填写 API Key 与模型 ID", "error");
    return;
  }
  const uploading = state.files.some((f) => f.uploading);
  if (uploading) {
    showBanner("请等待 PDF 上传完成", "error");
    return;
  }
  const fileIds = getUploadedFileIds();
  if (!fileIds.length) {
    showBanner("请先上传至少一个 PDF", "error");
    return;
  }
  try {
    const data = await apiPost(
      "/api/session/start",
      {
        grade: state.grade,
        subject: state.subject,
        file_ids: fileIds,
        client_id: state.clientId,
      },
      "正在创建学习会话…"
    );
    state.clientId = data.client_id;
    localStorage.setItem("doubaochat_client_id", state.clientId);
    state.sessionReady = true;
    resetTeachState();
    setTeachUnlock(false);
    updateMaxReached("upload");
    updateMaxReached("lesson");
    persistState();
    updateNavButtons();
    showBanner("学习会话已创建", "ok", 2000);
    navigateTo("lesson");
  } catch (err) {
    showBanner(err.message || "创建会话失败", "error");
  }
});

// 讲解文本结构化渲染：标题/小标题/段落，句子用 span 包裹以支持 karaoke 高亮
function splitSentences(text) {
  return (text || "")
    .split(/(?<=[。！？；\n])/)
    .map((s) => s.trim())
    .filter(Boolean);
}

function renderLessonText(text) {
  if (!text || !text.trim()) {
    lessonBox.textContent = "尚未生成讲解内容。";
    return;
  }
  const lines = text.split(/\n/).map((l) => l.trim()).filter(Boolean);
  const html = [];
  let sentenceIndex = 0;
  lines.forEach((line, lineIdx) => {
    const isHeading = lineIdx === 0 || /^(\d+[.、)）]|[一二三四五六七八九十]+[、）:：])/.test(line) || (line.length <= 16 && !/[。！？；]$/.test(line));
    if (isHeading) {
      html.push(`<h3 class="lesson-heading">${escapeHtml(line)}</h3>`);
    } else {
      const sentences = splitSentences(line);
      const spans = sentences
        .map((s) => {
          const idx = sentenceIndex++;
          return `<span class="lesson-sentence" data-sentence="${idx}">${escapeHtml(s)}</span>`;
        })
        .join("");
      html.push(`<p class="lesson-paragraph">${spans}</p>`);
    }
  });
  lessonBox.innerHTML = html.join("");
}

function setLessonHighlight(sentenceIndex) {
  lessonBox.querySelectorAll(".lesson-sentence").forEach((el) => {
    el.classList.toggle("is-active", Number(el.dataset.sentence) === sentenceIndex);
  });
  const active = lessonBox.querySelector(".lesson-sentence.is-active");
  if (active) {
    active.scrollIntoView({ block: "center", behavior: "smooth" });
  }
}

function clearLessonHighlight() {
  lessonBox.querySelectorAll(".lesson-sentence.is-active").forEach((el) =>
    el.classList.remove("is-active")
  );
}

explainBtn.addEventListener("click", async () => {
  if (!state.sessionReady) {
    showBanner("请先完成上传并开始学习", "error");
    navigateTo("upload");
    return;
  }
  lessonBox.textContent = "讲解生成中...";
  try {
    const data = await apiPost(
      "/api/lesson/explain",
      { client_id: state.clientId },
      "正在生成讲解…"
    );
    state.lessonText = data.lesson_text;
    state.lessonKnowledgePoints = data.knowledge_points || [];
    renderLessonText(data.lesson_text);
    updateMaxReached("lesson");
    updateMaxReached("quiz");
    persistState();
    updateNavButtons();
    window.maybeAutoSpeak?.(data.lesson_text);
  } catch (err) {
    lessonBox.textContent = "讲解生成失败";
    showBanner(err.message || "生成讲解失败", "error");
  }
});

const pauseLessonBtn = document.getElementById("pauseLessonBtn");
const stopLessonBtn = document.getElementById("stopLessonBtn");
const lessonPlayStatus = document.getElementById("lessonPlayStatus");

function setLessonPlaying(playing) {
  playLessonBtn.classList.toggle("hidden", playing);
  pauseLessonBtn.classList.remove("hidden");
  stopLessonBtn.classList.remove("hidden");
  pauseLessonBtn.textContent = playing ? "暂停" : "继续";
}

function setLessonStopped() {
  playLessonBtn.classList.remove("hidden");
  pauseLessonBtn.classList.add("hidden");
  stopLessonBtn.classList.add("hidden");
  if (lessonPlayStatus) lessonPlayStatus.textContent = "";
  clearLessonHighlight();
}

playLessonBtn.addEventListener("click", () => {
  if (!state.lessonText) {
    showBanner("请先生成讲解", "error");
    return;
  }
  window.primeAudioOnUserGesture?.();
  setLessonPlaying(true);
  window.playTtsKaraoke?.(
    state.lessonText,
    lessonBox,
    {
      onSentence: (i) => setLessonHighlight(i),
      onStatus: (msg) => {
        if (lessonPlayStatus) lessonPlayStatus.textContent = msg;
      },
      onEnd: () => setLessonStopped(),
    }
  );
});

pauseLessonBtn?.addEventListener("click", () => {
  const paused = window.toggleTtsPause?.();
  if (paused === true) {
    pauseLessonBtn.textContent = "继续";
    if (lessonPlayStatus) lessonPlayStatus.textContent = "已暂停";
  } else if (paused === false) {
    pauseLessonBtn.textContent = "暂停";
  }
});

stopLessonBtn?.addEventListener("click", () => {
  window.stopTts?.();
  setLessonStopped();
});

generateQuizBtn.addEventListener("click", async () => {
  if (!state.lessonText) {
    showBanner("请先生成讲解内容", "error");
    navigateTo("lesson");
    return;
  }
  try {
    const data = await apiPost(
      "/api/quiz/generate",
      {
        client_id: state.clientId,
        count: 5,
      },
      "正在生成练习题…"
    );
    state.quizQuestions = data.questions || [];
    state.quizIndex = 0;
    state.answerResults = {};
    state.correctCount = 0;
    state.wrongCount = 0;
    state.variantQuestions = [];
    state.variantIndex = 0;
    state.variantAnswerResults = {};
    state.analysisSummary = "";
    state.analysisDone = false;
    setTeachUnlock(false);
    if (analysisReasonBox) {
      analysisReasonBox.textContent = "暂无分析结果。";
    }
    if (variantQuizBox) {
      variantQuizBox.classList.add("hidden");
      variantQuizBox.innerHTML = "";
    }
    if (variantProgress) {
      variantProgress.textContent = "变式题未开始";
    }
    updateMaxReached("quiz");
    updateMaxReached("analysis");
    persistState();
    renderCurrentQuestion();
    updateNavButtons();
  } catch (err) {
    showBanner(err.message || "生成题目失败", "error");
  }
});

analyzeBtn.addEventListener("click", async () => {
  if (!state.quizQuestions.length) {
    showBanner("请先生成练习题", "error");
    navigateTo("quiz");
    return;
  }
  if (shouldSkipAnalysis()) {
    skipAnalysisToTeach("全部答对，无需错题分析");
    return;
  }
  if (analysisReasonBox) {
    analysisReasonBox.textContent = "分析中...";
  }
  if (variantQuizBox) {
    variantQuizBox.classList.add("hidden");
    variantQuizBox.innerHTML = "";
  }
  try {
    const data = await apiPost(
      "/api/analysis/wrong",
      { client_id: state.clientId },
      "正在分析错题…"
    );
    if (data.skipped) {
      skipAnalysisToTeach(data.summary || "本轮没有错题，已跳过错题分析");
      return;
    }
    state.analysisSummary = data.summary || "已完成错题分析。";
    state.analysisReasons = data.reasons || [];
    // 收集错题信息用于关联展示
    state.wrongQuestions = state.quizQuestions
      .filter((q) => state.answerResults[q.id] && !state.answerResults[q.id].correct)
      .map((q) => ({
        id: q.id,
        question_text: q.question_text,
        knowledge_point: q.knowledge_point || "",
        user_answer: state.answerResults[q.id].user_answer,
        standard_answer: q.answer,
      }));
    state.analysisDone = true;
    state.variantQuestions = data.variants || [];
    state.variantIndex = 0;
    state.variantAnswerResults = {};
    renderAnalysisReason();
    renderCurrentVariant();
    updateMaxReached("analysis");
    updateMaxReached("teach");
    persistState();
    updateNavButtons();
    window.maybeAutoSpeak?.(data.summary || "错题分析已完成，请完成变式题。");
  } catch (err) {
    if (analysisReasonBox) {
      analysisReasonBox.textContent = "分析失败";
    }
    showBanner(err.message || "错题分析失败", "error");
  }
});

inviteTeachBtn.addEventListener("click", async () => {
  if (!state.sessionReady) {
    showBanner("请先创建学习会话", "error");
    return;
  }
  try {
    const data = await apiPost(
      "/api/teach/invite",
      { client_id: state.clientId },
      "正在获取邀请…"
    );
    if (!data.teach_unlocked) {
      showBanner(data.invite_text || "尚未解锁向 AI 讲题", "error");
      setTeachUnlock(false);
      return;
    }
    state.teachInvite = data.invite_text || "";
    setTeachUnlock(true);
    if (data.turns) {
      state.teachTurns = data.turns;
    } else if (data.invite_text) {
      state.teachTurns = [{ role: "ai", content: data.invite_text, round: null }];
    }
    if (typeof data.teach_student_rounds === "number") {
      state.teachStudentRounds = data.teach_student_rounds;
    }
    if (typeof data.learning_completed === "boolean") {
      state.learningCompleted = data.learning_completed;
    }
    renderTeachChat();
    updateTeachRoundUI();
    persistState();
    window.maybeAutoSpeak?.(data.invite_text);
  } catch (err) {
    showBanner(err.message || "获取邀请失败", "error");
  }
});

teachSubmitBtn.addEventListener("click", async () => {
  if (!state.teachUnlocked) {
    showBanner("累计答对 3 题后可解锁向 AI 讲题", "error");
    return;
  }
  if (state.learningCompleted || state.teachStudentRounds >= MAX_TEACH_STUDENT_ROUNDS) {
    showBanner("互讲已满 2 轮，本次学习已结束", "error");
    return;
  }
  const explainText = (teachInput.value || "").trim();
  if (!explainText) {
    showBanner("请先输入或语音讲解后再提交", "error");
    return;
  }
  try {
    const data = await apiPost(
      "/api/teach/evaluate",
      {
        client_id: state.clientId,
        explanation_text: explainText,
      },
      "正在评估你的讲解…"
    );
    if (data.turns) {
      state.teachTurns = data.turns;
    }
    if (typeof data.teach_student_rounds === "number") {
      state.teachStudentRounds = data.teach_student_rounds;
    }
    if (typeof data.learning_completed === "boolean") {
      state.learningCompleted = data.learning_completed;
    } else if (data.completed) {
      state.learningCompleted = true;
    }
    teachInput.value = "";
    renderTeachChat();
    updateTeachRoundUI();
    persistState();
    const lastAi = [...state.teachTurns].reverse().find((t) => t.role === "ai");
    window.maybeAutoSpeak?.(lastAi?.content || data.feedback);
    if (data.completed || state.learningCompleted) {
      showLearningCompleteModal();
    }
  } catch (err) {
    showBanner(err.message || "讲解评估失败", "error");
  }
});

learningCompleteClose?.addEventListener("click", hideLearningCompleteModal);
learningCompleteModal?.addEventListener("click", (e) => {
  if (e.target.id === "learningCompleteModal") hideLearningCompleteModal();
});

function initApp() {
  restoreState();
  if (state.grade || state.subject) {
    syncGradeSubjectButtons();
    renderGradeSummary();
  }
  setTeachUnlock(state.teachUnlocked);
  renderTeachChat();
  updateTeachRoundUI();
  renderFileList();
  if (state.quizQuestions.length) {
    renderCurrentQuestion();
  }
  if (state.analysisDone) {
    renderAnalysisReason();
    if (state.variantQuestions.length) {
      renderCurrentVariant();
    }
  }
  window.isServerConfigured = () => state.serverConfigured;
  const initialStep = parseRoute();
  if (!location.hash) {
    navigateTo(state.currentStep || initialStep || "grade", { replace: true });
  } else {
    showPage(initialStep);
    history.replaceState({ step: initialStep }, "", `#/${initialStep}`);
  }
  checkHealth();
}

initApp();
