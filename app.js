const state = {
  questions: [],
  students: [],
  results: [],
  activeStudent: "",
  ocrText: "",
  lastOcrTarget: "",
  ocrMeta: null,
  llmMeta: null,
  referenceOcrText: "",
  referenceOcrMeta: null,
  referenceLlmMeta: null,
  referenceTimings: [],
  submissionOcrText: "",
  submissionOcrMeta: null,
  submissionLlmMeta: null,
  submissionTimings: [],
  submissionEvidenceUrl: "",
  submissionEvidenceName: "",
  submissionEvidenceType: "",
  referenceUploaded: false,
  submissionUploaded: false,
  referenceUploading: false,
  submissionUploading: false,
  referenceProgress: null,
  submissionProgress: null,
  referenceConfirmed: false,
  expandedQuestionIds: new Set(),
  expandedEvidenceIds: new Set(),
  scoreAuditOpen: false,
  typeScoreDrafts: {},
  expectedTotalScore: "",
  ocrSelectionStart: 0,
  ocrSelectionEnd: 0,
};

const autoTypes = new Set(["choice", "judge", "fill", "single", "选择题", "判断题", "填空题", "单一答案计算题"]);
const assistTypes = new Set(["essay", "reading", "history", "politics", "proof", "math_process", "calculation", "geometry", "calculus", "derivative", "integral", "limit", "subjective", "语文作文", "阅读理解", "历史材料题", "政治论述题", "数学证明题", "数学计算大题", "解答题", "几何题", "导数题", "积分题", "极限题", "微分题"]);
const manualTypes = new Set(["drawing", "oral", "experiment", "project", "作图题", "口语表达", "实验操作题", "开放项目题"]);

const exampleQuestions = [
  {
    id: "q1",
    subject: "数学",
    type: "choice",
    title: "下列计算正确的是？",
    answer: "B",
    score: 2,
    knowledge: "分数乘法",
  },
  {
    id: "q2",
    subject: "数学",
    type: "fill",
    title: "7 × 6 = ____",
    answer: "42",
    score: 2,
    knowledge: "乘法计算",
  },
  {
    id: "q3",
    subject: "语文",
    type: "essay",
    title: "那一刻，我长大了",
    score: 50,
    keywords: ["长大", "责任", "感受", "那一刻"],
    rubric: ["中心明确", "事例具体", "情感真实", "结尾点题"],
  },
  {
    id: "q4",
    subject: "历史",
    type: "history",
    title: "结合材料分析工业革命的影响",
    score: 10,
    keywords: ["生产力", "城市化", "工人阶级", "社会问题"],
    rubric: ["生产力提升", "城市化发展", "工人阶级形成", "社会矛盾"],
  },
  {
    id: "q5",
    subject: "数学",
    type: "proof",
    title: "证明两个三角形相似",
    score: 8,
    keywords: ["角相等", "相似", "对应", "比例"],
    rubric: ["写出已知条件", "证明角相等", "使用相似判定", "结论完整"],
  },
];

const exampleStudents = [
  {
    student: "李同学",
    answers: {
      q1: "B",
      q2: "36",
      q3: "那天妈妈发烧了，我给她倒水、找药，还做了简单的饭。那一刻我明白了责任，也觉得自己长大了。",
      q4: "工业革命提高生产力，也推动城市发展，让人们生活方式变化。",
      q5: "因为两个角相等，所以两个三角形相似，对应边成比例。",
    },
  },
  {
    student: "王同学",
    answers: {
      q1: "A",
      q2: "42",
      q3: "我写了一次比赛，虽然输了，但我有很多感受。以后我要继续努力。",
      q4: "工业革命让机器变多，工厂出现，工人阶级形成，但也带来社会问题。",
      q5: "先证明一个角相等，再证明另一个角相等，根据两角相等可得三角形相似。",
    },
  },
];

function byId(id) {
  return document.getElementById(id);
}

function showToast(message) {
  const toast = byId("toast");
  toast.textContent = message;
  toast.classList.add("show");
  window.setTimeout(() => toast.classList.remove("show"), 2400);
}

function setUploadState(target, uploading) {
  if (target === "reference") {
    state.referenceUploading = uploading;
    if (!uploading) state.referenceProgress = null;
  } else {
    state.submissionUploading = uploading;
    if (!uploading) state.submissionProgress = null;
  }
  renderStatuses();
}

function updateExtractProgress(target, progress) {
  if (!progress) return;
  if (target === "reference") {
    state.referenceProgress = progress;
  } else {
    state.submissionProgress = progress;
  }
  renderStatuses();
}

function normalize(value) {
  return normalizeMathForCompare(value)
    .trim()
    .replace(/\s+/g, "")
    .replace(/[。！？；，、,.!?;:：]/g, "")
    .toLowerCase();
}

function normalizeMathForCompare(value) {
  return String(value ?? "")
    .replace(/\\times/g, "×")
    .replace(/\\cdot/g, "·")
    .replace(/\\left\s*/g, "")
    .replace(/\\right\s*/g, "")
    .replace(/\\leq?/g, "≤")
    .replace(/\\geq?/g, "≥")
    .replace(/\\neq/g, "≠")
    .replace(/\\infty/g, "∞")
    .replace(/\\to/g, "→")
    .replace(/\\lim/g, "lim")
    .replace(/\\ln/g, "ln")
    .replace(/\\sin/g, "sin")
    .replace(/\\cos/g, "cos")
    .replace(/\\tan/g, "tan")
    .replace(/\\int/g, "∫")
    .replace(/\\partial/g, "∂")
    .replace(/\\Delta/g, "Δ")
    .replace(/10([⁰¹²³⁴⁵⁶⁷⁸⁹]+)/g, (_, power) => `10^${normalizeSuperscriptDigits(power)}`)
    .replace(/[×xX]\s*10\s*\^\s*([+-]?\d+)/g, "×10^$1")
    .replace(/\\frac\s*\{([^}]*)\}\s*\{([^}]*)\}/g, "$1/$2")
    .replace(/\(([-+]?\d+(?:\.\d+)?)\)\s*\/\s*\(([-+]?\d+(?:\.\d+)?)\)/g, "$1/$2")
    .replace(/\\sqrt\s*\{([^}]*)\}/g, "√($1)")
    .replace(/\^2\b/g, "²")
    .replace(/\^3\b/g, "³");
}

function normalizeSuperscriptDigits(value) {
  const map = {
    "⁰": "0",
    "¹": "1",
    "²": "2",
    "³": "3",
    "⁴": "4",
    "⁵": "5",
    "⁶": "6",
    "⁷": "7",
    "⁸": "8",
    "⁹": "9",
  };
  return String(value ?? "").replace(/[⁰¹²³⁴⁵⁶⁷⁸⁹]/g, (char) => map[char] || char);
}

function toSuperscriptDigits(value) {
  const map = {
    "0": "⁰",
    "1": "¹",
    "2": "²",
    "3": "³",
    "4": "⁴",
    "5": "⁵",
    "6": "⁶",
    "7": "⁷",
    "8": "⁸",
    "9": "⁹",
    "+": "⁺",
    "-": "⁻",
  };
  return String(value ?? "").replace(/[0-9+-]/g, (char) => map[char] || char);
}

function parseDecimalInput(value) {
  const normalized = String(value ?? "")
    .trim()
    .replace(/[，,]/g, ".")
    .replace(/[^\d.+-]/g, "");
  if (!normalized || normalized === "." || normalized === "+" || normalized === "-") return NaN;
  return Number(normalized);
}

function normalizeQuestionNo(value) {
  const text = String(value ?? "").trim();
  const chineseNumbers = {
    一: "1",
    二: "2",
    三: "3",
    四: "4",
    五: "5",
    六: "6",
    七: "7",
    八: "8",
    九: "9",
    十: "10",
  };
  if (chineseNumbers[text]) return chineseNumbers[text];
  return /^\d+$/.test(text) ? String(Number(text)) : text;
}

function splitList(value) {
  if (Array.isArray(value)) return value.map(String).map((item) => item.trim()).filter(Boolean);
  return String(value ?? "")
    .split(/[|/;,，、；\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function parseCSV(text) {
  const rows = [];
  let row = [];
  let cell = "";
  let quoted = false;

  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    const next = text[index + 1];
    if (char === '"' && quoted && next === '"') {
      cell += '"';
      index += 1;
    } else if (char === '"') {
      quoted = !quoted;
    } else if (char === "," && !quoted) {
      row.push(cell);
      cell = "";
    } else if ((char === "\n" || char === "\r") && !quoted) {
      if (char === "\r" && next === "\n") index += 1;
      row.push(cell);
      if (row.some((item) => item.trim())) rows.push(row);
      row = [];
      cell = "";
    } else {
      cell += char;
    }
  }

  row.push(cell);
  if (row.some((item) => item.trim())) rows.push(row);
  return rows;
}

function rowsToObjects(rows) {
  if (!rows.length) return [];
  const headers = rows[0].map((item) => item.trim());
  return rows.slice(1).map((row) => {
    const obj = {};
    headers.forEach((header, index) => {
      obj[header] = row[index] ?? "";
    });
    return obj;
  });
}

function parseJSON(text) {
  const parsed = JSON.parse(text);
  return Array.isArray(parsed) ? parsed : parsed.items || parsed.questions || parsed.students || [];
}

function parseReferenceText(text) {
  const tableItems = parseAnswerTableText(text);
  if (tableItems.length) return tableItems;
  return text
    .split(/\n+/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line, index) => {
      const parts = {};
      line.split("|").forEach((segment) => {
        const [key, ...rest] = segment.split(/[:：]/);
        if (!key || !rest.length) return;
        parts[key.trim()] = rest.join(":").trim();
      });
      return {
        id: parts.id || parts.题号 || parts.question || `q${index + 1}`,
        subject: parts.subject || parts.科目 || "",
        type: parts.type || parts.题型 || "",
        title: parts.title || parts.题目 || "",
        answer: parts.answer || parts.答案 || "",
        score: Number(parts.score || parts.分值 || 0) || 0,
        keywords: splitList(parts.keywords || parts.关键词),
        rubric: splitList(parts.rubric || parts.评分点),
      };
    });
}

function parseAnswerTableText(text) {
  const lines = String(text || "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .filter((line) => !line.startsWith("==="));
  const joined = lines.join(" ");
  const sections = inferQuestionSections(joined);
  const pairMatches = [...joined.matchAll(/(?:第\s*)?([0-9]{1,3})\s*(?:题)?[\.\．\、\):：-]?\s*(?:答案)?\s*[:：]?\s*([A-Da-d对错√×真假]|-?\d+(?:\.\d+)?|[\u4e00-\u9fa5]{1,8})(?=\s|$|[;；,，、])/g)];
  const pairs = [];
  const seen = new Set();
  pairMatches.forEach((match) => {
    const no = normalizeQuestionNo(match[1]);
    const section = inferSectionForNo(no, sections);
    const answer = match[2].trim();
    if (seen.has(no)) return;
    seen.add(no);
    const isChoice = section?.type === "choice" || (!section && /^[A-Da-d]$/.test(answer));
    pairs.push({
      id: `q${no}`,
      type: isChoice ? "choice" : "fill",
      title: `第 ${no} 题`,
      answer: /^[A-Da-d]$/.test(answer) ? answer.toUpperCase() : answer,
      score: section?.score || (isChoice ? 4 : 6),
    });
  });
  const lineItems = parseMathAnswerLines(lines);
  const existing = new Set(pairs.map((item) => item.id));
  lineItems.forEach((item) => {
    if (!existing.has(item.id)) pairs.push(item);
  });
  return pairs;
}

function parseMathAnswerLines(lines) {
  const items = [];
  const seen = new Set();
  lines.forEach((line) => {
    const match = line.match(/^(?:第\s*)?([0-9]{1,3})(?:\s*[（(]([0-9一二三四五六七八九十]+)[）)])?\s*(?:题)?[\.\．\、\):：-]?\s*(?:答案)?\s*[:：]?\s*(.+)$/);
    if (!match) return;
    const value = match[3].trim();
    if (!value || /^(选择题|填空题|解答题|计算题|证明题)/.test(value)) return;
    const no = normalizeQuestionNo(match[1]);
    const subNo = match[2] ? `_${normalizeQuestionNo(match[2])}` : "";
    const id = `q${no}${subNo}`;
    if (seen.has(id)) return;
    seen.add(id);
    const isChoice = /^[A-Da-d]$/.test(value);
    const isMath = /[=×÷/^²³√|≤≥≈π{}[\]]/.test(value) || /\d+\s*[+\-*/]\s*\d+/.test(value);
    if (!subNo && !isMath) return;
    items.push({
      id,
      type: isChoice ? "choice" : isMath ? "calculation" : "fill",
      title: `第 ${no}${subNo ? `(${subNo.slice(1)})` : ""} 题`,
      answer: isChoice ? value.toUpperCase() : value,
      score: 0,
    });
  });
  return items;
}

