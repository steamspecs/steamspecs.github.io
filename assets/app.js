const REQUIREMENT_FIELDS = [
  "os",
  "cpu",
  "gpu",
  "ram_gb",
  "vram_gb",
  "storage_gb",
  "directx",
  "opengl",
  "vulkan",
  "notes",
  "raw_html"
];

const state = {
  index: null,
  filtered: [],
  selected: null,
  buildStore: null,
  specs: null,
  shardCache: new Map()
};

const els = {
  search: document.getElementById("search"),
  filter: document.getElementById("filter"),
  list: document.getElementById("list"),
  meta: document.getElementById("meta"),
  detailEmpty: document.getElementById("detailEmpty"),
  detail: document.getElementById("detail"),

  openSpecs: document.getElementById("openSpecs"),
  closeSpecs: document.getElementById("closeSpecs"),
  modal: document.getElementById("specModal"),
  backdrop: document.getElementById("modalBackdrop"),

  buildSelect: document.getElementById("buildSelect"),
  buildName: document.getElementById("buildName"),
  newBuild: document.getElementById("newBuild"),
  deleteBuild: document.getElementById("deleteBuild"),
  specCpu: document.getElementById("specCpu"),
  specGpu: document.getElementById("specGpu"),
  specRam: document.getElementById("specRam"),
  specStorage: document.getElementById("specStorage"),
  saveSpecs: document.getElementById("saveSpecs")
};