function inferQuestionSections(text) {
  const sections = [];
  const compact = String(text || "").replace(/\s+/g, "");
  const choice = compact.match(/选择题[（(]?每小题(\d+)分[，,、]?共(\d+)分[）)]?/);
  const fill = compact.match(/填空题[（(]?每小题(\d+)分[，,、]?共(\d+)分[）)]?/);
  let cursor = 1;
  if (choice) {
    const score = Number(choice[1]);
    const count = Math.max(1, Math.round(Number(choice[2]) / score));
    sections.push({ type: "choice", start: cursor, end: cursor + count - 1, score });
    cursor += count;
  }
  if (fill) {
    const score = Number(fill[1]);
    const count = Math.max(1, Math.round(Number(fill[2]) / score));
    sections.push({ type: "fill", start: cursor, end: cursor + count - 1, score });
  }
  return sections;
}

function inferSectionForNo(no, sections) {
  const value = Number(no);
  if (!Number.isFinite(value)) return null;
  return sections.find((section) => value >= section.start && value <= section.end) || null;
}

function normalizeQuestion(raw, index) {
  const title = String(raw.title || raw.题目 || raw.stem || "").trim();
  const answer = raw.answer ?? raw.答案 ?? raw.standard_answer ?? "";
  const rubric = splitList(raw.rubric || raw.评分点 || raw.criteria || raw.采分点);
  const inferredRubric = rubric.length ? rubric : extractExplicitRubricFromAnswer(answer);
  const scoreContext = [title, answer, inferredRubric.join("；")].join(" ");
  const authoritativeScore = inferScoreFromText(scoreContext, true);
  const score = authoritativeScore || Number(raw.score || raw.分值 || raw.points || 0) || inferScoreFromText(scoreContext);
  return {
    id: String(raw.id || raw.题号 || raw.question_id || raw.question || `q${index + 1}`).trim(),
    subject: String(raw.subject || raw.科目 || "").trim(),
    type: String(raw.type || raw.题型 || "").trim(),
    title,
    answer,
    score,
    keywords: splitList(raw.keywords || raw.关键词 || raw.knowledge || raw.知识点),
    rubric: inferredRubric,
    visualNotes: String(raw.visual_notes || raw.visualNotes || raw.图形说明 || raw.图形关系 || "").trim(),
  };
}

function inferScoreFromText(text, authoritative = false) {
  const compact = String(text || "").replace(/\s+/g, "");
  const patterns = [/本小题满分(\d+(?:\.\d+)?)分/, /小题满分(\d+(?:\.\d+)?)分/, /满分(\d+(?:\.\d+)?)分/, /[（(](\d+(?:\.\d+)?)分[）)]/];
  if (!authoritative) patterns.push(/共(\d+(?:\.\d+)?)分/);
  const values = [];
  for (const pattern of patterns) {
    for (const match of compact.matchAll(new RegExp(pattern.source, "g"))) {
      const value = Number(match[1]);
      if (value > 0 && value <= 100) values.push(value);
    }
  }
  return values.length ? Math.max(...values) : 0;
}

function extractExplicitRubricFromAnswer(answer) {
  const text = String(answer || "").trim();
  if (!text) return [];
  if (/^[A-Da-d对错√×真假]$/.test(text) || /^-?\d+(?:\.\d+)?$/.test(text)) return [];
  const scored = [...text.matchAll(/([^。；;\n]{2,80}?)[（(](\d+(?:\.\d+)?)分[）)]/g)]
    .map((match) => `${match[1].trim()}（${match[2]}分）`)
    .filter(Boolean);
  if (scored.length) return scored.slice(0, 6);
  return [];
}

function isGenericQuestionTitle(title) {
  const text = String(title || "").trim();
  return !text || /^第\s*[0-9一二三四五六七八九十]+(?:\([^)]+\))?\s*题$/.test(text);
}

function needsQuestionStructure() {
  if (!state.questions.length) return true;
  const usefulCount = state.questions.filter((question) => !isGenericQuestionTitle(question.title) || question.visualNotes).length;
  return usefulCount < Math.max(1, Math.ceil(state.questions.length * 0.3));
}

function mergeQuestionStructures(baseQuestions, supplementalQuestions) {
  const byId = new Map(baseQuestions.map((question) => [question.id, { ...question }]));
  supplementalQuestions.forEach((question) => {
    if (!question.id) return;
    const existing = byId.get(question.id);
    if (!existing) {
      byId.set(question.id, question);
      return;
    }
    byId.set(question.id, {
      ...existing,
      subject: existing.subject || question.subject,
      type: existing.type || question.type,
      title: isGenericQuestionTitle(existing.title) ? question.title || existing.title : existing.title,
      answer: existing.answer || question.answer,
      score: existing.score || question.score,
      keywords: existing.keywords?.length ? existing.keywords : question.keywords,
      rubric: existing.rubric?.length ? existing.rubric : question.rubric,
      visualNotes: existing.visualNotes || question.visualNotes,
    });
  });
  return [...byId.values()];
}

function parseReference(text, fileName = "") {
  const trimmed = text.trim();
  let rawItems;
  if (!trimmed) return [];
  if (trimmed.startsWith("[") || trimmed.startsWith("{")) {
    rawItems = parseJSON(trimmed);
  } else if (fileName.endsWith(".csv") || trimmed.split(/\r?\n/)[0].includes(",")) {
    rawItems = rowsToObjects(parseCSV(trimmed));
  } else {
    rawItems = parseReferenceText(trimmed);
  }
  return rawItems.map(normalizeQuestion).filter((item) => item.id);
}

function isOcrFile(file) {
  return /\.(png|jpg|jpeg|webp|pdf|zip)$/i.test(file?.name || "");
}

async function extractFile(file, target = "reference", options = {}) {
  const candidates = buildApiCandidates("/api/extract");
  const errors = [];
  updateExtractProgress(target, { percent: 1, stage: "uploading", message: "正在上传文件..." });
  for (const endpoint of candidates) {
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("target", target);
      form.append("async", "true");
      if (options.needQuestions) form.append("need_questions", "true");
      const response = await fetch(endpoint, {
        method: "POST",
        body: form,
      });
      const payload = await response.json().catch(() => ({}));
      if (response.ok && payload.job_id && payload.status === "processing") {
        updateExtractProgress(target, payload.progress || { percent: 3, stage: "queued", message: payload.message || "后台解析已开始。" });
        return await pollExtractJob(endpoint, payload.job_id, target);
      }
      if (response.ok && payload.ok) {
        return payload;
      }
      errors.push(`${endpoint}: ${payload.error || response.status}`);
    } catch (error) {
      errors.push(`${endpoint}: ${error.message}`);
    }
  }
  throw new Error(`图片/PDF/ZIP 解析服务连接失败。请确认已运行 python3 server.py，并使用终端打印的地址打开页面。详情：${errors[0] || "未知错误"}`);
}

function wait(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function pollExtractJob(endpoint, jobId, target = "reference") {
  const statusUrl = new URL(endpoint);
  statusUrl.pathname = "/api/extract-status";
  statusUrl.search = new URLSearchParams({ job_id: jobId }).toString();
  for (let attempt = 0; attempt < 600; attempt += 1) {
    await wait(attempt < 2 ? 1000 : 2000);
    const response = await fetch(statusUrl.toString(), { method: "GET" });
    const payload = await response.json().catch(() => ({}));
    if (response.ok && payload.ok && payload.status === "processing") {
      updateExtractProgress(target, payload.progress || { percent: 5, stage: "processing", message: "正在解析..." });
      continue;
    }
    if (response.ok && payload.ok) {
      updateExtractProgress(target, { percent: 100, stage: "done", message: "解析完成。" });
      return payload;
    }
    throw new Error(payload.error || `解析任务失败：${response.status}`);
  }
  throw new Error("解析任务仍在运行，请稍后重试或减少 PDF/ZIP 页数。");
}

async function structureOcrText(text, target = "reference") {
  const candidates = buildApiCandidates("/api/structure-text");
  const errors = [];
  for (const endpoint of candidates) {
    try {
      const response = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, target }),
      });
      const payload = await response.json().catch(() => ({}));
      if (response.ok && payload.ok) return payload;
      errors.push(`${endpoint}: ${payload.error || response.status}`);
    } catch (error) {
      errors.push(`${endpoint}: ${error.message}`);
    }
  }
  throw new Error(`大模型重新解析失败。详情：${errors[0] || "未知错误"}`);
}

function buildApiCandidates(path) {
  const origins = new Set();
  if (window.location.origin && window.location.origin !== "null") {
    origins.add(window.location.origin);
  }
  for (let port = 8011; port <= 8030; port += 1) {
    origins.add(`http://127.0.0.1:${port}`);
    origins.add(`http://localhost:${port}`);
  }
  return [...origins].map((origin) => `${origin}${path}`);
}

function parseStudentText(text) {
  const blocks = text.split(/\n\s*\n/).map((block) => block.trim()).filter(Boolean);
  return blocks.map((block, index) => {
    const lines = block.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
    let student = `学生${index + 1}`;
    const answers = {};
    lines.forEach((line) => {
      const [key, ...rest] = line.split(/[:：]/);
      if (!key || !rest.length) return;
      const value = rest.join(":").trim();
      if (key.trim() === "学生" || key.trim().toLowerCase() === "student") {
        student = value;
      } else {
        answers[key.trim()] = value;
      }
    });
    return { student, answers };
  });
}

function normalizeStudent(raw, index) {
  if (raw.answers && typeof raw.answers === "object") {
    return { student: String(raw.student || raw.学生 || `学生${index + 1}`), answers: normalizeAnswerKeys(raw.answers) };
  }
  const student = String(raw.student || raw.学生 || raw.name || raw.姓名 || `学生${index + 1}`);
  const answers = {};
  Object.entries(raw).forEach(([key, value]) => {
    if (!["student", "学生", "name", "姓名"].includes(key)) answers[key] = value;
  });
  return { student, answers };
}

function normalizeAnswerKeys(rawAnswers) {
  const answers = {};
  Object.entries(rawAnswers || {}).forEach(([key, value]) => {
    const rawKey = String(key || "").trim();
    const qid = rawKey.toLowerCase().startsWith("q") ? rawKey : `q${normalizeQuestionNo(rawKey)}`;
    answers[qid] = value;
  });
  return answers;
}

function parseStudents(text, fileName = "") {
  const trimmed = text.trim();
  let rawItems;
  if (!trimmed) return [];
  if (trimmed.startsWith("[") || trimmed.startsWith("{")) {
    rawItems = parseJSON(trimmed);
  } else if (fileName.endsWith(".csv") || trimmed.split(/\r?\n/)[0].includes(",")) {
    rawItems = rowsToObjects(parseCSV(trimmed));
  } else {
    rawItems = parseStudentText(trimmed);
  }
  return rawItems.map(normalizeStudent).filter((item) => item.student);
}

function parseStudentOcr(text, fileName = "") {
  const answerCardStudents = parseAnswerCardText(text, fileName);
  if (answerCardStudents.length) return answerCardStudents;
  const parsed = parseStudents(text, fileName).filter((item) => Object.keys(item.answers || {}).length);
  if (parsed.length) return parsed;
  const answers = {};
  const lines = text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  lines.forEach((line) => {
    if (line.startsWith("===")) return;
    const match = line.match(/^(?:第\s*)?([0-9一二三四五六七八九十]+)\s*(?:题)?[\.\．\、\):：\s-]*(.+)$/);
    if (match) answers[`q${normalizeQuestionNo(match[1])}`] = match[2].trim();
  });
  return [
    {
      student: fileName.replace(/\.[^.]+$/, "") || "OCR学生作业",
      answers,
    },
  ];
}

function parseAnswerCardText(text, fileName = "") {
  const sections = splitAnswerCardSections(text, fileName);
  return sections
    .map((section, index) => {
      const student =
        detectStudentName(section.text) ||
        deriveStudentNameFromPath(section.name) ||
        deriveStudentNameFromPath(fileName) ||
        `答题卡-${index + 1}`;
      const answers = extractAnswerCardAnswers(section.text);
      return { student, answers };
    })
    .filter((item) => Object.keys(item.answers).length);
}

function deriveStudentNameFromPath(path) {
  const normalizedPath = String(path || "").replace(/\\/g, "/").trim();
  if (!normalizedPath) return "";
  const parts = normalizedPath.split("/").filter(Boolean);
  if (parts.length > 1) return cleanStudentFileName(parts[0]);
  return cleanStudentFileName(parts[0] || "");
}

function cleanStudentFileName(name) {
  return String(name || "")
    .replace(/\.[^.]+$/, "")
    .replace(/[-_ ]?(?:第)?\d{1,3}(?:页|p|page)?$/i, "")
    .replace(/[-_ ]?(?:answer|scan|photo|答题卡|试卷)$/i, "")
    .trim();
}

function splitAnswerCardSections(text, fileName = "") {
  const byFile = splitOcrSections(text, fileName);
  const sections = [];
  byFile.forEach((section) => {
    const lines = section.text.split(/\r?\n/);
    let current = { name: section.name, text: "" };
    lines.forEach((line) => {
      const isNameLine = /(?:学生|姓名|考生|Name|name)\s*[:：]/.test(line);
      if (isNameLine && current.text.trim()) {
        sections.push(current);
        current = { name: section.name, text: "" };
      }
      current.text += `${line}\n`;
    });
    if (current.text.trim()) sections.push(current);
  });
  return sections;
}

function splitOcrSections(text, fileName) {
  const lines = String(text || "").split(/\r?\n/);
  const sections = [];
  let current = { name: fileName.replace(/\.[^.]+$/, "") || "答题卡", text: "" };
  lines.forEach((line) => {
    const header = line.match(/^===\s*(.+?)\s*===$/);
    if (header) {
      if (current.text.trim()) sections.push(current);
      current = { name: header[1].replace(/\.[^.]+$/, ""), text: "" };
    } else {
      current.text += `${line}\n`;
    }
  });
  if (current.text.trim()) sections.push(current);
  return sections.length ? sections : [{ name: fileName.replace(/\.[^.]+$/, "") || "答题卡", text }];
}

function detectStudentName(text) {
  const match = String(text || "").match(/(?:学生|姓名|考生|姓名姓名|Name|name)\s*[:：]?\s*([\u4e00-\u9fa5A-Za-z0-9_-]{2,20})/);
  return match ? match[1] : "";
}

function extractAnswerCardAnswers(text) {
  const answers = {};
  const normalizedText = String(text || "").replace(/[．]/g, ".");
  const objectivePattern = /(?:第\s*)?([0-9]{1,3})\s*(?:题)?\s*[\.\、\):：-]?\s*(?:答案)?\s*[:：]?\s*([A-Da-d对错√×真假]|-?\d+(?:\.\d+)?)(?=\s|$|[;；,，、])/g;
  let match;
  while ((match = objectivePattern.exec(normalizedText))) {
    const no = normalizeQuestionNo(match[1]);
    const value = match[2].trim();
    answers[`q${no}`] = /^[a-d]$/i.test(value) ? value.toUpperCase() : value;
  }

  normalizedText.split(/\r?\n/).forEach((line) => {
    if (line.startsWith("===")) return;
    const subjective = line.match(/^(?:第\s*)?([0-9]{1,3})(?:\s*[（(]([0-9一二三四五六七八九十]+)[）)])?\s*(?:题)?[\.\、\):：-]\s*(.+)$/);
    if (!subjective) return;
    const no = normalizeQuestionNo(subjective[1]);
    const subNo = subjective[2] ? `_${normalizeQuestionNo(subjective[2])}` : "";
    const key = `q${no}${subNo}`;
    const value = subjective[3].trim();
    if (!answers[key] && value.length > 1) answers[key] = value;
  });

  return answers;
}

function getMode(question) {
  if (manualTypes.has(question.type)) return "manual";
  if (autoTypes.has(question.type)) return "auto";
  if (assistTypes.has(question.type)) return "assist";
  return question.answer ? "auto" : "assist";
}

function gradeAuto(question, answer) {
  const accepted = buildAcceptedAnswerSet(question.answer);
  const actual = normalize(answer);
  const correct = accepted.includes(actual);
  return {
    mode: "auto",
    score: correct ? question.score : 0,
    maxScore: question.score,
    confidence: actual ? 0.96 : 0.2,
    status: correct ? "自动通过" : "自动判错",
    evidence: correct ? "学生答案与参考答案一致。" : `参考答案：${formatMathText(question.answer || "缺失")}；学生答案：${formatMathText(answer || "未作答")}。`,
    feedback: correct ? "答案正确。" : "请对照参考答案订正，并检查是否存在计算或审题错误。",
    reviewRequired: !actual || !question.answer,
  };
}

function buildAcceptedAnswerSet(value) {
  const answers = [String(value ?? "").trim(), ...splitAcceptedAnswers(value)];
  return [...new Set(answers.map(normalize).filter(Boolean))];
}

function splitAcceptedAnswers(value) {
  if (Array.isArray(value)) return value.map(String).map((item) => item.trim()).filter(Boolean);
  return String(value ?? "")
    .split(/\s*(?:\||；|;|\n|或|或者)\s*/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function questionsToReadableText(questions) {
  return (questions || [])
    .map((question) => {
      const lines = [
        `${question.id} ${getQuestionTypeLabel(question.type)}${question.score ? `（${question.score}分）` : ""}`,
        question.title ? `题目：${formatMathText(question.title)}` : "",
        String(question.answer ?? "").trim() ? `参考答案：${formatMathText(question.answer)}` : "",
        question.rubric?.length ? `评分点：${question.rubric.join("；")}` : "",
        question.visualNotes ? `图形：${question.visualNotes}` : "",
      ].filter(Boolean);
      return lines.join("\n");
    })
    .join("\n\n");
}

function hitItems(items, answer) {
  const normalizedAnswer = normalize(answer);
  return items.filter((item) => normalizedAnswer.includes(normalize(item)));
}

function buildMathAnswerCandidates(value) {
  const text = formatMathText(value || "")
    .replace(/\s+/g, "")
    .replace(/[。；;，,、]+$/g, "");
  if (!text) return [];
  const candidates = new Set([text]);
  const conclusionPatterns = [
    /(?:答案|结果|结论|解集|故|所以|∴|得|为|是)[:：]?(.{1,80})$/g,
    /(?:解集为|结果为|答案为|最大值为|最小值为)(.{1,80})$/g,
  ];
  conclusionPatterns.forEach((pattern) => {
    for (const match of text.matchAll(pattern)) {
      if (match[1]) candidates.add(match[1].replace(/[。；;，,、]+$/g, ""));
    }
  });

  const expressionPatterns = [
    /-?\d+(?:\/\d+)?(?:\.\d+)?[≤<][a-zA-Z][≤<]-?\d+(?:\/\d+)?(?:\.\d+)?/g,
    /[a-zA-Z][=＝]-?\d+(?:\/\d+)?(?:\.\d+)?/g,
    /[a-zA-Z][≥>≤<]-?\d+(?:\/\d+)?(?:\.\d+)?/g,
    /-?\d+(?:\.\d+)?×10[\^⁰¹²³⁴⁵⁶⁷⁸⁹+-]+/g,
    /√\([^)]+\)|\([^)]*\)\/\([^)]*\)|-?\d+\/\d+/g,
  ];
  expressionPatterns.forEach((pattern) => {
    for (const match of text.matchAll(pattern)) {
      candidates.add(match[0]);
    }
  });

  return [...candidates]
    .map((item) => normalize(item))
    .filter((item) => item.length >= 2);
}

function matchStandardAnswer(question, answer) {
  const standardCandidates = buildMathAnswerCandidates(question.answer);
  const studentCandidates = buildMathAnswerCandidates(answer);
  const normalizedStudent = normalize(answer);
  if (!standardCandidates.length || !normalizedStudent) {
    return { matched: false, matchedText: "" };
  }
  const matched = standardCandidates.find((candidate) => {
    if (!candidate) return false;
    return normalizedStudent.includes(candidate) || studentCandidates.includes(candidate);
  });
  return { matched: Boolean(matched), matchedText: matched || "" };
}

function tokenizeMeaningful(text) {
  const source = String(text || "")
    .replace(/[^\u4e00-\u9fa5A-Za-z0-9]/g, " ")
    .split(/\s+/)
    .filter(Boolean);
  const tokens = new Set();
  source.forEach((part) => {
    if (/^[A-Za-z0-9]+$/.test(part)) {
      if (part.length >= 3) tokens.add(part.toLowerCase());
      return;
    }
    for (let size of [4, 3, 2]) {
      for (let index = 0; index <= part.length - size; index += 1) {
        const token = part.slice(index, index + size);
        if (!isWeakChineseToken(token)) tokens.add(token);
      }
    }
  });
  return [...tokens].slice(0, 28);
}

function isWeakChineseToken(token) {
  const weak = new Set(["什么", "为什么", "如何", "结合", "材料", "分析", "说明", "简述", "下列", "正确", "的是", "题目", "答案", "证明", "两个"]);
  return weak.has(token);
}

function evaluateQuestionResponse(question, answer) {
  const title = String(question.title || question.stem || question.material || "").trim();
  if (!title) {
    return {
      level: "无法判断",
      ratio: 0,
      hits: [],
      tokens: [],
      message: "题目缺失，无法判断学生是否回应设问，只能做低置信评分点检查。",
    };
  }
  const tokens = tokenizeMeaningful(title);
  const hits = hitItems(tokens, answer);
  const ratio = tokens.length ? hits.length / Math.min(tokens.length, 8) : 0;
  let level = "低";
  if (ratio >= 0.45 || hits.length >= 4) level = "高";
  else if (ratio >= 0.2 || hits.length >= 2) level = "中";
  return {
    level,
    ratio: Math.min(1, ratio),
    hits,
    tokens,
    message:
      level === "高"
        ? "学生答案与题目核心要求匹配度较高。"
        : level === "中"
          ? "学生答案与题目部分相关，建议教师确认是否答完整。"
          : "学生答案与题目核心要求匹配度较低，存在偏题或答非所问风险。",
  };
}

function analyzeQuestionIntent(question) {
  const title = String(question.title || question.stem || question.material || "").trim();
  const normalizedTitle = normalize(title);
  const intents = [];
  const subject = String(question.subject || "").trim();
  const type = String(question.type || "").trim();

  if (!title) {
    return {
      title,
      subject,
      type,
      intents: ["题目缺失"],
      requiredActions: [],
      hasQuestion: false,
      summary: "题目缺失，无法完整解析设问。",
    };
  }

  const patterns = [
    ["分析", "分析原因、影响或意义"],
    ["说明", "说明观点或材料含义"],
    ["概括", "概括材料要点"],
    ["结合材料", "结合材料作答"],
    ["证明", "按条件完成推理证明"],
    ["评价", "评价观点并说明理由"],
    ["为什么", "回答原因"],
    ["如何", "回答做法或路径"],
    ["谈谈", "表达观点并展开论述"],
    ["长大", "围绕成长变化表达中心"],
  ];

  patterns.forEach(([keyword, intent]) => {
    if (normalizedTitle.includes(normalize(keyword))) intents.push(intent);
  });

  if (!intents.length) {
    if (["essay", "语文作文"].includes(type)) intents.push("围绕作文题目表达中心思想");
    else if (["proof", "数学证明题"].includes(type)) intents.push("依据题目条件完成证明");
    else intents.push("正面回应题干设问");
  }

  return {
    title,
    subject,
    type,
    intents: [...new Set(intents)],
    requiredActions: tokenizeMeaningful(title).slice(0, 8),
    hasQuestion: true,
    summary: [...new Set(intents)].join("；"),
  };
}

function deriveStandardPoints(question) {
  const answerPoints = splitList(question.answer);
  const rubricPoints = question.rubric || [];
  const keywordPoints = question.keywords || [];
  const combined = [...rubricPoints, ...keywordPoints, ...answerPoints]
    .map((item) => String(item).trim())
    .filter(Boolean);
  return [...new Set(combined)];
}

function detectTheme(answer) {
  const text = String(answer || "").replace(/\s+/g, "");
  if (!text) return "未识别到有效作答内容";
  const sentences = text.split(/[。！？!?；;]/).filter(Boolean);
  const first = sentences.find((item) => item.length >= 8) || sentences[0] || text;
  return first.length > 46 ? `${first.slice(0, 46)}...` : first;
}