function createBuildId() {
  return `build_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

function normalizeBuildSpecs(specs) {
  return {
    cpu: cleanText(specs?.cpu) || null,
    gpu: cleanText(specs?.gpu) || null,
    ram_gb: toNumberOrNull(specs?.ram_gb),
    storage_gb: toNumberOrNull(specs?.storage_gb)
  };
}

function normalizeBuild(build, fallbackIndex = 0) {
  return {
    id: cleanText(build?.id) || createBuildId(),
    name: cleanText(build?.name) || `Build ${fallbackIndex + 1}`,
    specs: normalizeBuildSpecs(build?.specs || build)
  };
}

function defaultBuildStore() {
  return {
    version: 1,
    activeBuildId: null,
    builds: []
  };
}

function loadBuildStore() {
  try {
    const raw = localStorage.getItem("steamSpecChecker_builds");
    if (raw) {
      const parsed = JSON.parse(raw);
      const builds = Array.isArray(parsed?.builds) ? parsed.builds.map(normalizeBuild) : [];
      return {
        version: 1,
        activeBuildId: cleanText(parsed?.activeBuildId) || builds[0]?.id || null,
        builds
      };
    }

    const legacyRaw = localStorage.getItem("steamSpecChecker_specs");
    if (!legacyRaw) return defaultBuildStore();

    const legacySpecs = JSON.parse(legacyRaw);
    const legacyBuild = normalizeBuild({
      id: createBuildId(),
      name: "My PC",
      specs: legacySpecs
    });

    return {
      version: 1,
      activeBuildId: legacyBuild.id,
      builds: [legacyBuild]
    };
  } catch {
    return defaultBuildStore();
  }
}

function saveBuildStore(store) {
  localStorage.setItem("steamSpecChecker_builds", JSON.stringify(store));
  localStorage.removeItem("steamSpecChecker_specs");
}

function getActiveBuild() {
  return state.buildStore?.builds.find(build => build.id === state.buildStore.activeBuildId) || null;
}

function syncActiveSpecs() {
  state.specs = getActiveBuild()?.specs || null;
  const activeName = getActiveBuild()?.name || "Your builds";
  els.openSpecs.textContent = activeName;
}

function renderBuildOptions(selectedId) {
  const currentId = selectedId || state.buildStore?.activeBuildId || "";
  els.buildSelect.innerHTML = '<option value="">Create a new build</option>';

  for (const build of state.buildStore.builds) {
    const option = document.createElement("option");
    option.value = build.id;
    option.textContent = build.name;
    option.selected = build.id === currentId;
    els.buildSelect.appendChild(option);
  }
}

function fillSpecsForm(specs) {
  const s = normalizeBuildSpecs(specs);
  els.specCpu.value = s.cpu || "";
  els.specGpu.value = s.gpu || "";
  els.specRam.value = s.ram_gb ?? "";
  els.specStorage.value = s.storage_gb ?? "";
}

function loadBuildIntoForm(buildId) {
  const build = state.buildStore.builds.find(entry => entry.id === buildId) || null;
  if (!build) {
    els.buildName.value = "";
    fillSpecsForm(null);
    renderBuildOptions("");
    return;
  }

  els.buildName.value = build.name;
  fillSpecsForm(build.specs);
  renderBuildOptions(build.id);
}

function persistBuildStore() {
  saveBuildStore(state.buildStore);
  syncActiveSpecs();
}

function readSpecsFromForm() {
  return normalizeBuildSpecs({
    cpu: els.specCpu.value,
    gpu: els.specGpu.value,
    ram_gb: els.specRam.value,
    storage_gb: els.specStorage.value
  });
}

function saveCurrentBuildFromForm() {
  const selectedId = cleanText(els.buildSelect.value);
  const build = normalizeBuild({
    id: selectedId || createBuildId(),
    name: els.buildName.value,
    specs: readSpecsFromForm()
  }, state.buildStore.builds.length);

  const existingIndex = state.buildStore.builds.findIndex(entry => entry.id === build.id);
  if (existingIndex >= 0) {
    state.buildStore.builds[existingIndex] = build;
  } else {
    state.buildStore.builds.push(build);
  }

  state.buildStore.activeBuildId = build.id;
  persistBuildStore();
  loadBuildIntoForm(build.id);
}

function deleteSelectedBuild() {
  const selectedId = cleanText(els.buildSelect.value) || state.buildStore.activeBuildId;
  if (!selectedId) {
    loadBuildIntoForm("");
    return;
  }

  state.buildStore.builds = state.buildStore.builds.filter(build => build.id !== selectedId);
  state.buildStore.activeBuildId = state.buildStore.builds[0]?.id || null;
  persistBuildStore();
  loadBuildIntoForm(state.buildStore.activeBuildId || "");
}

function fixEncoding(value) {
  if (typeof value !== "string" || !/[ÃÂâ€™€œ¢â„¢]/.test(value)) return value;

  try {
    const bytes = Uint8Array.from(value, ch => ch.charCodeAt(0) & 0xff);
    const decoded = new TextDecoder("utf-8", { fatal: false }).decode(bytes);
    if (decoded.includes("\ufffd")) return value;

    const suspiciousOriginal = (value.match(/[ÃÂâ]/g) || []).length;
    const suspiciousDecoded = (decoded.match(/[ÃÂâ]/g) || []).length;
    return suspiciousDecoded <= suspiciousOriginal ? decoded : value;
  } catch {
    return value;
  }
}

function stripHtml(html) {
  if (!html) return "";
  const doc = new DOMParser().parseFromString(`<div>${html}</div>`, "text/html");
  return (doc.body.textContent || "").replace(/\s+/g, " ").trim();
}

function cleanText(value) {
  if (value === null || value === undefined) return null;
  const text = typeof value === "string" ? value : String(value);
  const fixed = fixEncoding(text).replace(/\u00a0/g, " ");
  return fixed.replace(/\s+/g, " ").trim() || null;
}

function isPlaceholderText(value) {
  const text = cleanText(value);
  if (!text) return true;
  const normalized = text.toLowerCase();
  return normalized === "minimum:" ||
    normalized === "recommended:" ||
    normalized === "minimum" ||
    normalized === "recommended";
}

function isMeaningfulText(value) {
  return !isPlaceholderText(value);
}

function cleanHtml(value) {
  const text = cleanText(value);
  return text ? fixEncoding(value) : null;
}

function fmtNum(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return "Unknown";
  return `${n}`;
}

function fmtGb(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return "Unknown";
  return `${n} GB`;
}

function compareNumeric(userVal, reqVal) {
  if (reqVal === null || reqVal === undefined || Number.isNaN(reqVal)) {
    return { status: "unknown", text: "No numeric requirement" };
  }
  if (userVal === null || userVal === undefined || Number.isNaN(userVal)) {
    return { status: "unknown", text: "Your value missing" };
  }
  if (userVal >= reqVal) return { status: "good", text: `Meets (${userVal} vs ${reqVal})` };
  return { status: "bad", text: `Below (${userVal} vs ${reqVal})` };
}

function badgeClass(status) {
  if (status === "good") return "badge good";
  if (status === "bad") return "badge bad";
  return "badge warn";
}

function loadIndex() {
  return fetch("data/index.json", { cache: "no-store" }).then(res => {
    if (!res.ok) throw new Error("Failed to load index");
    return res.json();
  });
}

function shardForAppid(appid) {
  const shardSize = state.index.shard_size;
  return Math.floor(appid / shardSize);
}

async function loadShard(shardId) {
  if (state.shardCache.has(shardId)) return state.shardCache.get(shardId);
  const url = `data/shards/shard_${String(shardId).padStart(5, "0")}.json`;
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`Failed to load shard ${shardId}`);
  const data = await res.json();
  const normalized = data.map(normalizeApp);
  state.shardCache.set(shardId, normalized);
  return normalized;
}

function toNumberOrNull(value) {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function cloneRequirement(req) {
  const base = {};
  for (const key of REQUIREMENT_FIELDS) {
    base[key] = null;
  }
  if (!req) return base;

  for (const key of REQUIREMENT_FIELDS) {
    if (key === "vulkan") {
      base[key] = Boolean(req[key]);
    } else if (["ram_gb", "vram_gb", "storage_gb", "directx", "opengl"].includes(key)) {
      base[key] = toNumberOrNull(req[key]);
    } else if (key === "raw_html") {
      base[key] = cleanHtml(req[key]);
    } else {
      base[key] = cleanText(req[key]);
    }
  }
  return base;
}

function emptyRequirement() {
  return cloneRequirement(null);
}

function hasUsableRequirement(req) {
  if (!req) return false;
  return Boolean(
    isMeaningfulText(req.os) ||
    isMeaningfulText(req.cpu) ||
    isMeaningfulText(req.gpu) ||
    req.ram_gb !== null ||
    req.vram_gb !== null ||
    req.storage_gb !== null ||
    req.directx !== null ||
    req.opengl !== null ||
    req.vulkan ||
    isMeaningfulText(req.notes)
  );
}

function requirementCompleteness(req) {
  if (!req) return 0;
  let score = 0;
  if (isMeaningfulText(req.os)) score++;
  if (isMeaningfulText(req.cpu)) score++;
  if (isMeaningfulText(req.gpu)) score++;
  if (req.ram_gb !== null) score++;
  if (req.vram_gb !== null) score++;
  if (req.storage_gb !== null) score++;
  if (req.directx !== null) score++;
  if (req.opengl !== null || req.vulkan) score++;
  return score;
}

function bestText(existing, parsed) {
  if (isMeaningfulText(parsed) && !isMeaningfulText(existing)) return parsed;
  if (!isMeaningfulText(parsed)) return existing;
  if (!isMeaningfulText(existing)) return parsed;
  return parsed.length > existing.length ? parsed : existing;
}

function bestNumber(existing, parsed) {
  if (existing === null || existing === undefined || Number.isNaN(existing)) return parsed ?? null;
  return existing;
}

function mergeRequirement(existing, parsed) {
  const out = cloneRequirement(existing);
  if (!parsed) return out;

  out.os = bestText(out.os, parsed.os);
  out.cpu = bestText(out.cpu, parsed.cpu);
  out.gpu = bestText(out.gpu, parsed.gpu);
  out.notes = bestText(out.notes, parsed.notes);
  out.raw_html = out.raw_html || parsed.raw_html || null;
  out.ram_gb = bestNumber(out.ram_gb, parsed.ram_gb);
  out.vram_gb = bestNumber(out.vram_gb, parsed.vram_gb);
  out.storage_gb = bestNumber(out.storage_gb, parsed.storage_gb);
  out.directx = bestNumber(out.directx, parsed.directx);
  out.opengl = bestNumber(out.opengl, parsed.opengl);
  out.vulkan = out.vulkan || parsed.vulkan;
  return out;
}

function normalizeLabel(label) {
  return cleanText(label)?.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim() || "";
}

function parseSizeInGb(text) {
  const normalized = cleanText(text)?.toLowerCase();
  if (!normalized) return null;

  const match = normalized.match(/(\d+(?:\.\d+)?)\s*(tb|gb|mb)\b/);
  if (!match) return null;

  const value = Number(match[1]);
  const unit = match[2];
  if (!Number.isFinite(value)) return null;
  if (unit === "tb") return value * 1024;
  if (unit === "mb") return value / 1024;
  return value;
}

function parseDirectxVersion(text) {
  const normalized = cleanText(text)?.toLowerCase();
  if (!normalized) return null;
  const match = normalized.match(/(?:version\s*)?(\d+(?:\.\d+)?)(?:c)?\b/);
  return match ? Number(match[1]) : null;
}

function assignParsedField(req, label, value) {
  const normalizedLabel = normalizeLabel(label);
  const cleanedValue = cleanText(value);
  if (!normalizedLabel || !cleanedValue) return false;

  if (normalizedLabel.includes("os") || normalizedLabel.includes("operating system")) {
    req.os = bestText(req.os, cleanedValue);
    return true;
  }

  if (normalizedLabel === "processor" || normalizedLabel.includes("cpu processor")) {
    req.cpu = bestText(req.cpu, cleanedValue);
    return true;
  }

  if (normalizedLabel.includes("cpu speed")) {
    req.cpu = req.cpu ? `${req.cpu}; ${cleanedValue}` : cleanedValue;
    return true;
  }

  if (
    normalizedLabel === "graphics" ||
    normalizedLabel === "video card" ||
    normalizedLabel.startsWith("video card ") ||
    normalizedLabel === "video"
  ) {
    req.gpu = req.gpu ? `${req.gpu}; ${cleanedValue}` : cleanedValue;
    return true;
  }

  if (normalizedLabel === "memory" || normalizedLabel === "system memory") {
    req.ram_gb = bestNumber(req.ram_gb, parseSizeInGb(cleanedValue));
    if (!req.ram_gb && isMeaningfulText(cleanedValue)) {
      req.notes = bestText(req.notes, `Memory: ${cleanedValue}`);
    }
    return true;
  }

  if (normalizedLabel.includes("video ram") || normalizedLabel.includes("video memory")) {
    req.vram_gb = bestNumber(req.vram_gb, parseSizeInGb(cleanedValue));
    return true;
  }

  if (
    normalizedLabel.includes("hard drive") ||
    normalizedLabel.includes("hard disk") ||
    normalizedLabel === "storage"
  ) {
    req.storage_gb = bestNumber(req.storage_gb, parseSizeInGb(cleanedValue));
    return true;
  }

  if (normalizedLabel.includes("directx")) {
    req.directx = bestNumber(req.directx, parseDirectxVersion(cleanedValue));
    return true;
  }

  if (normalizedLabel.includes("opengl")) {
    req.opengl = bestNumber(req.opengl, parseDirectxVersion(cleanedValue));
    return true;
  }

  if (normalizedLabel.includes("vulkan")) {
    req.vulkan = true;
    return true;
  }

  if (
    normalizedLabel.includes("sound") ||
    normalizedLabel.includes("network") ||
    normalizedLabel.includes("internet") ||
    normalizedLabel.includes("notice") ||
    normalizedLabel.includes("multiplayer")
  ) {
    req.notes = req.notes ? `${req.notes}\n${cleanedValue}` : cleanedValue;
    return true;
  }

  return false;
}

function parseFreeformText(text) {
  const req = emptyRequirement();
  const normalized = cleanText(text);
  if (!normalized) return req;

  const lower = normalized.toLowerCase();
  const osMatch = normalized.match(/(windows [^,;]+|mac(?:os| os x)? [^,;]+|os x [^,;]+|linux [^,;]+|ubuntu [^,;]+|steamos[^,;]*)/i);
  if (osMatch) req.os = cleanText(osMatch[1]);

  const ramMatch = lower.match(/(\d+(?:\.\d+)?)\s*(tb|gb|mb)\s*(?:system )?(?:memory|ram)\b/);
  if (ramMatch) req.ram_gb = parseSizeInGb(ramMatch[0]);

  const vramMatch = lower.match(/(\d+(?:\.\d+)?)\s*(tb|gb|mb)\s*(?:video )?(?:memory|ram|vram)\b/);
  if (vramMatch) req.vram_gb = parseSizeInGb(vramMatch[0]);

  const storageMatch = lower.match(/(\d+(?:\.\d+)?)\s*(tb|gb|mb)\s*(?:free )?(?:disk|drive|storage|space)/);
  if (storageMatch) req.storage_gb = parseSizeInGb(storageMatch[0]);

  const directxMatch = lower.match(/directx(?:\s*(?:version)?)?\s*(\d+(?:\.\d+)?)/);
  if (directxMatch) req.directx = Number(directxMatch[1]);

  const openglMatch = lower.match(/opengl\s*(\d+(?:\.\d+)?)/);
  if (openglMatch) req.opengl = Number(openglMatch[1]);

  if (lower.includes("vulkan")) req.vulkan = true;

  const cpuMatch = normalized.match(/([^,;\n]*?(?:processor|intel|amd|ryzen|core i\d|pentium|athlon)[^,;\n]*)/i);
  if (cpuMatch) req.cpu = cleanText(cpuMatch[1]);

  const gpuMatch = normalized.match(/([^,;\n]*?(?:geforce|radeon|intel hd|video card|graphics|gtx|rtx|rx )[^\n,;]*)/i);
  if (gpuMatch) req.gpu = cleanText(gpuMatch[1]);

  const leftover = normalized
    .replace(cpuMatch?.[1] || "", "")
    .replace(gpuMatch?.[1] || "", "")
    .trim();
  if (leftover && leftover !== normalized) req.notes = leftover;

  return req;
}

function parseRequirementSection(htmlOrText) {
  const raw = cleanHtml(htmlOrText);
  const req = emptyRequirement();
  req.raw_html = raw;
  if (!raw) return req;

  const doc = new DOMParser().parseFromString(`<div>${raw}</div>`, "text/html");
  const items = Array.from(doc.querySelectorAll("li"));
  let assignedAny = false;

  for (const item of items) {
    const strong = item.querySelector("strong");
    const strongText = strong ? strong.textContent : "";
    const label = normalizeLabel(strongText);
    const itemText = cleanText(item.textContent);
    const valueText = strong
      ? cleanText(itemText?.replace(strong.textContent || "", ""))
      : itemText;

    if (label && assignParsedField(req, label, valueText)) {
      assignedAny = true;
      continue;
    }

    if (itemText) {
      assignedAny = true;
      const extra = parseFreeformText(itemText);
      Object.assign(req, mergeRequirement(req, extra));
    }
  }

  const plainText = cleanText(doc.body.textContent);
  if (!assignedAny && plainText) {
    return mergeRequirement(req, parseFreeformText(plainText));
  }

  return req;
}

function splitLevelsFromRaw(rawHtml) {
  const raw = cleanHtml(rawHtml);
  if (!raw) return {};

  const regex = /(?:<strong>\s*)?(Minimum|Recommended)\s*:?\s*(?:<\/strong>)?/gi;
  const matches = Array.from(raw.matchAll(regex));
  if (!matches.length) return {};

  const sections = {};
  for (let i = 0; i < matches.length; i++) {
    const match = matches[i];
    const level = match[1].toLowerCase();
    const start = match.index + match[0].length;
    const end = i + 1 < matches.length ? matches[i + 1].index : raw.length;
    const sectionRaw = raw.slice(start, end).trim();
    if (sectionRaw) {
      sections[level] = match[0] + sectionRaw;
    }
  }
  return sections;
}

function buildRequirement(existingReq, fallbackHtml) {
  const base = cloneRequirement(existingReq);
  const raw = base.raw_html || cleanHtml(fallbackHtml);
  const parsed = parseRequirementSection(raw);
  return mergeRequirement(base, parsed);
}

function normalizePlatformRequirements(platformReq) {
  const minimum = cloneRequirement(platformReq?.minimum);
  const recommended = cloneRequirement(platformReq?.recommended);

  const combinedSections = splitLevelsFromRaw(minimum.raw_html) || {};
  const minimumRaw = combinedSections.minimum || minimum.raw_html;
  const recommendedRaw = combinedSections.recommended || recommended.raw_html;

  const normalizedMinimum = buildRequirement(minimum, minimumRaw);
  let normalizedRecommended = buildRequirement(recommended, recommendedRaw);

  if (!hasUsableRequirement(normalizedRecommended) && combinedSections.recommended) {
    normalizedRecommended = buildRequirement(recommended, combinedSections.recommended);
  }

  const leakedRecommended = /recommended\s*:/i.test(cleanText(normalizedMinimum.cpu) || "") ||
    /recommended\s*:/i.test(cleanText(normalizedMinimum.gpu) || "") ||
    /recommended\s*:/i.test(cleanText(normalizedMinimum.notes) || "");

  if (leakedRecommended && hasUsableRequirement(normalizedRecommended)) {
    normalizedMinimum.cpu = cleanText(normalizedMinimum.cpu?.replace(/recommended\s*:.*$/i, ""));
    normalizedMinimum.gpu = cleanText(normalizedMinimum.gpu?.replace(/recommended\s*:.*$/i, ""));
    normalizedMinimum.notes = cleanText(normalizedMinimum.notes?.replace(/recommended\s*:.*$/i, ""));
  }

  return {
    minimum: normalizedMinimum,
    recommended: normalizedRecommended
  };
}

function normalizeApp(app) {
  const normalized = {
    appid: app.appid,
    name: cleanText(app.name),
    type: cleanText(app.type),
    requirements: null
  };

  if (!app.requirements) return normalized;

  normalized.requirements = {
    pc: normalizePlatformRequirements(app.requirements.pc),
    mac: normalizePlatformRequirements(app.requirements.mac),
    linux: normalizePlatformRequirements(app.requirements.linux)
  };

  return normalized;
}

function appHasUsableRequirements(app) {
  if (!app?.requirements) return false;
  return ["pc", "mac", "linux"].some(platform => {
    const reqs = app.requirements[platform];
    return hasUsableRequirement(reqs?.minimum) || hasUsableRequirement(reqs?.recommended);
  });
}

function typeLabel(app) {
  if (app.type) return app.type;
  if (appHasUsableRequirements(app)) return "unknown type";
  return "untyped";
}

function applyFilters() {
  const q = (els.search.value || "").trim().toLowerCase();
  const mode = els.filter.value;

  let apps = state.index.apps;

  if (mode === "game") apps = apps.filter(a => a.type === "game");
  if (mode === "dlc") apps = apps.filter(a => a.type === "dlc");
  if (mode === "hasreqs") apps = apps.filter(a => a.has_requirements);

  if (q) {
    apps = apps.filter(a => (a.name || "").toLowerCase().includes(q));
  }

  state.filtered = apps.slice(0, 200);
  renderList();
}

function renderList() {
  els.list.innerHTML = "";
  const total = state.index.total_apps;
  const shown = state.filtered.length;
  els.meta.textContent = `Loaded ${total} apps. Showing ${shown} results. Requirement badges are verified after opening a record.`;

  for (const a of state.filtered) {
    const div = document.createElement("div");
    div.className = "item";
    div.onclick = () => selectApp(a.appid);

    const left = document.createElement("div");
    const t = document.createElement("div");
    t.className = "itemTitle";
    t.textContent = cleanText(a.name) || `(appid ${a.appid})`;

    const s = document.createElement("div");
    s.className = "itemSub";
    s.textContent = `${cleanText(a.type) || "unknown"} · appid ${a.appid}`;

    left.appendChild(t);
    left.appendChild(s);

    const b = document.createElement("div");
    b.className = a.has_requirements ? "badge warn" : "badge";
    b.textContent = a.has_requirements ? "Needs verify" : "No raw reqs";

    div.appendChild(left);
    div.appendChild(b);
    els.list.appendChild(div);
  }
}

function pickReq(app, platform, level) {
  return app.requirements?.[platform]?.[level] || null;
}

function comparisonBadgeStatus(req, userSpecs) {
  if (!hasUsableRequirement(req)) return "warn";
  if (!userSpecs) return "warn";

  const checks = [
    compareNumeric(userSpecs.ram_gb, req.ram_gb),
    compareNumeric(userSpecs.storage_gb, req.storage_gb)
  ];

  if (checks.some(check => check.status === "bad")) return "bad";
  if (checks.some(check => check.status === "good")) return "good";
  return "warn";
}

function comparisonBadgeText(req, userSpecs) {
  if (!hasUsableRequirement(req)) return "Missing";
  if (!userSpecs) return "Add your specs";

  const status = comparisonBadgeStatus(req, userSpecs);
  if (status === "bad") return "Below spec";
  if (status === "good") return "Looks good";
  return "Partial compare";
}

function recoveryNote(req) {
  if (!req?.raw_html) return null;
  if (requirementCompleteness(req) >= 3) return "Recovered from stored Steam HTML";
  return "Only partially recovered from stored Steam HTML";
}

function renderReqCard(title, req, userSpecs) {
  if (!hasUsableRequirement(req)) {
    return `
      <div class="reqCard">
        <div class="reqTitle"><span>${title}</span><span class="badge warn">Missing</span></div>
        <div class="reqList">No reliable requirements data for this platform and level.</div>
      </div>
    `;
  }

  const ramCmp = compareNumeric(userSpecs?.ram_gb, req.ram_gb);
  const stoCmp = compareNumeric(userSpecs?.storage_gb, req.storage_gb);
  const status = comparisonBadgeStatus(req, userSpecs);

  return `
    <div class="reqCard">
      <div class="reqTitle">
        <span>${title}</span>
        <span class="${badgeClass(status)}">${comparisonBadgeText(req, userSpecs)}</span>
      </div>
      <div class="reqList">
        <div class="kv"><span><b>OS</b></span><span class="small">${req.os || "Unknown"}</span></div>
        <div class="kv"><span><b>CPU</b></span><span class="small">${req.cpu || "Unknown"}</span></div>
        <div class="kv"><span><b>GPU</b></span><span class="small">${req.gpu || "Unknown"}</span></div>

        <div class="kv"><span><b>RAM</b></span><span>${fmtGb(req.ram_gb)} ${userSpecs ? ` · ${ramCmp.text}` : ""}</span></div>
        <div class="kv"><span><b>Storage</b></span><span>${fmtGb(req.storage_gb)} ${userSpecs ? ` · ${stoCmp.text}` : ""}</span></div>
      </div>
    </div>
  `;
}

function renderSavedBuildComparisons(minReq, recReq) {
  const builds = state.buildStore?.builds || [];
  if (!builds.length) {
    return `
      <div class="reqCard" style="margin-top:12px">
        <div class="reqTitle"><span>Saved Builds</span><span class="badge warn">None yet</span></div>
        <div class="reqList">Save one or more PC builds to switch quickly and compare them here.</div>
      </div>
    `;
  }

  const rows = builds.map(build => {
    const minStatus = comparisonBadgeStatus(minReq, build.specs);
    const recStatus = comparisonBadgeStatus(recReq, build.specs);
    const active = build.id === state.buildStore.activeBuildId ? " (active)" : "";

    return `
      <div class="kv">
        <span><b>${build.name}${active}</b></span>
        <span>
          <span class="${badgeClass(minStatus)}">Min: ${comparisonBadgeText(minReq, build.specs)}</span>
          <span class="${badgeClass(recStatus)}">Rec: ${comparisonBadgeText(recReq, build.specs)}</span>
        </span>
      </div>
    `;
  }).join("");

  return `
    <div class="reqCard" style="margin-top:12px">
      <div class="reqTitle"><span>Saved Builds</span><span class="badge good">${builds.length} saved</span></div>
      <div class="reqList">${rows}</div>
    </div>
  `;
}

function renderDetail(app) {
  els.detailEmpty.classList.add("hidden");
  els.detail.classList.remove("hidden");

  let platform = "pc";
  const userSpecs = state.specs;

  function draw() {
    const min = pickReq(app, platform, "minimum");
    const rec = pickReq(app, platform, "recommended");
    const verified = hasUsableRequirement(min) || hasUsableRequirement(rec);

    els.detail.innerHTML = `
      <div class="h1">${app.name || `(appid ${app.appid})`}</div>
      <div class="h2">${typeLabel(app)} · appid ${app.appid}</div>
      <div class="h2">${verified ? "Recovered and normalized from stored scrape data." : "This record does not have a usable requirement parse yet."}</div>

      <div class="tabs">
        <button class="tab ${platform === "pc" ? "active" : ""}" data-p="pc">Windows</button>
        <button class="tab ${platform === "mac" ? "active" : ""}" data-p="mac">macOS</button>
        <button class="tab ${platform === "linux" ? "active" : ""}" data-p="linux">Linux</button>
      </div>

      <div class="grid2">
        ${renderReqCard("Minimum", min, userSpecs)}
        ${renderReqCard("Recommended", rec, userSpecs)}
      </div>

      ${renderSavedBuildComparisons(min, rec)}

      <div style="margin-top:12px;color:var(--muted);font-size:12px">
        CPU and GPU matching is still text-only. Numeric comparisons apply to RAM and storage when they could be recovered cleanly.
      </div>
    `;

    els.detail.querySelectorAll(".tab").forEach(btn => {
      btn.onclick = () => {
        platform = btn.getAttribute("data-p");
        draw();
      };
    });
  }

  draw();
}

async function selectApp(appid) {
  const shardId = shardForAppid(appid);
  const shard = await loadShard(shardId);
  const app = shard.find(x => x.appid === appid);
  state.selected = app || null;
  if (state.selected) renderDetail(state.selected);
}

function openModal() {
  els.backdrop.classList.remove("hidden");
  els.modal.classList.remove("hidden");
  loadBuildIntoForm(state.buildStore.activeBuildId || "");
}

function closeModal() {
  els.backdrop.classList.add("hidden");
  els.modal.classList.add("hidden");
}

async function init() {
  state.buildStore = loadBuildStore();
  syncActiveSpecs();
  state.index = await loadIndex();

  els.search.addEventListener("input", applyFilters);
  els.filter.addEventListener("change", applyFilters);

  els.openSpecs.onclick = openModal;
  els.closeSpecs.onclick = closeModal;
  els.backdrop.onclick = closeModal;
  els.buildSelect.onchange = () => loadBuildIntoForm(els.buildSelect.value);
  els.newBuild.onclick = () => loadBuildIntoForm("");
  els.deleteBuild.onclick = () => {
    deleteSelectedBuild();
    if (state.selected) renderDetail(state.selected);
  };

  els.saveSpecs.onclick = () => {
    saveCurrentBuildFromForm();
    closeModal();
    if (state.selected) renderDetail(state.selected);
  };

  applyFilters();
}

init().catch(err => {
  els.meta.textContent = `Failed to load site data: ${err.message}`;
});