function gradeAssist(question, answer) {
  const intent = analyzeQuestionIntent(question);
  const rubric = deriveStandardPoints(question);
  const hits = hitItems(rubric, answer);
  const keywords = hitItems(question.keywords, answer);
  const response = evaluateQuestionResponse(question, answer);
  const standardMatch = matchStandardAnswer(question, answer);
  const essayLike = ["essay", "语文作文"].includes(question.type);
  if (!essayLike && standardMatch.matched && question.score) {
    return {
      mode: "assist",
      score: question.score,
      maxScore: question.score,
      confidence: 0.9,
      status: "自动辅助通过",
      evidence: `参考答案：${formatMathText(question.answer || "")}。学生答案已命中参考答案最终结论：${standardMatch.matchedText}。`,
      feedback: "最终答案与参考答案一致，系统已按满分辅助判定；如需检查过程严谨性，可由教师复核。",
      reviewRequired: false,
      hits: standardMatch.matchedText ? [standardMatch.matchedText] : hits,
      missing: [],
      questionIntent: intent,
      hasStandardAnswer: true,
      questionResponse: response,
      matchedStandardAnswer: true,
    };
  }
  const rubricRatio = rubric.length ? hits.length / rubric.length : Math.min(String(answer || "").length / 120, 1);
  const responseWeight = response.level === "无法判断" ? 0.2 : response.ratio;
  const hasStandardAnswer = String(question.answer ?? "").trim().length > 0;
  const lengthBonus = String(answer || "").length >= 60 ? 0.08 : 0;
  const standardWeight = hasStandardAnswer ? 0.74 : 0.58;
  const responseScoreWeight = hasStandardAnswer ? 0.18 : 0.30;
  const scoreRatio = Math.min(1, rubricRatio * standardWeight + responseWeight * responseScoreWeight + lengthBonus);
  const score = Math.round((question.score || 10) * scoreRatio);
  const baseConfidence = response.level === "无法判断" ? 0.24 : hasStandardAnswer ? 0.5 : 0.38;
  const confidence = Math.max(0.2, Math.min(0.88, baseConfidence + scoreRatio * 0.28));
  const missing = rubric.filter((item) => !hits.includes(item));
  const titlePart = intent.hasQuestion ? `题目：${intent.title}。题目要求：${intent.summary}。` : "题目缺失。";
  const responsePart = `题目回应度：${response.level}。${response.message}`;
  const standardPart = hasStandardAnswer ? "已按上方参考答案和评分标准辅助判断。" : "未提供标准答案，仅按题目和评分框架辅助判断。";
  const rubricPart = `命中评分点/参考要点：${hits.join("、") || "暂无"}；遗漏：${missing.join("、") || "暂无"}。`;

  return {
    mode: "assist",
    score,
    maxScore: question.score || 0,
    confidence,
    status: !question.score || response.level === "低" || response.level === "无法判断" || !intent.hasQuestion ? "重点复核" : "需教师复核",
    evidence: essayLike
      ? `${titlePart}${standardPart} 学生中心思想：${detectTheme(answer)}。${responsePart} 关键词命中：${keywords.join("、") || "较少"}。${rubricPart}`
      : `${titlePart}${standardPart} ${responsePart} ${rubricPart}`,
    feedback: essayLike
      ? response.level === "低"
        ? "请先确认文章是否扣题，再围绕题目关键词补充具体事件、感受和结尾点题。"
        : "请围绕题目关键词补充更具体的事件、感受和结尾点题。"
      : response.level === "低"
        ? "请先回到题目要求，确认答案是否正面回应设问，再补充采分点。"
        : missing.length
        ? `建议补充：${missing.slice(0, 3).join("、")}。`
        : "观点或步骤较完整，建议教师确认表达质量和过程严谨性。",
    reviewRequired: true,
    hits,
    missing,
    questionIntent: intent,
    hasStandardAnswer,
    questionResponse: response,
    theme: essayLike ? detectTheme(answer) : "",
  };
}

function gradeManual(question, answer) {
  return {
    mode: "manual",
    score: 0,
    maxScore: question.score || 0,
    confidence: 0.2,
    status: "人工处理",
    evidence: `当前 MVP 不可靠自动处理该题型：${question.type || "未知题型"}。`,
    feedback: answer ? "已保存学生作答，建议教师人工批改。" : "未识别到有效作答，请教师确认。",
    reviewRequired: true,
  };
}

function gradeOne(question, student) {
  const answer = student.answers[question.id] ?? student.answers[question.title] ?? "";
  if (!question.score) {
    return {
      question,
      student: student.student,
      answer,
      mode: "assist",
      score: 0,
      maxScore: 0,
      confidence: 0.2,
      status: "重点复核",
      evidence: "未识别到该题分值，系统不自动猜分。请老师在题目列表中补充分值后再批改。",
      feedback: "请先确认题目分值和参考答案，再运行批改。",
      reviewRequired: true,
      hits: [],
      missing: [],
    };
  }
  const mode = getMode(question);
  let result;
  if (mode === "manual") result = gradeManual(question, answer);
  else if (mode === "auto") result = gradeAuto(question, answer);
  else result = gradeAssist(question, answer);
  return {
    question,
    student: student.student,
    answer,
    ...result,
  };
}

function runGrading() {
  if (!state.questions.length || !state.students.length) {
    showToast("请先上传参考答案/评分规则文件和学生作业文件。");
    return;
  }
  if (!state.referenceConfirmed) {
    showToast("请先在题目列表确认题号、分值、参考答案和评分点。");
    return;
  }
  state.results = state.students.map((student) => ({
    student: student.student,
    items: state.questions.map((question) => gradeOne(question, student)),
  }));
  state.activeStudent = state.results[0]?.student || "";
  renderAll();
  switchView("results");
  showToast("批改完成：已生成学生结果、复核队列和班级分析。");
}

function calculateMetrics() {
  const allItems = state.results.flatMap((result) => result.items);
  const reviewCount = allItems.filter((item) => item.reviewRequired).length;
  const autoCount = allItems.filter((item) => item.mode === "auto").length;
  const totalScore = state.results.reduce((sum, result) => sum + result.items.reduce((itemSum, item) => itemSum + item.score, 0), 0);
  const totalMax = state.results.reduce((sum, result) => sum + result.items.reduce((itemSum, item) => itemSum + item.maxScore, 0), 0);
  return [
    { label: "题目数", value: String(state.questions.length), note: "来自上传文件" },
    { label: "学生数", value: String(state.students.length), note: "已解析作答" },
    { label: "自动题", value: String(autoCount), note: "可直接规则判分" },
    { label: "平均得分率", value: totalMax ? `${Math.round((totalScore / totalMax) * 100)}%` : "-", note: `${reviewCount} 处需复核` },
  ];
}

function getQuestionTypeLabel(type) {
  const value = String(type || "").trim();
  const labels = {
    choice: "选择题",
    judge: "判断题",
    fill: "填空题",
    single: "单一答案题",
    calculation: "计算题",
    geometry: "几何题",
    proof: "证明题",
    math_process: "数学过程题",
    essay: "作文",
    reading: "阅读理解",
    history: "历史材料题",
    politics: "政治论述题",
    subjective: "主观题",
    physics: "物理题",
    chemistry: "化学题",
  };
  return labels[value] || value || "待确认题型";
}

function getQuestionMetaText(question) {
  return [question.id, question.subject, getQuestionTypeLabel(question.type)].filter(Boolean).join(" · ");
}

function renderQuestionTypeOptions(currentType) {
  const options = [
    ["choice", "选择题"],
    ["fill", "填空题"],
    ["judge", "判断题"],
    ["calculation", "计算题"],
    ["geometry", "几何题"],
    ["proof", "证明题"],
    ["subjective", "主观题"],
    ["essay", "作文"],
    ["reading", "阅读理解"],
    ["history", "历史材料题"],
    ["politics", "政治论述题"],
    ["physics", "物理题"],
    ["chemistry", "化学题"],
  ];
  const value = String(currentType || "").trim();
  const hasCurrent = !value || options.some(([type]) => type === value);
  const optionHtml = options
    .map(([type, label]) => `<option value="${escapeHtml(type)}" ${type === value ? "selected" : ""}>${escapeHtml(label)}</option>`)
    .join("");
  return `${hasCurrent ? "" : `<option value="${escapeHtml(value)}" selected>${escapeHtml(value)}</option>`}<option value="" ${value ? "" : "selected"}>待确认题型</option>${optionHtml}`;
}

function renderEditableQuestionCard(question, index) {
  const rubricText = (question.rubric || []).join("；");
  const answerPreview = formatQuestionPreview(formatMathText(question.answer || "未填参考答案"), 44);
  const rubricPreview = question.rubric?.length ? `${question.rubric.length} 个评分点` : "未识别到评分点";
  const scorePreview = question.score ? `${question.score} 分` : "未识别到分值";
  const isOpen = state.expandedQuestionIds.has(question.id) ? " open" : "";
  return `
    <details class="question-edit-card" data-question-index="${index}" data-question-id="${escapeHtml(question.id)}"${isOpen}>
      <summary class="question-summary">
        <div class="question-summary-main">
          <strong>${escapeHtml(getQuestionMetaText(question))}</strong>
          <span>${escapeHtml(formatQuestionPreview(formatMathText(question.title || "待确认题目"), 56))}</span>
        </div>
        <div class="question-summary-meta">
          <span>${escapeHtml(scorePreview)}</span>
          <span>答案：${escapeHtml(answerPreview)}</span>
          <span>${escapeHtml(rubricPreview)}</span>
          <b>编辑</b>
        </div>
      </summary>
      <div class="question-edit-body">
        <div class="question-edit-head">
          <label>
            <span>题号</span>
            <input data-question-field="id" value="${escapeHtml(question.id)}" />
          </label>
          <label>
            <span>题型</span>
            <select data-question-field="type">${renderQuestionTypeOptions(question.type)}</select>
          </label>
          <label>
            <span>分值</span>
            <input data-question-field="score" type="text" inputmode="decimal" value="${escapeHtml(question.score || "")}" />
          </label>
        </div>
        <label class="question-edit-full">
          <span>题目</span>
          <textarea data-question-field="title" rows="2" spellcheck="false">${escapeHtml(formatMathText(question.title || ""))}</textarea>
        </label>
        <label class="question-edit-full">
          <span>参考答案</span>
          <textarea data-question-field="answer" rows="2" spellcheck="false">${escapeHtml(formatMathText(question.answer || ""))}</textarea>
        </label>
        <label class="question-edit-full">
          <span>评分点</span>
          <textarea data-question-field="rubric" rows="2" spellcheck="false">${escapeHtml(rubricText)}</textarea>
        </label>
        ${question.visualNotes ? `<p class="question-visual-note">图形：${escapeHtml(question.visualNotes)}</p>` : ""}
      </div>
    </details>
  `;
}

function formatQuestionPreview(value, maxLength = 60) {
  const text = String(value ?? "").replace(/\s+/g, " ").trim();
  return text.length > maxLength ? `${text.slice(0, maxLength)}...` : text;
}

function buildScoreAudit() {
  const groups = new Map();
  let total = 0;
  const missing = [];
  state.questions.forEach((question) => {
    const score = Number(question.score || 0);
    const type = getQuestionTypeLabel(question.type);
    if (!groups.has(type)) groups.set(type, { type, count: 0, score: 0, missing: 0 });
    const group = groups.get(type);
    group.count += 1;
    if (score > 0) {
      group.score += score;
      total += score;
    } else {
      group.missing += 1;
      missing.push(question.id);
    }
  });
  const expected = parseDecimalInput(state.expectedTotalScore);
  const diff = expected ? total - expected : 0;
  return { total, expected: Number.isFinite(expected) ? expected : 0, diff, missing, groups: [...groups.values()] };
}

function renderScoreAuditPanel() {
  const audit = buildScoreAudit();
  const status = !audit.expected
    ? "未填写标称总分"
    : audit.diff === 0 && !audit.missing.length
      ? "总分一致"
      : "需要复核";
  const groupRows = audit.groups.length
    ? audit.groups
        .map(
          (group) => `
            <tr data-score-type="${escapeHtml(group.type)}">
              <td>${escapeHtml(group.type)}</td>
              <td>${group.count}</td>
              <td>${group.score}</td>
              <td>${group.missing || "-"}</td>
              <td>
                <div class="type-score-tool">
                  <input data-type-score-input data-type-score-key="${escapeHtml(group.type)}" type="text" inputmode="decimal" value="${escapeHtml(state.typeScoreDrafts[group.type] || "")}" placeholder="每题分" />
                  <button class="secondary-button" data-apply-type-score type="button">应用</button>
                </div>
              </td>
            </tr>
          `,
        )
        .join("")
    : `<tr><td colspan="5">暂无题目</td></tr>`;
  return `
    <details class="score-audit-panel"${state.scoreAuditOpen ? " open" : ""}>
      <summary>
        <span>核对总分</span>
        <strong>${audit.total} 分</strong>
        <em>${escapeHtml(status)}</em>
      </summary>
      <div class="score-audit-body">
        <label>
          <span>试卷标称总分</span>
          <input data-expected-total-score type="text" inputmode="decimal" value="${escapeHtml(state.expectedTotalScore)}" placeholder="如 150" />
        </label>
        <div class="score-audit-cards">
          <div><span>已识别总分</span><strong>${audit.total}</strong></div>
          <div><span>标称总分</span><strong>${audit.expected || "-"}</strong></div>
          <div><span>差值</span><strong>${audit.expected ? audit.diff : "-"}</strong></div>
          <div><span>缺分题</span><strong>${audit.missing.length}</strong></div>
        </div>
        ${audit.missing.length ? `<p class="score-audit-warning">未识别分值：${escapeHtml(audit.missing.join("、"))}。请展开对应题目补充分值。</p>` : ""}
        <table class="score-audit-table">
          <thead><tr><th>题型</th><th>题数</th><th>已识别分值</th><th>缺分题数</th><th>按题型配置</th></tr></thead>
          <tbody>${groupRows}</tbody>
        </table>
      </div>
    </details>
  `;
}

function renderMetrics() {
  byId("metricsGrid").innerHTML = calculateMetrics()
    .map(
      (item) => `
        <article class="metric-card">
          <span>${item.label}</span>
          <strong>${item.value}</strong>
          <p>${item.note}</p>
        </article>
      `,
    )
    .join("");
}

function renderPreview() {
  const missingScoreCount = state.questions.filter((question) => !question.score).length;
  const missingAnswerCount = state.questions.filter((question) => !String(question.answer ?? "").trim()).length;
  byId("questionPreview").innerHTML = state.questions.length
    ? `
      <div class="question-review-toolbar">
        <div>
          <strong>${state.referenceConfirmed ? "题目答案已确认" : "题目答案待确认"}</strong>
          <span>${state.questions.length} 道题；${missingScoreCount} 题未识别分值；${missingAnswerCount} 题未识别参考答案</span>
        </div>
        <button class="primary-button" data-confirm-reference type="button">${state.referenceConfirmed ? "已确认" : "确认题目答案"}</button>
      </div>
      ${renderScoreAuditPanel()}
      ${state.questions.map(renderEditableQuestionCard).join("")}
    `
    : `<p class="empty">尚未解析题目。</p>`;

  byId("studentPreview").innerHTML = state.students.length
    ? state.students
        .map(
          (student) => `
            <article>
              <strong>${student.student}</strong>
              <span>${Object.keys(student.answers).length} 道作答</span>
              <div class="answer-chip-list">${renderAnswerChips(student.answers)}</div>
            </article>
          `,
        )
        .join("")
    : `<p class="empty">尚未解析学生作业。</p>`;

  const ocrTargetText = state.lastOcrTarget === "reference" ? "参考答案/评分规则" : state.lastOcrTarget === "submission" ? "学生作业" : "最近上传文件";
  const hasReferenceOcr = Boolean(state.referenceOcrText);
  const hasSubmissionOcr = Boolean(state.submissionOcrText);
  byId("ocrPreview").innerHTML = state.ocrText
    ? `
      <h3>OCR 文本预览</h3>
      <div class="segmented-control">
        <button class="${state.lastOcrTarget === "reference" ? "active" : ""}" data-show-ocr="reference" type="button" ${hasReferenceOcr ? "" : "disabled"}>查看参考答案解析</button>
        <button class="${state.lastOcrTarget === "submission" ? "active" : ""}" data-show-ocr="submission" type="button" ${hasSubmissionOcr ? "" : "disabled"}>查看学生作答解析</button>
      </div>
      <p class="helper-text">当前显示：${ocrTargetText}。老师可以在这里修正 OCR 文本，再点击对应按钮重新解析。</p>
      ${renderOcrQuality()}
      <p class="helper-text">手写答案、答题卡表格和低清图片可能会出现漏字、错字、题号错位或行列打乱。你可以在这里修正文本，再重新解析。</p>
      <div class="math-editor-tools" aria-label="数学符号快捷输入">
        ${renderMathInsertButtons()}
      </div>
      <div class="ocr-editor-title">可编辑数学表达式预览</div>
      <textarea id="ocrEditor" class="math-preview editable-preview" rows="18" spellcheck="false">${escapeHtml(formatMathText(state.ocrText))}</textarea>
      <div class="action-row ocr-actions">
        <button class="secondary-button" data-ocr-reparse="reference" type="button">按参考答案重新解析</button>
        <button class="secondary-button" data-ocr-reparse="submission" type="button">按学生作业重新解析</button>
        <button class="primary-button" data-ocr-llm-reparse type="button">${getLlmReparseButtonText()}</button>
      </div>
      <p class="helper-text">
        按参考答案重新解析：把左侧文本当成标准答案/评分规则，重新生成题目列表。按学生作业重新解析：把左侧文本当成学生作答，重新生成学生答案。${getLlmReparseButtonText()}：把当前 OCR 文本交给云端/本地模型做结构化，只更新当前显示的这一类数据。
      </p>
      <p class="helper-text">数学建议格式：<code>22(1). 2(a+1/2)^2-(2a+7/2)(a-1)-(a^2-4)/a÷((a^2+5)/(a-1)-a+1)</code>、<code>√(x+1)</code>、<code>|x-3|</code>、<code>x^2</code>、<code>1/2</code>、<code>lim_{x→0}</code>、<code>f′(0)</code>、<code>dy/dx</code>、<code>∫_{}^{}</code>。</p>
    `
    : "";
}

function renderAnswerChips(answers) {
  const entries = Object.entries(answers || {}).sort(([left], [right]) => compareQuestionIds(left, right));
  if (!entries.length) return "";
  return entries
    .map(([key, value]) => `<span class="answer-chip"><strong>${escapeHtml(key)}</strong>${escapeHtml(formatMathText(value || "未作答/未识别")).slice(0, 160)}</span>`)
    .join("");
}

function compareQuestionIds(left, right) {
  const parse = (value) => {
    const match = String(value || "").match(/q?(\d+)(?:[_-]?(\d+))?/i);
    if (!match) return [Number.MAX_SAFE_INTEGER, 0, String(value || "")];
    return [Number(match[1]), Number(match[2] || 0), String(value || "")];
  };
  const a = parse(left);
  const b = parse(right);
  return a[0] - b[0] || a[1] - b[1] || a[2].localeCompare(b[2]);
}

function formatMathText(value) {
  return toSimplifiedText(value)
    .split(/\r?\n/)
    .map((line) => (isLikelyMathSourceLine(line) ? normalizeMathDisplay(line) : line))
    .join("\n");
}

function toSimplifiedText(value) {
  const map = {
    問: "问",
    題: "题",
    關: "关",
    鍵: "键",
    線: "线",
    段: "段",
    圖: "图",
    樹: "树",
    對: "对",
    錯: "错",
    規: "规",
    則: "则",
    學: "学",
    體: "体",
    點: "点",
    類: "类",
    項: "项",
    結: "结",
    構: "构",
    過: "过",
    程: "程",
    證: "证",
    據: "据",
    準: "准",
    確: "确",
    識: "识",
    彙: "汇",
    總: "总",
  };
  return String(value ?? "").replace(/[問題關鍵線圖樹對錯規則學體點類項結構過證據準確識彙總]/g, (char) => map[char] || char);
}

function isLikelyMathSourceLine(line) {
  return /[=+\-×÷*/^²³√≤≥≈≠∞π∫∂′'→∠△⊥∥{}()[\]]|\\(?:frac|sqrt|int|lim|partial|infty|leq?|geq?|neq|sin|cos|tan|ln|Delta)|\b(?:sqrt|abs|lim|ln|sin|cos|tan|cot|sec|csc|log|exp|dx|dy)\b|\bf\s*['′]\s*\(|d\s*[xy]\s*\/\s*d\s*[xy]|d\/d[xy]|求导|导数|微分|积分|极限|偏导|参数方程|隐函数|分段函数|函数|方程|根号|平方|分数|角|三角形|直线|垂直|平行|证明|相似|全等|圆|半径|直径|度数/.test(String(line || ""));
}

function renderMathInsertButtons() {
  const items = [
    ["分数", "()/()"],
    ["根号", "√()"],
    ["平方", "^2"],
    ["幂", "^()"],
    ["绝对值", "| |"],
    ["括号", "()"],
    ["乘号", "×"],
    ["除号", "÷"],
    ["≤", "≤"],
    ["≥", "≥"],
    ["≈", "≈"],
    ["π", "π"],
    ["e", "e"],
    ["ln", "ln()"],
    ["sin", "sin()"],
    ["cos", "cos()"],
    ["tan", "tan()"],
    ["导数", "f′(x)"],
    ["d/dx", "d/dx"],
    ["偏导", "∂/∂x"],
    ["积分", "∫"],
    ["定积分", "∫_{}^{}"],
    ["极限", "lim_{x→0}"],
    ["无穷", "∞"],
    ["趋于", "→"],
    ["不等于", "≠"],
    ["分段", "{\n  ,\n  ,\n}"],
    ["因为", "∵"],
    ["所以", "∴"],
    ["角", "∠"],
    ["三角形", "△"],
    ["垂直", "⊥"],
    ["平行", "∥"],
  ];
  return items
    .map(([label, value]) => `<button class="math-tool-button" data-insert-math="${escapeHtml(value)}" type="button">${escapeHtml(label)}</button>`)
    .join("");
}

function renderMathPreview(text) {
  const lines = String(text || "").split(/\r?\n/);
  const previewLines = lines.map((line) => {
    const normalized = normalizeMathDisplay(line);
    const className = isLikelyMathLine(normalized) ? "math-line is-math" : "math-line";
    return `<div class="${className}">${escapeHtml(normalized) || "&nbsp;"}</div>`;
  });
  return previewLines.join("");
}

function getLlmReparseTarget() {
  return state.lastOcrTarget === "submission" ? "submission" : "reference";
}

function getLlmReparseButtonText() {
  return getLlmReparseTarget() === "submission" ? "用大模型解析学生作业" : "用大模型解析参考答案";
}

function normalizeMathDisplay(line) {
  let value = String(line || "")
    .replace(/\\text\s*\{([^}]*)\}/g, "$1")
    .replace(/\\mathrm\s*\{([^}]*)\}/g, "$1")
    .replace(/\\times/g, "×")
    .replace(/\\cdot/g, "·")
    .replace(/\\left\s*/g, "")
    .replace(/\\right\s*/g, "")
    .replace(/\\leq?/g, "≤")
    .replace(/\\geq?/g, "≥")
    .replace(/\\neq/g, "≠")
    .replace(/\\infty/g, "∞")
    .replace(/\\to/g, "→")
    .replace(/\\rightarrow/g, "→")
    .replace(/\\ln/g, "ln")
    .replace(/\\sin/g, "sin")
    .replace(/\\cos/g, "cos")
    .replace(/\\tan/g, "tan")
    .replace(/\\log/g, "log")
    .replace(/\\exp/g, "exp")
    .replace(/\\lim\s*_\s*\{([^}]*)\}/g, "lim_{$1}")
    .replace(/\\int/g, "∫")
    .replace(/\\partial/g, "∂")
    .replace(/\\Delta/g, "Δ")
    .replace(/\\prime/g, "′")
    .replace(/\bfprime\s*\(/gi, "f′(")
    .replace(/\bint(?=_)/gi, "∫")
    .replace(/10([⁰¹²³⁴⁵⁶⁷⁸⁹]+)/g, (_, power) => `10^${normalizeSuperscriptDigits(power)}`)
    .replace(/([ZzＺｚ])\s*([0-9]+)/g, "∠$2")
    .replace(/\b[LlI]\s*([0-9])(?=\s*=\s*\d+°?)/g, "∠$1")
    .replace(/(^|[\s，,。；;])2\s*([1-9])(?=\s*=\s*\d+°?)/g, "$1∠$2")
    .replace(/[二乙之]\s*([0-9]+)(?=的?度数|度数|为|=|，|,|。|$)/g, "∠$1")
    .replace(/[二乙之]\s*([0-9]+)(?=\s*的)/g, "∠$1")
    .replace(/(?<=∠)\s+/g, "")
    .replace(/(?<=直线)\s*6(?=上|与|和|,|，|$)/g, "b")
    .replace(/直线\s*6/g, "直线b")
    .replace(/RIA([A-Z]{3,4})/g, "Rt△$1")
    .replace(/RtA([A-Z]{3,4})/g, "Rt△$1")
    .replace(/等腰直\s*角\s*△/g, "等腰直角△")
    .replace(/\bA([A-Z]{3,4})\b/g, "△$1")
    .replace(/\bL([A-Z0-9]{1,4})/g, "∠$1")
    .replace(/∠A=/g, "∠A=")
    .replace(/角([A-Z0-9]{1,4})/g, "∠$1")
    .replace(/三角形\s*([A-Z]{3,4})/g, "△$1")
    .replace(/等腰直\s*角\s*△/g, "等腰直角△")
    .replace(/因为/g, "∵")
    .replace(/所以/g, "∴")
    .replace(/趋于/g, "→")
    .replace(/不等于/g, "≠")
    .replace(/垂直/g, "⊥")
    .replace(/平行/g, "∥")
    .replace(/sqrt\s*\(/gi, "√(")
    .replace(/\\sqrt\s*\{([^}]*)\}/g, "√($1)")
    .replace(/\\frac\s*\{([^}]*)\}\s*\{([^}]*)\}/g, (_, numerator, denominator) => {
      const simple = /^-?\d+(?:\.\d+)?$/.test(numerator) && /^[0-9a-zA-Z]+$/.test(denominator);
      return simple ? `${numerator}/${denominator}` : `(${numerator})/(${denominator})`;
    })
    .replace(/\\\[/g, "[")
    .replace(/\\\]/g, "]")
    .replace(/\\\(/g, "(")
    .replace(/\\\)/g, ")")
    .replace(/\\\{/g, "{")
    .replace(/\\\}/g, "}")
    .replace(/([a-zA-Z])\s*'\s*\(/g, "$1′(")
    .replace(/([a-zA-Z])\s*'\s*([0-9a-zA-Z])/g, "$1′$2")
    .replace(/d\s*([xy])\s*\/\s*d\s*([xy])/gi, "d$1/d$2")
    .replace(/(\d+(?:\.\d+)?)\s*[xX]\s*10\s*\^\s*([+-]?\d+)/g, "$1×10^$2")
    .replace(/([×xX]\s*10)\s*\^\s*([+-]?\d+)/g, (_, prefix, power) => `${prefix.replace(/[xX]/, "×").replace(/\s+/g, "")}${toSuperscriptDigits(power)}`)
    .replace(/abs\s*\(([^)]*)\)/gi, "|$1|")
    .replace(/\^2\b/g, "²")
    .replace(/\^3\b/g, "³")
    .replace(/e\^2/g, "e²")
    .replace(/\((e²-1)\)\/\((e²\+1)\)/g, "($1)/($2)")
    .replace(/√\s*\(\s*([^)]+?)\s*\)\s*\/\s*\(?\s*([^)]+?)\s*\)?/g, "√$1/$2")
    .replace(/\*/g, "×")
    .replace(/<=/g, "≤")
    .replace(/>=/g, "≥")
    .replace(/!=/g, "≠")
    .replace(/<>/g, "≠")
    .replace(/->/g, "→")
    .replace(/\/\//g, "∥")
    .replace(/([0-9A-Za-z)\]）⁰¹²³⁴⁵⁶⁷⁸⁹])。$/g, "$1");
  if (/^\s*[：:]\s*[A-Z∠△√0-9(]/.test(value)) value = value.replace(/^\s*[：:]\s*/, "∴ ");
  if (/^\s*\.?[：:]\s*/.test(value) && /得|故|可知|所以|∴/.test(value)) value = value.replace(/^\s*\.?[：:]\s*/, "∴ ");
  return value;
}

function isLikelyMathLine(line) {
  return /[=+\-×÷*/^²³√|≤≥≈≠∞π∫∂′→∵∴∠△⊥∥(){}[\]0-9]|\b(?:lim|ln|sin|cos|tan|log|exp|dx|dy)\b/.test(line);
}

function renderOcrQuality() {
  const ocr = state.ocrMeta || {};
  const avg = Number(ocr.average_confidence || 0);
  const percent = avg ? Math.round(avg * 100) : 0;
  const hasOcrConfidence = percent > 0 && Number(ocr.line_count || 0) > 0;
  const quality = percent >= 85 ? "高" : percent >= 65 ? "中" : percent ? "低" : "未知";
  const source = state.llmMeta?.source || "";
  const sourceLabel = source.includes("vision") ? "视觉模型" : source === "cloud" ? "云端模型" : source === "local" ? "本地模型" : "大模型";
  const llmText = state.llmMeta?.message ? `<span>${sourceLabel}：${escapeHtml(state.llmMeta.message)}</span>` : "";
  const timings = state.lastOcrTarget === "reference" ? state.referenceTimings : state.lastOcrTarget === "submission" ? state.submissionTimings : [];
  const timingText = renderTimingSummary(timings);
  const ocrText = hasOcrConfidence
    ? `<span>OCR 准确性：${quality}（约 ${percent}%）</span><span>低置信行：${ocr.low_confidence_count || 0}/${ocr.line_count || 0}</span>`
    : `<span>OCR 准确性：未生成置信度</span><span>当前主要依据视觉模型直接看图</span>`;
  const reviewText = hasOcrConfidence && percent < 75 ? `<span>建议人工复核手写/低置信答案</span>` : "";
  return `
    <div class="ocr-quality">
      ${ocrText}
      ${llmText}
      ${timingText}
      ${reviewText}
    </div>
  `;
}

function renderTimingSummary(timings) {
  if (!Array.isArray(timings) || !timings.length) return "";
  const total = timings.find((item) => item.stage === "total");
  const slowest = timings
    .filter((item) => item.stage !== "total")
    .sort((a, b) => Number(b.seconds || 0) - Number(a.seconds || 0))[0];
  const totalText = total ? `总耗时 ${formatSeconds(total.seconds)}` : "";
  const slowText = slowest ? `最慢：${formatStageName(slowest.stage)} ${formatSeconds(slowest.seconds)}` : "";
  return `<span>${escapeHtml([totalText, slowText].filter(Boolean).join("，"))}</span>`;
}

function formatSeconds(value) {
  const seconds = Number(value || 0);
  if (seconds >= 60) return `${Math.round(seconds)} 秒`;
  return `${seconds.toFixed(seconds >= 10 ? 0 : 1)} 秒`;
}

function formatStageName(stage) {
  const names = {
    pdf_render: "PDF 转图",
    ocr: "本地 OCR",
    ocr_fallback: "OCR 回退",
    question_structure: "题目解析",
    student_structure: "学生答案解析",
    vision_submission_bundle: "学生卷视觉合并解析",
    vision_student_fallback: "学生答案回退解析",
    vision_question_fallback: "题目回退解析",
    text_question_fallback: "文本题目回退",
    text_student_fallback: "文本学生回退",
    zip_extract_ocr_render: "ZIP 解包",
  };
  return names[stage] || stage;
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function renderStudentSelector() {
  const select = byId("studentSelect");
  select.innerHTML = state.results
    .map((result) => `<option value="${result.student}" ${result.student === state.activeStudent ? "selected" : ""}>${result.student}</option>`)
    .join("");
}

function renderEvidencePreview(item) {
  if (!item.reviewRequired || !state.submissionEvidenceUrl) return "";
  const evidenceId = `${item.student || ""}:${item.question?.id || ""}`;
  const name = escapeHtml(state.submissionEvidenceName || "学生原始答卷");
  const isImage = /^image\//.test(state.submissionEvidenceType || "");
  const preview = isImage
    ? `<img src="${state.submissionEvidenceUrl}" alt="${name}" />`
    : `<iframe src="${state.submissionEvidenceUrl}" title="${name}"></iframe>`;
  return `
    <details class="evidence-panel" data-evidence-id="${escapeHtml(evidenceId)}"${state.expandedEvidenceIds.has(evidenceId) ? " open" : ""}>
      <summary>查看原始答卷证据</summary>
      <div>
        <p>当前展示原始上传文件，题块自动裁剪需要题目坐标识别，后续可继续增强。</p>
        ${preview}
      </div>
    </details>
  `;
}

function updateManualScore(input) {
  const result = state.results.find((item) => item.student === state.activeStudent);
  if (!result) return;
  const questionId = input.dataset.scoreQuestion;
  const item = result.items.find((entry) => entry.question.id === questionId);
  if (!item) return;
  const value = parseDecimalInput(input.value);
  if (!Number.isFinite(value)) return;
  const maxScore = parseDecimalInput(input.dataset.scoreMax || item.maxScore);
  item.score = Math.max(0, Math.min(value, Number.isFinite(maxScore) && maxScore > 0 ? maxScore : value));
  item.status = "老师已改分";
  item.reviewRequired = false;
  item.confidence = 1;
  item.teacherAdjusted = true;
  item.feedback = "老师已人工确认分数。";
  renderResults();
  renderAnalytics();
}

function getResultCardClass(item) {
  if (item.status === "自动判错") return "auto wrong";
  if (item.status === "自动通过" || item.status === "自动辅助通过") return "auto correct";
  return item.mode;
}

function getResultStatusClass(item) {
  if (item.status === "自动判错") return "danger";
  if (item.status === "自动通过" || item.status === "自动辅助通过" || item.status === "老师已改分") return "ready";
  if (item.mode === "assist") return "warning";
  return "danger";
}

function renderReferenceStandardBlock(item) {
  const answer = String(item.question?.answer ?? "").trim();
  const rubric = item.question?.rubric || [];
  const keywords = item.question?.keywords || [];
  const standards = rubric.length ? rubric : keywords;
  if (!answer && !standards.length) {
    return `
      <div class="reference-standard-block is-missing">
        <div>
          <span>参考答案</span>
          <strong>未识别到最终正确答案</strong>
        </div>
        <div>
          <span>评分标准</span>
          <strong>未识别到评分点，请老师先复核题目列表。</strong>
        </div>
      </div>
    `;
  }
  return `
    <div class="reference-standard-block">
      <div>
        <span>参考答案</span>
        <strong>${answer ? escapeHtml(formatMathText(answer)) : "未识别到最终正确答案"}</strong>
      </div>
      <div>
        <span>评分标准</span>
        <strong>${standards.length ? escapeHtml(standards.map(formatMathText).join("；")) : "未识别到评分点"}</strong>
      </div>
    </div>
  `;
}

function renderResults() {
  renderStudentSelector();
  const result = state.results.find((item) => item.student === state.activeStudent);
  if (!result) {
    byId("studentSummary").innerHTML = `<p class="empty">暂无批改结果，请先上传文件并运行批改。</p>`;
    byId("resultList").innerHTML = "";
    return;
  }
  const score = result.items.reduce((sum, item) => sum + item.score, 0);
  const max = result.items.reduce((sum, item) => sum + item.maxScore, 0);
  const reviewCount = result.items.filter((item) => item.reviewRequired).length;
  byId("studentSummary").innerHTML = `
    <div><span>学生</span><strong>${result.student}</strong></div>
    <div><span>得分</span><strong>${score}/${max}</strong></div>
    <div><span>得分率</span><strong>${max ? Math.round((score / max) * 100) : 0}%</strong></div>
    <div><span>需复核</span><strong>${reviewCount} 题</strong></div>
  `;
  byId("resultList").innerHTML = result.items
    .map(
      (item) => `
        <article class="result-card ${getResultCardClass(item)}" id="${escapeHtml(getResultAnchorId(item.student, item.question.id))}" data-result-student="${escapeHtml(item.student)}" data-result-question="${escapeHtml(item.question.id)}">
          <div class="result-card-head">
            <div>
              <strong>${escapeHtml(getQuestionMetaText(item.question))}</strong>
              <span>${escapeHtml(formatMathText(item.question.title || "待确认题目"))}</span>
            </div>
            <span class="status-pill ${getResultStatusClass(item)}">${item.status}</span>
          </div>
          <div class="result-meta">
            <div><span>学生答案</span><strong>${escapeHtml(formatMathText(item.answer || "未作答"))}</strong></div>
            <div><span>得分</span><strong>${item.score}/${item.maxScore}</strong></div>
            <div><span>置信度</span><strong>${Math.round(item.confidence * 100)}%</strong></div>
          </div>
          <div class="teacher-score-row">
            <label>
              <span>老师改分</span>
              <input data-score-question="${escapeHtml(item.question.id)}" data-score-max="${escapeHtml(item.maxScore || "")}" type="text" inputmode="decimal" value="${escapeHtml(item.score)}" />
            </label>
          </div>
          ${renderEvidencePreview(item)}
          ${renderReferenceStandardBlock(item)}
          <p><b>AI判断依据：</b>${escapeHtml(formatMathText(item.evidence))}</p>
          <p><b>反馈：</b>${escapeHtml(formatMathText(item.feedback))}</p>
        </article>
      `,
    )
    .join("");
}

function buildAnalytics() {
  const allItems = state.results.flatMap((result) => result.items);
  const missingMap = new Map();
  allItems.forEach((item) => {
    (item.missing || []).forEach((point) => {
      missingMap.set(point, (missingMap.get(point) || 0) + 1);
    });
  });
  const topMissing = [...missingMap.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5);
  const autoWrong = allItems.filter((item) => item.mode === "auto" && item.score < item.maxScore);
  const assistReview = allItems.filter((item) => item.mode === "assist");
  return [
    {
      title: "自动题错因",
      text: autoWrong.length ? `${autoWrong.length} 处自动题答错，建议优先讲解 ${autoWrong[0].question.knowledge || autoWrong[0].question.title || "高频错题"}。` : "自动题整体完成较好。",
    },
    {
      title: "主观题复核压力",
      text: `${assistReview.length} 处主观题已生成辅助初评，需要教师确认建议分和评语。`,
    },
    {
      title: "高频遗漏采分点",
      text: topMissing.length ? topMissing.map(([point, count]) => `${point}（${count} 次）`).join("、") : "暂未发现明显遗漏采分点。",
    },
  ];
}

function renderAnalytics() {
  byId("analysisList").innerHTML = buildAnalytics()
    .map((item) => `<article class="insight-item"><strong>${item.title}</strong><p>${item.text}</p></article>`)
    .join("");
  const queue = state.results
    .flatMap((result) => result.items)
    .filter((item) => item.reviewRequired);
  byId("reviewQueue").innerHTML = queue.length
    ? queue
        .map(
          (item) => `
            <article class="review-jump-card" role="button" tabindex="0" data-review-student="${escapeHtml(item.student)}" data-review-question="${escapeHtml(item.question.id)}" title="跳转到批改结果中的 ${escapeHtml(item.question.id)}">
              <strong>${escapeHtml(item.student)} · ${escapeHtml(item.question.id)} · ${escapeHtml(item.status)}</strong>
              <span>${escapeHtml(formatMathText(item.evidence))}</span>
            </article>
          `,
        )
        .join("")
    : `<p class="empty">暂无需要复核的题目。</p>`;
}

function getResultAnchorId(student, questionId) {
  return `result-${slugifyId(student)}-${slugifyId(questionId)}`;
}

function slugifyId(value) {
  return String(value ?? "")
    .trim()
    .replace(/[^\w\u4e00-\u9fa5-]+/g, "-")
    .replace(/^-+|-+$/g, "") || "item";
}

function jumpToReviewResult(student, questionId) {
  const result = state.results.find((item) => item.student === student);
  if (!result) {
    showToast("没有找到对应学生的批改结果。");
    return;
  }
  state.activeStudent = student;
  switchView("results");
  renderResults();
  const card = document.getElementById(getResultAnchorId(student, questionId));
  if (!card) {
    showToast("没有找到对应题目的批改卡片。");
    return;
  }
  card.scrollIntoView({ behavior: "smooth", block: "center" });
  card.classList.add("is-targeted");
  window.setTimeout(() => card.classList.remove("is-targeted"), 1800);
}

function renderStatuses() {
  const referenceStatus = byId("referenceStatus");
  const submissionStatus = byId("submissionStatus");
  renderExtractProgress("reference");
  renderExtractProgress("submission");
  if (state.referenceUploading) {
    referenceStatus.textContent = formatProgressStatus(state.referenceProgress);
    referenceStatus.className = "status-pill warning";
  } else if (state.questions.length) {
    referenceStatus.textContent = state.referenceConfirmed ? `已确认 ${state.questions.length} 题` : `待确认 ${state.questions.length} 题`;
    referenceStatus.className = state.referenceConfirmed ? "status-pill ready" : "status-pill warning";
  } else if (state.referenceUploaded) {
    referenceStatus.textContent = "已上传，待补题目";
    referenceStatus.className = "status-pill warning";
  } else {
    referenceStatus.textContent = "未上传";
    referenceStatus.className = "status-pill";
  }

  if (state.submissionUploading) {
    submissionStatus.textContent = formatProgressStatus(state.submissionProgress);
    submissionStatus.className = "status-pill warning";
  } else if (state.students.length) {
    submissionStatus.textContent = `已解析 ${state.students.length} 人`;
    submissionStatus.className = "status-pill ready";
  } else if (state.submissionUploaded) {
    submissionStatus.textContent = "已上传，待解析";
    submissionStatus.className = "status-pill warning";
  } else {
    submissionStatus.textContent = "未上传";
    submissionStatus.className = "status-pill";
  }
}

function formatProgressStatus(progress) {
  const percent = Math.round(Number(progress?.percent || 0));
  return percent > 0 && percent < 100 ? `解析 ${percent}%` : "解析中...";
}

function renderExtractProgress(target) {
  const box = byId(target === "reference" ? "referenceProgress" : "submissionProgress");
  if (!box) return;
  const progress = target === "reference" ? state.referenceProgress : state.submissionProgress;
  const uploading = target === "reference" ? state.referenceUploading : state.submissionUploading;
  if (!uploading || !progress) {
    box.hidden = true;
    box.innerHTML = "";
    return;
  }
  const percent = Math.max(1, Math.min(100, Math.round(Number(progress.percent || 1))));
  const message = progress.message || "正在解析...";
  const elapsed = Number(progress.elapsed || 0);
  box.hidden = false;
  box.innerHTML = `
    <div class="progress-row">
      <span>${escapeHtml(message)}</span>
      <strong>${percent}%</strong>
    </div>
    <div class="progress-track" aria-hidden="true"><span style="width: ${percent}%"></span></div>
    <div class="progress-meta">${elapsed ? `已用 ${Math.round(elapsed)} 秒` : "正在准备"}</div>
  `;
}

function renderAll() {
  renderMetrics();
  renderPreview();
  renderResults();
  renderAnalytics();
  renderStatuses();
}

function switchView(viewId) {
  document.querySelectorAll(".view").forEach((view) => view.classList.toggle("active", view.id === viewId));
  document.querySelectorAll(".nav-item").forEach((button) => button.classList.toggle("active", button.dataset.view === viewId));
}

async function readFile(file) {
  if (!file) return "";
  return file.text();
}

function resetTransientUiState() {
  state.expandedQuestionIds = new Set();
  state.expandedEvidenceIds = new Set();
  state.scoreAuditOpen = false;
  state.typeScoreDrafts = {};
  state.expectedTotalScore = "";
  state.ocrSelectionStart = 0;
  state.ocrSelectionEnd = 0;
}

function setExample() {
  state.questions = exampleQuestions.map((item, index) => normalizeQuestion(item, index));
  state.students = exampleStudents.map(normalizeStudent);
  byId("referenceName").textContent = "已载入示例参考答案";
  byId("submissionName").textContent = "已载入示例学生作业";
  state.results = [];
  state.activeStudent = "";
  state.ocrText = "";
  state.referenceOcrText = "";
  state.referenceOcrMeta = null;
  state.referenceLlmMeta = null;
  state.submissionOcrText = "";
  state.submissionOcrMeta = null;
  state.submissionLlmMeta = null;
  state.referenceUploaded = true;
  state.submissionUploaded = true;
  state.referenceConfirmed = false;
  state.referenceProgress = null;
  state.submissionProgress = null;
  resetTransientUiState();
  renderAll();
  showToast("示例文件已载入，可以点击“运行批改”。");
}

function clearAll() {
  if (state.submissionEvidenceUrl) URL.revokeObjectURL(state.submissionEvidenceUrl);
  state.questions = [];
  state.students = [];
  state.results = [];
  state.activeStudent = "";
  state.ocrText = "";
  state.lastOcrTarget = "";
  state.ocrMeta = null;
  state.llmMeta = null;
  state.referenceOcrText = "";
  state.referenceOcrMeta = null;
  state.referenceLlmMeta = null;
  state.submissionOcrText = "";
  state.submissionOcrMeta = null;
  state.submissionLlmMeta = null;
  state.submissionEvidenceUrl = "";
  state.submissionEvidenceName = "";
  state.submissionEvidenceType = "";
  state.referenceUploaded = false;
  state.submissionUploaded = false;
  state.referenceUploading = false;
  state.submissionUploading = false;
  state.referenceProgress = null;
  state.submissionProgress = null;
  state.referenceConfirmed = false;
  resetTransientUiState();
  byId("referenceFile").value = "";
  byId("submissionFile").value = "";
  byId("referenceName").textContent = "支持 JSON / CSV / TXT / MD";
  byId("submissionName").textContent = "支持多学生作答";
  renderAll();
  showToast("已清空上传内容和批改结果。");
}

function reparseOcrText(target) {
  const editor = byId("ocrEditor");
  const text = editor ? editor.value : state.ocrText;
  state.ocrText = text;
  if (target === "reference") {
    state.expandedQuestionIds = new Set();
    state.typeScoreDrafts = {};
    state.questions = parseReference(text, "ocr-corrected.txt");
    state.referenceConfirmed = false;
    state.results = [];
    state.activeStudent = "";
    renderAll();
    showToast(`已按参考答案重新解析：${state.questions.length} 道题。`);
    return;
  }
  state.students = parseStudentOcr(text, "ocr-corrected.txt");
  state.results = [];
  state.activeStudent = "";
  renderAll();
  showToast(`已按学生作业重新解析：${state.students.length} 人。`);
}

function updateQuestionFromEditor(element) {
  const card = element.closest("[data-question-index]");
  if (!card) return;
  const index = Number(card.dataset.questionIndex);
  const question = state.questions[index];
  if (!question) return;
  const field = element.dataset.questionField;
  const value = element.value;
  const oldId = question.id;
  if (field === "score") {
    const score = parseDecimalInput(value);
    question.score = Number.isFinite(score) ? score : 0;
  } else if (field === "rubric") {
    question.rubric = splitList(value);
    question.keywords = question.keywords?.length ? question.keywords : question.rubric;
  } else if (field) {
    question[field] = value;
  }
  if (field === "id" && oldId !== question.id) {
    state.expandedQuestionIds.delete(oldId);
    card.dataset.questionId = question.id;
  }
  if (card.open) state.expandedQuestionIds.add(question.id);
  state.results = [];
  state.activeStudent = "";
  state.referenceConfirmed = false;
  updateQuestionSummary(card, question);
  renderMetrics();
  renderResults();
  renderStatuses();
}

function confirmReferenceQuestions() {
  if (!state.questions.length) {
    showToast("尚未解析题目，无法确认。");
    return;
  }
  state.referenceConfirmed = true;
  state.results = [];
  state.activeStudent = "";
  renderAll();
  showToast("题目、分值、参考答案和评分点已确认，可以运行批改。");
}

function applyTypeScore(button) {
  const row = button.closest("[data-score-type]");
  const input = row?.querySelector("[data-type-score-input]");
  const typeLabel = row?.dataset.scoreType || "";
  const score = parseDecimalInput(input?.value || "");
  if (!typeLabel || !(score > 0)) {
    showToast("请先填写有效的每题分值。");
    return;
  }
  let count = 0;
  state.questions.forEach((question) => {
    if (getQuestionTypeLabel(question.type) !== typeLabel) return;
    question.score = score;
    count += 1;
  });
  state.referenceConfirmed = false;
  state.results = [];
  state.activeStudent = "";
  renderAll();
  showToast(`已将 ${typeLabel} 的 ${count} 道题统一设置为每题 ${score} 分。`);
}

function updateQuestionSummary(card, question) {
  const summary = card.querySelector(".question-summary");
  if (!summary) return;
  const title = summary.querySelector(".question-summary-main span");
  const meta = summary.querySelector(".question-summary-meta");
  const strong = summary.querySelector(".question-summary-main strong");
  if (strong) strong.textContent = getQuestionMetaText(question);
  if (title) title.textContent = formatQuestionPreview(formatMathText(question.title || "待确认题目"), 56);
  if (meta) {
    const scorePreview = question.score ? `${question.score} 分` : "未识别到分值";
    const answerPreview = formatQuestionPreview(formatMathText(question.answer || "未填参考答案"), 44);
    const rubricPreview = question.rubric?.length ? `${question.rubric.length} 个评分点` : "未识别到评分点";
    meta.innerHTML = `
      <span>${escapeHtml(scorePreview)}</span>
      <span>答案：${escapeHtml(answerPreview)}</span>
      <span>${escapeHtml(rubricPreview)}</span>
      <b>编辑</b>
    `;
  }
}

async function reparseOcrTextWithModel(button) {
  const editor = byId("ocrEditor");
  const text = editor ? editor.value : state.ocrText;
  if (!text.trim()) {
    showToast("OCR 文本为空，无法重新解析。");
    return;
  }
  const originalText = button?.textContent || "";
  const target = getLlmReparseTarget();
  if (button) {
    button.disabled = true;
    button.textContent = target === "submission" ? "正在解析学生作业..." : "正在解析参考答案...";
  }
  showToast(target === "submission" ? "正在用大模型解析学生作业 OCR 文本，可能需要几分钟。" : "正在用大模型解析参考答案 OCR 文本，可能需要几分钟。");
  try {
    const payload = await structureOcrText(text, target);
    state.ocrText = text;
    state.llmMeta = payload.llm || null;
    if (target === "submission") {
      const modelStudents = (payload.students || []).map(normalizeStudent).filter((item) => Object.keys(item.answers || {}).length);
      state.students = modelStudents.length ? modelStudents : parseStudentOcr(text, "ocr-corrected.txt");
      state.submissionOcrText = text;
      state.submissionLlmMeta = state.llmMeta;
    } else {
      state.expandedQuestionIds = new Set();
      state.typeScoreDrafts = {};
      state.questions = (payload.questions || []).map(normalizeQuestion);
      state.referenceConfirmed = false;
      state.referenceOcrText = text;
      state.referenceLlmMeta = state.llmMeta;
    }
    state.results = [];
    state.activeStudent = "";
    renderAll();
    if (payload.warning) showToast(payload.warning);
    else showToast(target === "submission" ? `大模型解析学生作业完成：${state.students.length} 人。` : `大模型解析参考答案完成：${state.questions.length} 道题。`);
  } catch (error) {
    showToast(error.message);
  } finally {
    const currentButton = byId("ocrPreview").querySelector("[data-ocr-llm-reparse]");
    if (currentButton) {
      currentButton.disabled = false;
      currentButton.textContent = originalText || getLlmReparseButtonText();
    }
  }
}

function insertMathToken(token) {
  const editor = byId("ocrEditor");
  if (!editor) return;
  const canUseLiveSelection = document.activeElement === editor && typeof editor.selectionStart === "number";
  const start = canUseLiveSelection ? editor.selectionStart : state.ocrSelectionStart ?? editor.value.length;
  const end = canUseLiveSelection ? editor.selectionEnd : state.ocrSelectionEnd ?? start;
  const before = editor.value.slice(0, start);
  const after = editor.value.slice(end);
  editor.value = before + token + after;
  const cursor = start + token.length;
  editor.focus();
  editor.setSelectionRange(cursor, cursor);
  state.ocrSelectionStart = cursor;
  state.ocrSelectionEnd = cursor;
  updateMathPreviewFromEditor();
}

function updateMathPreviewFromEditor() {
  const editor = byId("ocrEditor");
  if (!editor) return;
  state.ocrText = editor.value;
  state.ocrSelectionStart = editor.selectionStart ?? state.ocrSelectionStart;
  state.ocrSelectionEnd = editor.selectionEnd ?? state.ocrSelectionEnd;
}

function rememberOcrSelection() {
  const editor = byId("ocrEditor");
  if (!editor) return;
  state.ocrSelectionStart = editor.selectionStart ?? state.ocrSelectionStart;
  state.ocrSelectionEnd = editor.selectionEnd ?? state.ocrSelectionEnd;
}

function saveCurrentOcrEditor() {
  const editor = byId("ocrEditor");
  if (!editor || !state.lastOcrTarget) return;
  state.ocrText = editor.value;
  if (state.lastOcrTarget === "reference") state.referenceOcrText = editor.value;
  if (state.lastOcrTarget === "submission") state.submissionOcrText = editor.value;
}

function showOcrTarget(target) {
  saveCurrentOcrEditor();
  if (target === "reference") {
    state.ocrText = state.referenceOcrText;
    state.ocrMeta = state.referenceOcrMeta;
    state.llmMeta = state.referenceLlmMeta;
    state.lastOcrTarget = state.referenceOcrText ? "reference" : state.lastOcrTarget;
  } else {
    state.ocrText = state.submissionOcrText;
    state.ocrMeta = state.submissionOcrMeta;
    state.llmMeta = state.submissionLlmMeta;
    state.lastOcrTarget = state.submissionOcrText ? "submission" : state.lastOcrTarget;
  }
  renderAll();
}

function downloadReport() {
  if (!state.results.length) {
    showToast("暂无可导出的批改结果。");
    return;
  }
  const report = {
    generatedAt: new Date().toISOString(),
    questions: state.questions,
    evidence: {
      submissionFile: state.submissionEvidenceName,
      type: state.submissionEvidenceType,
    },
    results: state.results,
    analytics: buildAnalytics(),
  };
  const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "ai-grading-report.json";
  link.click();
  URL.revokeObjectURL(url);
}

function bindEvents() {
  document.querySelectorAll(".nav-item").forEach((button) => {
    button.addEventListener("click", () => switchView(button.dataset.view));
  });

  byId("referenceFile").addEventListener("click", (event) => {
    event.target.value = "";
  });
  byId("submissionFile").addEventListener("click", (event) => {
    event.target.value = "";
  });

  byId("referenceFile").addEventListener("change", async (event) => {
    const file = event.target.files[0];
    if (!file) return;
    setUploadState("reference", true);
    byId("referenceName").textContent = `${file.name}（解析中...）`;
    showToast("参考答案正在上传和解析，请稍等。");
    try {
      state.expandedQuestionIds = new Set();
      state.scoreAuditOpen = false;
      state.typeScoreDrafts = {};
      state.expectedTotalScore = "";
      if (isOcrFile(file)) {
        const payload = await extractFile(file, "reference");
        state.ocrText = payload.text || "";
        state.ocrMeta = payload.ocr || null;
        state.llmMeta = payload.llm || null;
        state.referenceTimings = payload.timings || [];
        state.lastOcrTarget = "reference";
        state.referenceOcrText = state.ocrText;
        state.referenceOcrMeta = state.ocrMeta;
        state.referenceLlmMeta = state.llmMeta;
        state.questions = (payload.questions || []).map(normalizeQuestion);
        if (!state.questions.length && state.ocrText) {
          state.questions = parseReference(state.ocrText, `${file.name}.txt`);
        }
        if (state.questions.length) {
          state.ocrText = questionsToReadableText(state.questions) || state.ocrText;
          state.referenceOcrText = state.ocrText;
        }
        if (payload.warning) showToast(payload.warning);
      } else {
        const text = await readFile(file);
        state.ocrText = "";
        state.ocrMeta = null;
        state.llmMeta = null;
        state.referenceTimings = [];
        state.lastOcrTarget = "";
        state.referenceOcrText = "";
        state.referenceOcrMeta = null;
        state.referenceLlmMeta = null;
        state.questions = parseReference(text, file.name);
      }
      state.referenceUploaded = true;
      state.referenceConfirmed = false;
      state.results = [];
      state.activeStudent = "";
      byId("referenceName").textContent = file.name;
      renderAll();
      showToast(`参考答案已解析：${state.questions.length} 道题。`);
    } catch (error) {
      showToast(error.message);
    } finally {
      setUploadState("reference", false);
    }
  });

  byId("submissionFile").addEventListener("change", async (event) => {
    const file = event.target.files[0];
    if (!file) return;
    if (state.submissionEvidenceUrl) URL.revokeObjectURL(state.submissionEvidenceUrl);
    state.submissionEvidenceUrl = URL.createObjectURL(file);
    state.submissionEvidenceName = file.name;
    state.submissionEvidenceType = file.type || (file.name.toLowerCase().endsWith(".pdf") ? "application/pdf" : "");
    setUploadState("submission", true);
    byId("submissionName").textContent = `${file.name}（解析中...）`;
    showToast("学生作业正在上传和解析，请稍等。");
    try {
      state.expandedEvidenceIds = new Set();
      let submissionPayload = null;
      const shouldSupplementQuestions = needsQuestionStructure();
      if (isOcrFile(file)) {
        const payload = await extractFile(file, "submission", { needQuestions: shouldSupplementQuestions });
        submissionPayload = payload;
        state.ocrText = payload.text || "";
        state.ocrMeta = payload.ocr || null;
        state.llmMeta = payload.llm || null;
        state.submissionTimings = payload.timings || [];
        state.lastOcrTarget = "submission";
        state.submissionOcrText = state.ocrText;
        state.submissionOcrMeta = state.ocrMeta;
        state.submissionLlmMeta = state.llmMeta;
        if (shouldSupplementQuestions && Array.isArray(payload.questions) && payload.questions.length) {
          state.questions = mergeQuestionStructures(state.questions, payload.questions.map(normalizeQuestion));
          state.referenceConfirmed = false;
        }
        state.students = parseStudentExtractPayload(payload, file.name);
      } else {
        const text = await readFile(file);
        state.ocrText = "";
        state.ocrMeta = null;
        state.llmMeta = null;
        state.submissionTimings = [];
        state.lastOcrTarget = "";
        state.submissionOcrText = "";
        state.submissionOcrMeta = null;
        state.submissionLlmMeta = null;
        state.students = parseStudents(text, file.name);
      }
      state.submissionUploaded = true;
      state.results = [];
      state.activeStudent = "";
      byId("submissionName").textContent = file.name;
      renderAll();
      const questionText = submissionPayload?.questions?.length ? `，并补充解析 ${submissionPayload.questions.length} 道题` : "";
      showToast(`学生作业已解析：${state.students.length} 人${questionText}。`);
    } catch (error) {
      showToast(error.message);
    } finally {
      setUploadState("submission", false);
    }
  });

  byId("ocrPreview").addEventListener("click", (event) => {
    const switchButton = event.target.closest("[data-show-ocr]");
    if (switchButton) {
      showOcrTarget(switchButton.dataset.showOcr);
      return;
    }
    const mathButton = event.target.closest("[data-insert-math]");
    if (mathButton) {
      insertMathToken(mathButton.dataset.insertMath || "");
      return;
    }
    const llmButton = event.target.closest("[data-ocr-llm-reparse]");
    if (llmButton) {
      reparseOcrTextWithModel(llmButton);
      return;
    }
    const target = event.target.closest("[data-ocr-reparse]");
    if (!target) return;
    reparseOcrText(target.dataset.ocrReparse);
  });
  byId("ocrPreview").addEventListener("mousedown", (event) => {
    if (event.target.closest("[data-insert-math]")) {
      event.preventDefault();
    }
  });
  byId("ocrPreview").addEventListener("input", (event) => {
    if (event.target.id === "ocrEditor") updateMathPreviewFromEditor();
  });
  byId("ocrPreview").addEventListener("keyup", (event) => {
    if (event.target.id === "ocrEditor") rememberOcrSelection();
  });
  byId("ocrPreview").addEventListener("mouseup", (event) => {
    if (event.target.id === "ocrEditor") rememberOcrSelection();
  });
  byId("ocrPreview").addEventListener("select", (event) => {
    if (event.target.id === "ocrEditor") rememberOcrSelection();
  });
  byId("questionPreview").addEventListener("input", (event) => {
    if (event.target.matches("[data-expected-total-score]")) {
      state.expectedTotalScore = event.target.value;
      state.referenceConfirmed = false;
      return;
    }
    if (event.target.matches("[data-type-score-input]")) {
      const key = event.target.dataset.typeScoreKey || "";
      if (key) state.typeScoreDrafts[key] = event.target.value;
      return;
    }
    const target = event.target.closest("[data-question-field]");
    if (target) {
      updateQuestionFromEditor(target);
    }
  });
  byId("questionPreview").addEventListener("change", (event) => {
    if (event.target.matches("[data-expected-total-score]")) {
      state.expectedTotalScore = event.target.value;
      state.referenceConfirmed = false;
      renderPreview();
      renderStatuses();
      return;
    }
    if (event.target.matches("[data-type-score-input]")) {
      const key = event.target.dataset.typeScoreKey || "";
      if (key) state.typeScoreDrafts[key] = event.target.value;
      return;
    }
    const target = event.target.closest("[data-question-field]");
    if (target) {
      updateQuestionFromEditor(target);
      renderPreview();
    }
  });
  byId("questionPreview").addEventListener("toggle", (event) => {
    const auditPanel = event.target.closest?.(".score-audit-panel");
    if (auditPanel) {
      state.scoreAuditOpen = auditPanel.open;
      return;
    }
    const card = event.target.closest?.(".question-edit-card");
    if (!card) return;
    const questionId = card.dataset.questionId || state.questions[Number(card.dataset.questionIndex)]?.id;
    if (!questionId) return;
    if (card.open) state.expandedQuestionIds.add(questionId);
    else state.expandedQuestionIds.delete(questionId);
  }, true);
  byId("questionPreview").addEventListener("click", (event) => {
    const applyScoreButton = event.target.closest("[data-apply-type-score]");
    if (applyScoreButton) {
      applyTypeScore(applyScoreButton);
      return;
    }
    const button = event.target.closest("[data-confirm-reference]");
    if (button) confirmReferenceQuestions();
  });

  byId("runGrading").addEventListener("click", runGrading);
  byId("loadExample").addEventListener("click", setExample);
  byId("clearAll").addEventListener("click", clearAll);
  byId("downloadReport").addEventListener("click", downloadReport);
  byId("studentSelect").addEventListener("change", (event) => {
    state.activeStudent = event.target.value;
    renderResults();
  });
  byId("reviewQueue").addEventListener("click", (event) => {
    const card = event.target.closest("[data-review-student][data-review-question]");
    if (!card) return;
    jumpToReviewResult(card.dataset.reviewStudent, card.dataset.reviewQuestion);
  });
  byId("reviewQueue").addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const card = event.target.closest("[data-review-student][data-review-question]");
    if (!card) return;
    event.preventDefault();
    jumpToReviewResult(card.dataset.reviewStudent, card.dataset.reviewQuestion);
  });
  byId("resultList").addEventListener("change", (event) => {
    const input = event.target.closest("[data-score-question]");
    if (input) updateManualScore(input);
  });
  byId("resultList").addEventListener("toggle", (event) => {
    const panel = event.target.closest?.(".evidence-panel");
    if (!panel) return;
    const evidenceId = panel.dataset.evidenceId || "";
    if (!evidenceId) return;
    if (panel.open) state.expandedEvidenceIds.add(evidenceId);
    else state.expandedEvidenceIds.delete(evidenceId);
  }, true);
}

function parseStudentExtractPayload(payload, fileName = "") {
  if (Array.isArray(payload.students) && payload.students.length) {
    return mergeStudentsByName(payload.students.map((item, index) => withFallbackStudentName(normalizeStudent(item, index), fileName)).filter((item) => item.student));
  }
  if (payload.sections && payload.sections.length) {
    const students = payload.sections
      .map((section, index) => {
        const parsed = parseAnswerCardText(section.text || "", section.name || `${fileName}-${index + 1}`);
        if (parsed.length) return parsed;
        const answers = extractAnswerCardAnswers(section.text || "");
        return [
          {
            student: detectStudentName(section.text || "") || (section.name || `${fileName}-${index + 1}`).replace(/\.[^.]+$/, ""),
            answers,
          },
        ];
      })
      .flat()
      .filter((item) => Object.keys(item.answers || {}).length);
    if (students.length) return mergeStudentsByName(students);
  }
  return parseStudentOcr(payload.text || "", fileName);
}

function withFallbackStudentName(student, fileName = "") {
  const fallback = cleanStudentFileName(fileName) || "未知学生";
  const current = String(student.student || "").trim();
  if (!current || /^未知学生$|^学生\d+$|^OCR学生作业$/.test(current)) {
    return { ...student, student: fallback };
  }
  return student;
}

function mergeStudentsByName(students) {
  const byName = new Map();
  students.forEach((student) => {
    const name = student.student || "未知学生";
    if (!byName.has(name)) {
      byName.set(name, { student: name, answers: {} });
    }
    Object.assign(byName.get(name).answers, student.answers || {});
  });
  return [...byName.values()];
}

function init() {
  renderAll();
  bindEvents();
}

document.addEventListener("DOMContentLoaded", init);
