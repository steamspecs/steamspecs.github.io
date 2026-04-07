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
  "raw_html",
  "cpu_match",
  "gpu_match"
];

const state = {
  index: null,
  filtered: [],
  selected: null,
  buildStore: null,
  catalogs: { cpu: [], gpu: [] },
  catalogNameMap: { cpu: new Map(), gpu: new Map() },
  shardCache: new Map(),
  listRenderToken: 0
};

const FALLBACK_AVERAGES = {
  ram_gb: 8,
  storage_gb: 30,
  cpu_score: 9000,
  gpu_score: 9000
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

  buildPlatform: document.getElementById("buildPlatform"),
  buildSelect: document.getElementById("buildSelect"),
  buildName: document.getElementById("buildName"),
  newBuild: document.getElementById("newBuild"),
  deleteBuild: document.getElementById("deleteBuild"),
  specCpu: document.getElementById("specCpu"),
  specCpuHelp: document.getElementById("specCpuHelp"),
  cpuOptions: document.getElementById("cpuOptions"),
  specGpu: document.getElementById("specGpu"),
  specGpuHelp: document.getElementById("specGpuHelp"),
  gpuOptions: document.getElementById("gpuOptions"),
  specRam: document.getElementById("specRam"),
  specStorage: document.getElementById("specStorage"),
  saveSpecs: document.getElementById("saveSpecs"),
  copyBtc: document.getElementById("copyBtc"),
  copyBtcLabel: document.getElementById("copyBtcLabel")
};

function createBuildId() {
  return `build_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

function toNumberOrNull(value) {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function fixEncoding(value) {
  if (typeof value !== "string" || !/[ÃÂâ]/.test(value)) return value;
  try {
    const bytes = Uint8Array.from(value, ch => ch.charCodeAt(0) & 0xff);
    const decoded = new TextDecoder("utf-8", { fatal: false }).decode(bytes);
    return decoded.includes("\ufffd") ? value : decoded;
  } catch {
    return value;
  }
}

function cleanText(value) {
  if (value === null || value === undefined) return null;
  const text = typeof value === "string" ? value : String(value);
  return fixEncoding(text).replace(/\u00a0/g, " ").replace(/\s+/g, " ").trim() || null;
}

function normalizeAlias(value) {
  const text = cleanText(value);
  if (!text) return null;
  return text
    .toLowerCase()
    .replace(/[®™]/g, "")
    .replace(/[^a-z0-9]+/g, " ")
    .replace(/\s+/g, " ")
    .trim() || null;
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
    platform: ["pc", "mac", "linux"].includes(build?.platform) ? build.platform : "pc",
    specs: normalizeBuildSpecs(build?.specs || build)
  };
}

function defaultBuildStore() {
  return { version: 1, activeBuildId: null, builds: [] };
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

    const legacyBuild = normalizeBuild({
      id: createBuildId(),
      name: "My PC",
      platform: "pc",
      specs: JSON.parse(legacyRaw)
    });

    return { version: 1, activeBuildId: legacyBuild.id, builds: [legacyBuild] };
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

function syncActiveBuildLabel() {
  els.openSpecs.textContent = getActiveBuild()?.name || "Your builds";
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
  updateCatalogFieldHelp("cpu");
  updateCatalogFieldHelp("gpu");
}

function loadBuildIntoForm(buildId) {
  const build = state.buildStore.builds.find(entry => entry.id === buildId) || null;
  if (!build) {
    els.buildPlatform.value = "pc";
    els.buildName.value = "";
    fillSpecsForm(null);
    renderBuildOptions("");
    return;
  }

  els.buildPlatform.value = build.platform || "pc";
  els.buildName.value = build.name;
  fillSpecsForm(build.specs);
  renderBuildOptions(build.id);
}

function persistBuildStore() {
  saveBuildStore(state.buildStore);
  syncActiveBuildLabel();
}

function readSpecsFromForm() {
  return normalizeBuildSpecs({
    cpu: els.specCpu.value,
    gpu: els.specGpu.value,
    ram_gb: els.specRam.value,
    storage_gb: els.specStorage.value
  });
}

function setFieldHelp(kind, text, status = "") {
  const el = kind === "cpu" ? els.specCpuHelp : els.specGpuHelp;
  el.textContent = text;
  el.className = `fieldHelp${status ? ` ${status}` : ""}`;
}

function getCatalogComponentByName(kind, rawText) {
  const normalized = normalizeAlias(rawText);
  if (!normalized) return null;
  return state.catalogNameMap[kind]?.get(normalized) || null;
}

function updateCatalogFieldHelp(kind) {
  const input = kind === "cpu" ? els.specCpu : els.specGpu;
  const catalog = state.catalogs[kind] || [];
  const label = kind.toUpperCase();
  const match = getCatalogComponentByName(kind, input.value);

  if (!cleanText(input.value)) {
    setFieldHelp(kind, `Choose a known ${label} from the catalog. ${catalog.length.toLocaleString()} available.`);
    return;
  }

  if (match) {
    const extra = kind === "cpu"
      ? [match.base_ghz ? `${match.base_ghz} GHz base` : null, match.score ? `score ${match.score}` : null].filter(Boolean).join(" · ")
      : [match.vram_gb ? `${match.vram_gb} GB VRAM` : null, match.score ? `score ${match.score}` : null].filter(Boolean).join(" · ");
    setFieldHelp(kind, extra ? `Matched ${match.name} · ${extra}` : `Matched ${match.name}`, "good");
    return;
  }

  setFieldHelp(kind, `This ${label} is not in the known catalog yet. Pick one of the suggestions to save this build.`, "warn");
}

function populateCatalogOptions(kind) {
  const list = kind === "cpu" ? els.cpuOptions : els.gpuOptions;
  const catalog = [...(state.catalogs[kind] || [])].sort((a, b) => {
    const scoreDiff = (Number(b.score) || 0) - (Number(a.score) || 0);
    if (scoreDiff) return scoreDiff;
    return (a.name || "").localeCompare(b.name || "");
  });

  list.innerHTML = "";
  const nameMap = new Map();
  for (const component of catalog) {
    const name = cleanText(component.name);
    if (!name) continue;
    const option = document.createElement("option");
    option.value = name;
    list.appendChild(option);
    const alias = normalizeAlias(name);
    if (alias && !nameMap.has(alias)) nameMap.set(alias, component);
  }
  state.catalogNameMap[kind] = nameMap;
  updateCatalogFieldHelp(kind);
}

function saveCurrentBuildFromForm() {
  const selectedId = cleanText(els.buildSelect.value);
  const specs = readSpecsFromForm();
  const cpuMatch = getCatalogComponentByName("cpu", specs.cpu);
  const gpuMatch = getCatalogComponentByName("gpu", specs.gpu);

  if (!cpuMatch) {
    updateCatalogFieldHelp("cpu");
    window.alert("Choose a CPU from the known catalog before saving this build.");
    els.specCpu.focus();
    return false;
  }

  if (!gpuMatch) {
    updateCatalogFieldHelp("gpu");
    window.alert("Choose a GPU from the known catalog before saving this build.");
    els.specGpu.focus();
    return false;
  }

  const build = normalizeBuild({
    id: selectedId || createBuildId(),
    name: els.buildName.value,
    platform: els.buildPlatform.value,
    specs
  }, state.buildStore.builds.length);

  const existingIndex = state.buildStore.builds.findIndex(entry => entry.id === build.id);
  if (existingIndex >= 0) state.buildStore.builds[existingIndex] = build;
  else state.buildStore.builds.push(build);

  state.buildStore.activeBuildId = build.id;
  persistBuildStore();
  loadBuildIntoForm(build.id);
  return true;
}

function deleteSelectedBuild() {
  const selectedId = cleanText(els.buildSelect.value) || state.buildStore.activeBuildId;
  if (!selectedId) return loadBuildIntoForm("");
  state.buildStore.builds = state.buildStore.builds.filter(build => build.id !== selectedId);
  state.buildStore.activeBuildId = state.buildStore.builds[0]?.id || null;
  persistBuildStore();
  loadBuildIntoForm(state.buildStore.activeBuildId || "");
}

function fmtGb(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return "Unknown";
  return `${n} GB`;
}

function fmtComparisonNumber(value, kind = "generic") {
  const n = toNumberOrNull(value);
  if (n === null) return "Unknown";
  if (kind === "ram" || kind === "storage") return `${n}GB`;
  return String(n);
}

function compareNumeric(userVal, reqVal, kind = "generic") {
  if (reqVal === null || reqVal === undefined || Number.isNaN(reqVal)) {
    return { status: "unknown", text: "No numeric requirement", label: "Unknown" };
  }
  if (userVal === null || userVal === undefined || Number.isNaN(userVal)) {
    return { status: "unknown", text: "Your value missing", label: "Unknown" };
  }

  if (userVal >= reqVal) return { status: "good", text: `${fmtComparisonNumber(userVal, kind)} > ${fmtComparisonNumber(reqVal, kind)}`, label: "Pass" };
  return { status: "bad", text: `${fmtComparisonNumber(userVal, kind)} < ${fmtComparisonNumber(reqVal, kind)}`, label: "Fail" };
}

function compareAverageFallback(userVal, averageVal, kind = "generic") {
  if (userVal === null || userVal === undefined || Number.isNaN(userVal)) {
    return { status: "unknown", text: "Your value missing", label: "Unknown" };
  }
  if (averageVal === null || averageVal === undefined || Number.isNaN(averageVal)) {
    return { status: "unknown", text: "Average unavailable", label: "Unknown" };
  }
  if (userVal >= averageVal) {
    return { status: "likely", text: `${fmtComparisonNumber(userVal, kind)} > ${fmtComparisonNumber(averageVal, kind)}`, label: "Likely" };
  }
  return { status: "unlikely", text: `${fmtComparisonNumber(userVal, kind)} < ${fmtComparisonNumber(averageVal, kind)}`, label: "Unlikely" };
}

function isGenericCpuText(text) {
  const normalized = normalizeAlias(text) || "";
  if (!normalized) return false;
  if (/^(amd|intel)$/.test(normalized)) return true;
  return /(single core|dual core|multi core|processor|cpu with|equivalent|or better|intel amd|amd intel|intel or amd|amd or intel)/.test(normalized);
}

function isVagueGpuText(text) {
  const normalized = normalizeAlias(text) || "";
  if (!normalized) return false;
  if (/^(amd|intel|nvidia|ati|radeon|geforce)$/.test(normalized)) return true;
  return /(directx|opengl|shader|video card|graphics card|graphic card|gpu|pci|agp|dedicated vram|vram)/.test(normalized)
    && !/(geforce \d|radeon \d|rtx|gtx|rx \d|hd \d|x\d{3}|intel arc|intel iris|intel gma)/.test(normalized);
}

function parseClockGhz(text) {
  const normalized = (cleanText(text)?.toLowerCase() || "").replace(/(\d),(\d)/g, "$1.$2");
  if (!normalized) return null;

  const ghzMatch = normalized.match(/(\d+(?:\.\d+)?)\s*ghz\b/);
  if (ghzMatch) return Number(ghzMatch[1]);

  const mhzMatch = normalized.match(/(\d+(?:\.\d+)?)\s*mhz\b/);
  if (mhzMatch) return Number(mhzMatch[1]) / 1000;

  return null;
}

function parseMemoryGb(text) {
  const normalized = (cleanText(text)?.toLowerCase() || "").replace(/(\d),(\d)/g, "$1.$2");
  if (!normalized) return null;

  const gbMatch = normalized.match(/(\d+(?:\.\d+)?)\s*gb\b/);
  if (gbMatch) return Number(gbMatch[1]);

  const mbMatch = normalized.match(/(\d+(?:\.\d+)?)\s*mb\b/);
  if (mbMatch) return Number(mbMatch[1]) / 1024;

  return null;
}

function getCpuClockGhzFromBuild(userText) {
  const userComponent = findCatalogComponent("cpu", userText);
  if (userComponent) {
    const knownClock = toNumberOrNull(userComponent.boost_ghz) ?? toNumberOrNull(userComponent.base_ghz);
    if (knownClock !== null) return knownClock;
  }
  return parseClockGhz(userText);
}

function getGpuMemoryGbFromBuild(userText) {
  const userComponent = findCatalogComponent("gpu", userText);
  if (userComponent) {
    const knownMemory = toNumberOrNull(userComponent.vram_gb);
    if (knownMemory !== null) return knownMemory;
  }
  return parseMemoryGb(userText);
}

function compareCpuRequirement(req, userText) {
  if (isGenericCpuText(req?.cpu)) {
    const reqClockOnly = parseClockGhz(req?.cpu);
    const userClockOnly = getCpuClockGhzFromBuild(userText);
    if (reqClockOnly !== null) {
      if (!cleanText(userText)) return { status: "unknown", text: "Your CPU missing", method: null };
      if (userClockOnly === null) return { status: "unknown", text: "Your CPU clock unknown", method: null };
      if (userClockOnly >= reqClockOnly) return { status: "good", text: `${userClockOnly.toFixed(2)} GHz > ${reqClockOnly.toFixed(2)} GHz`, method: "clock" };
      return { status: "bad", text: `${userClockOnly.toFixed(2)} GHz < ${reqClockOnly.toFixed(2)} GHz`, method: "clock" };
    }
    const userComponent = findCatalogComponent("cpu", userText);
    return compareAverageFallback(toNumberOrNull(userComponent?.score), FALLBACK_AVERAGES.cpu_score);
  }

  const catalogCmp = compareCatalogComponent("cpu", userText, req?.cpu_match);
  if (catalogCmp.status !== "unknown") return catalogCmp;

  const reqClock = parseClockGhz(req?.cpu);
  const userClock = getCpuClockGhzFromBuild(userText);
  if (reqClock !== null) {
    if (!cleanText(userText)) return { status: "unknown", text: "Your CPU missing", method: null };
    if (userClock === null) return { status: "unknown", text: "Your CPU clock unknown", method: null };
    if (userClock >= reqClock) return { status: "good", text: `${userClock.toFixed(2)} GHz > ${reqClock.toFixed(2)} GHz`, method: "clock" };
    return { status: "bad", text: `${userClock.toFixed(2)} GHz < ${reqClock.toFixed(2)} GHz`, method: "clock" };
  }

  const userComponent = findCatalogComponent("cpu", userText);
  if (!cleanText(req?.cpu)) {
    return compareAverageFallback(toNumberOrNull(userComponent?.score), FALLBACK_AVERAGES.cpu_score);
  }

  return catalogCmp;
}

function compareGpuRequirement(req, userText) {
  if (isVagueGpuText(req?.gpu)) {
    const reqVramOnly = toNumberOrNull(req?.vram_gb) ?? parseMemoryGb(req?.gpu);
    const userVramOnly = getGpuMemoryGbFromBuild(userText);
    if (reqVramOnly !== null) {
      if (!cleanText(userText)) return { status: "unknown", text: "Your GPU missing", method: null };
      if (userVramOnly === null) return { status: "unknown", text: "Your GPU memory unknown", method: null };
      if (userVramOnly >= reqVramOnly) return { status: "good", text: `${userVramOnly}GB > ${reqVramOnly}GB`, method: "exact" };
      return { status: "bad", text: `${userVramOnly}GB < ${reqVramOnly}GB`, method: "exact" };
    }
    return { status: "unknown", text: "Component unknown", method: null };
  }

  const catalogCmp = compareCatalogComponent("gpu", userText, req?.gpu_match);
  if (catalogCmp.status !== "unknown") return catalogCmp;

  const reqVram = toNumberOrNull(req?.vram_gb);
  const userVram = getGpuMemoryGbFromBuild(userText);
  if (reqVram !== null) {
    if (!cleanText(userText)) return { status: "unknown", text: "Your GPU missing", method: null };
    if (userVram === null) return { status: "unknown", text: "Your GPU memory unknown", method: null };
    if (userVram >= reqVram) return { status: "good", text: `${userVram}GB > ${reqVram}GB`, method: "exact" };
    return { status: "bad", text: `${userVram}GB < ${reqVram}GB`, method: "exact" };
  }

  const userComponent = findCatalogComponent("gpu", userText);
  if (!cleanText(req?.gpu)) {
    return compareAverageFallback(toNumberOrNull(userComponent?.score), FALLBACK_AVERAGES.gpu_score);
  }

  return catalogCmp;
}

function buildRequirementChecks(req, build) {
  return [
    { key: "cpu", required: Boolean(cleanText(req?.cpu)), result: compareCpuRequirement(req, build?.specs?.cpu) },
    { key: "gpu", required: Boolean(cleanText(req?.gpu)), result: compareGpuRequirement(req, build?.specs?.gpu) },
    {
      key: "ram",
      required: req?.ram_gb !== null && req?.ram_gb !== undefined,
      result: req?.ram_gb !== null && req?.ram_gb !== undefined
        ? compareNumeric(build?.specs?.ram_gb, req?.ram_gb, "ram")
        : compareAverageFallback(build?.specs?.ram_gb, FALLBACK_AVERAGES.ram_gb, "ram")
    },
    {
      key: "storage",
      required: req?.storage_gb !== null && req?.storage_gb !== undefined,
      result: req?.storage_gb !== null && req?.storage_gb !== undefined
        ? compareNumeric(build?.specs?.storage_gb, req?.storage_gb, "storage")
        : compareAverageFallback(build?.specs?.storage_gb, FALLBACK_AVERAGES.storage_gb, "storage")
    }
  ];
}

function badgeClass(status) {
  if (status === "good") return "badge good";
  if (status === "likely") return "badge likely";
  if (status === "bad") return "badge bad";
  if (status === "unlikely") return "badge unlikely";
  if (status === "unknown") return "badge unknown";
  if (status === "partial") return "badge partial";
  return "badge warn";
}

function requirementLabel(comparison) {
  if (comparison?.label) return comparison.label;
  if (comparison?.status === "good") return "Pass";
  if (comparison?.status === "likely") return "Likely";
  if (comparison?.status === "bad") return "Fail";
  if (comparison?.status === "unlikely") return "Unlikely";
  if (comparison?.status === "partial") return "Partial";
  return "Unknown";
}

function comparisonMethodLabel(comparison) {
  if (comparison?.method === "exact") return "Exact";
  if (comparison?.method === "score") return "Score";
  if (comparison?.method === "clock") return "Clock";
  return "";
}

function renderComparisonValue(value, comparison) {
  const methodLabel = comparisonMethodLabel(comparison);
  return `
    <div class="compareValue">
      <div>${value}</div>
      <div class="compareBadges">
        <span class="${badgeClass(comparison.status)}">${requirementLabel(comparison)}</span>
        ${methodLabel ? `<span class="compareMethod">${methodLabel}</span>` : ""}
      </div>
    </div>
    <div class="compareHint">${comparison.text}</div>
  `;
}

function loadIndex() {
  return fetch("data/index.json", { cache: "no-store" }).then(res => {
    if (!res.ok) throw new Error("Failed to load index");
    return res.json();
  });
}

async function loadCatalogs() {
  const [cpuRes, gpuRes] = await Promise.all([
    fetch("data/catalog/cpus.json", { cache: "no-store" }),
    fetch("data/catalog/gpus.json", { cache: "no-store" })
  ]);
  if (!cpuRes.ok || !gpuRes.ok) throw new Error("Failed to load component catalogs");
  const [cpu, gpu] = await Promise.all([cpuRes.json(), gpuRes.json()]);
  state.catalogs = { cpu, gpu };
  populateCatalogOptions("cpu");
  populateCatalogOptions("gpu");
}

function shardForAppid(appid) {
  return Math.floor(appid / state.index.shard_size);
}

function cloneRequirement(req) {
  const base = {};
  for (const key of REQUIREMENT_FIELDS) base[key] = null;
  base.vulkan = false;
  base.cpu_match = { raw: null, candidates: [], min_score: null };
  base.gpu_match = { raw: null, candidates: [], min_score: null };
  if (!req) return base;

  for (const key of REQUIREMENT_FIELDS) {
    if (key === "vulkan") base[key] = Boolean(req[key]);
    else if (["ram_gb", "vram_gb", "storage_gb", "directx", "opengl"].includes(key)) base[key] = toNumberOrNull(req[key]);
    else if (key === "cpu_match" || key === "gpu_match") {
      base[key] = {
        raw: cleanText(req[key]?.raw),
        candidates: Array.isArray(req[key]?.candidates) ? req[key].candidates.map(candidate => ({
          id: cleanText(typeof candidate === "string" ? candidate : candidate?.id),
          name: cleanText(candidate?.name),
          score: toNumberOrNull(candidate?.score),
          matched_from: cleanText(candidate?.matched_from)
        })).filter(candidate => candidate.id) : [],
        min_score: toNumberOrNull(req[key]?.min_score)
      };
    } else {
      base[key] = cleanText(req[key]);
    }
  }
  return base;
}

function hasUsableRequirement(req) {
  if (!req) return false;
  return Boolean(req.os || req.cpu || req.gpu || req.ram_gb !== null || req.storage_gb !== null);
}

function normalizeApp(app) {
  return {
    appid: app.appid,
    name: cleanText(app.name),
    type: cleanText(app.type),
    requirements: app.requirements ? {
      pc: {
        minimum: cloneRequirement(app.requirements.pc?.minimum),
        recommended: cloneRequirement(app.requirements.pc?.recommended)
      },
      mac: {
        minimum: cloneRequirement(app.requirements.mac?.minimum),
        recommended: cloneRequirement(app.requirements.mac?.recommended)
      },
      linux: {
        minimum: cloneRequirement(app.requirements.linux?.minimum),
        recommended: cloneRequirement(app.requirements.linux?.recommended)
      }
    } : null
  };
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

async function applyFilters() {
  const q = (els.search.value || "").trim().toLowerCase();
  const mode = els.filter.value;
  let apps = state.index.apps;

  if (mode === "game") apps = apps.filter(a => a.type === "game");
  if (mode === "dlc") apps = apps.filter(a => a.type === "dlc");
  if (q) apps = apps.filter(a => (a.name || "").toLowerCase().includes(q));

  const summaryModes = new Set(["pass", "likely", "unknown", "partial", "unlikely", "fail"]);
  if (summaryModes.has(mode)) {
    const activeBuild = getActiveBuild();
    const uniqueShardIds = [...new Set(apps.map(app => shardForAppid(app.appid)))];
    await Promise.all(uniqueShardIds.map(id => loadShard(id)));
    apps = apps.filter(app => {
      const shard = state.shardCache.get(shardForAppid(app.appid)) || [];
      const detailedApp = shard.find(entry => entry.appid === app.appid) || normalizeApp(app);
      return summarizeListMinimum(detailedApp, activeBuild).key === mode;
    });
  }

  state.filtered = apps;
  await renderList();
}

function summarizeListMinimum(app, build) {
  if (!build?.specs) return { status: "unknown", text: "Unknown", key: "unknown" };
  if (!app?.requirements) return { status: "unknown", text: "Unknown", key: "unknown" };

  const platform = build.platform || "pc";
  const minReq = app.requirements?.[platform]?.minimum || null;
  if (!hasUsableRequirement(minReq)) return { status: "unknown", text: "Unknown", key: "unknown" };

  const summary = comparisonSummary(minReq, build, platform);
  if (summary.status === "good") return { status: "good", text: "Pass", key: "pass" };
  if (summary.status === "likely") return { status: "likely", text: "Likely", key: "likely" };
  if (summary.status === "bad") return { status: "bad", text: "Fail", key: "fail" };
  if (summary.status === "unlikely") return { status: "unlikely", text: "Unlikely", key: "unlikely" };
  if (summary.status === "partial") return { status: "partial", text: "Partial", key: "partial" };
  return { status: "unknown", text: "Unknown", key: "unknown" };
}

async function renderList() {
  const renderToken = ++state.listRenderToken;
  const activeBuild = getActiveBuild();
  els.list.innerHTML = "";
  els.meta.textContent = `Loaded ${state.index.total_apps} apps. Showing ${state.filtered.length} results.`;

  for (const app of state.filtered) {
    const div = document.createElement("div");
    div.className = "item";
    div.onclick = () => selectApp(app.appid);

    const left = document.createElement("div");
    left.innerHTML = `
      <div class="itemTitle">${app.name || `(appid ${app.appid})`}</div>
      <div class="itemSub">${app.type || "unknown"} · appid ${app.appid}</div>
    `;

    const badge = document.createElement("div");
    badge.className = "badge warn";
    badge.textContent = "Unknown";
    div.dataset.appid = String(app.appid);

    div.appendChild(left);
    div.appendChild(badge);
    els.list.appendChild(div);
  }

  if (!state.filtered.length) return;

  const uniqueShardIds = [...new Set(state.filtered.map(app => shardForAppid(app.appid)))];
  await Promise.all(uniqueShardIds.map(id => loadShard(id)));
  if (renderToken !== state.listRenderToken) return;

  for (const app of state.filtered) {
    const div = els.list.querySelector(`[data-appid="${app.appid}"]`);
    if (!div) continue;

    const badge = div.querySelector(".badge");
    if (!badge) continue;

    const shard = state.shardCache.get(shardForAppid(app.appid)) || [];
    const detailedApp = shard.find(entry => entry.appid === app.appid) || normalizeApp(app);
    const summary = summarizeListMinimum(detailedApp, activeBuild);
    badge.className = badgeClass(summary.status);
    badge.textContent = summary.text;
  }
}

function findCatalogComponent(kind, rawText) {
  const normalized = normalizeAlias(rawText);
  if (!normalized) return null;
  const catalog = state.catalogs[kind] || [];
  let partial = null;

  for (const component of catalog) {
    const aliases = component.aliases || [];
    if (aliases.includes(normalized)) return component;
    if (!partial && aliases.some(alias => alias && (alias.includes(normalized) || normalized.includes(alias)))) {
      partial = component;
    }
  }
  return partial;
}

function compareCatalogComponent(kind, userText, reqMatch) {
  const minScore = reqMatch?.min_score ?? null;
  const reqCandidates = Array.isArray(reqMatch?.candidates) ? reqMatch.candidates : [];
  const reqCandidateIds = reqCandidates.map(candidate => cleanText(typeof candidate === "string" ? candidate : candidate?.id)).filter(Boolean);
  const reqRaw = cleanText(reqMatch?.raw);
  const userComponent = findCatalogComponent(kind, userText);

  if (!reqRaw) return { status: "unknown", text: "Component unknown", method: null };
  if ((kind === "cpu" && isGenericCpuText(reqRaw)) || (kind === "gpu" && isVagueGpuText(reqRaw))) {
    return { status: "unknown", text: "Component unknown", method: null };
  }
  if (!reqCandidates.length || minScore === null) return { status: "unknown", text: "Component not supported", method: null };
  if (!cleanText(userText)) return { status: "unknown", text: "Your component missing", method: null };
  if (!userComponent || userComponent.score === null || userComponent.score === undefined) {
    return { status: "unknown", text: "Your component not recognized", method: null };
  }
  if (reqCandidateIds.includes(userComponent.id)) {
    return { status: "good", text: `${userComponent.name} matches directly`, method: "exact" };
  }
  if (userComponent.score >= minScore) {
    return { status: "good", text: `${userComponent.name} ${userComponent.score} > ${minScore}`, method: "score" };
  }
  return { status: "bad", text: `${userComponent.name} ${userComponent.score} < ${minScore}`, method: "score" };
}

function comparisonSummary(req, build, platform) {
  if (!hasUsableRequirement(req)) return { status: "unknown", text: "Unknown" };
  if (!build?.specs) return { status: "unknown", text: "Unknown" };
  if ((build.platform || "pc") !== platform) return { status: "unknown", text: "Unknown" };

  const checks = buildRequirementChecks(req, build);
  const results = checks.map(check => check.result.status);
  const hasPass = results.includes("good");
  const hasLikely = results.includes("likely");
  const hasUnknown = results.includes("unknown");

  if (results.includes("bad")) return { status: "bad", text: "Below spec" };
  if (results.includes("unlikely")) return { status: "unlikely", text: "Unlikely" };
  if (hasUnknown && (hasPass || hasLikely)) return { status: "partial", text: "Partial" };
  if (hasLikely) return { status: "likely", text: "Likely" };
  if (hasPass) return { status: "good", text: "Pass" };
  if (hasUnknown) return { status: "unknown", text: "Unknown" };
  return { status: "unknown", text: "Unknown" };
}

function renderReqCard(title, req, build, platform) {
  if (!hasUsableRequirement(req)) {
    return `
      <div class="reqCard">
        <div class="reqTitle"><span>${title}</span><span class="badge unknown">Unknown</span></div>
        <div class="reqList">No data</div>
      </div>
    `;
  }

  const summary = comparisonSummary(req, build, platform);
  const cpuCmp = compareCpuRequirement(req, build?.specs?.cpu);
  const gpuCmp = compareGpuRequirement(req, build?.specs?.gpu);
  const ramCmp = req?.ram_gb !== null && req?.ram_gb !== undefined
    ? compareNumeric(build?.specs?.ram_gb, req.ram_gb, "ram")
    : compareAverageFallback(build?.specs?.ram_gb, FALLBACK_AVERAGES.ram_gb, "ram");
  const storageCmp = req?.storage_gb !== null && req?.storage_gb !== undefined
    ? compareNumeric(build?.specs?.storage_gb, req.storage_gb, "storage")
    : compareAverageFallback(build?.specs?.storage_gb, FALLBACK_AVERAGES.storage_gb, "storage");

  return `
    <div class="reqCard">
      <div class="reqTitle">
        <span>${title}</span>
        <span class="${badgeClass(summary.status)}">${summary.text}</span>
      </div>
      <div class="reqList">
        <div class="kv"><span><b>OS</b></span><span class="small">${req.os || "Unknown"}</span></div>
        <div class="kv"><span><b>CPU</b></span><span class="small">${req.cpu || "Unknown"} · ${cpuCmp.text}</span></div>
        <div class="kv"><span><b>GPU</b></span><span class="small">${req.gpu || "Unknown"} · ${gpuCmp.text}</span></div>
        <div class="kv"><span><b>RAM</b></span><span>${fmtGb(req.ram_gb)} · ${ramCmp.text}</span></div>
        <div class="kv"><span><b>Storage</b></span><span>${fmtGb(req.storage_gb)} · ${storageCmp.text}</span></div>
      </div>
    </div>
  `;
}

function renderReqCard(title, req, build, platform) {
  if (!hasUsableRequirement(req)) {
    return `
      <div class="reqCard">
        <div class="reqTitle"><span>${title}</span><span class="badge unknown">Unknown</span></div>
        <div class="reqList">No data</div>
      </div>
    `;
  }

  const summary = comparisonSummary(req, build, platform);
  const cpuCmp = compareCpuRequirement(req, build?.specs?.cpu);
  const gpuCmp = compareGpuRequirement(req, build?.specs?.gpu);
  const ramCmp = req?.ram_gb !== null && req?.ram_gb !== undefined
    ? compareNumeric(build?.specs?.ram_gb, req.ram_gb, "ram")
    : compareAverageFallback(build?.specs?.ram_gb, FALLBACK_AVERAGES.ram_gb, "ram");
  const storageCmp = req?.storage_gb !== null && req?.storage_gb !== undefined
    ? compareNumeric(build?.specs?.storage_gb, req.storage_gb, "storage")
    : compareAverageFallback(build?.specs?.storage_gb, FALLBACK_AVERAGES.storage_gb, "storage");

  return `
    <div class="reqCard">
      <div class="reqTitle">
        <span>${title}</span>
        <span class="${badgeClass(summary.status)}">${summary.text}</span>
      </div>
      <div class="reqList">
        <div class="kv"><span><b>OS</b></span><span class="small">${req.os || "Unknown"}</span></div>
        <div class="kv compareRow ${cpuCmp.status}"><span><b>CPU</b></span><span class="small">${renderComparisonValue(req.cpu || "Unknown", cpuCmp)}</span></div>
        <div class="kv compareRow ${gpuCmp.status}"><span><b>GPU</b></span><span class="small">${renderComparisonValue(req.gpu || "Unknown", gpuCmp)}</span></div>
        <div class="kv compareRow ${ramCmp.status}"><span><b>RAM</b></span><span>${renderComparisonValue(fmtGb(req.ram_gb), ramCmp)}</span></div>
        <div class="kv compareRow ${storageCmp.status}"><span><b>Storage</b></span><span>${renderComparisonValue(fmtGb(req.storage_gb), storageCmp)}</span></div>
      </div>
    </div>
  `;
}

function renderSavedBuildComparisons(minReq, recReq, platform) {
  const builds = state.buildStore?.builds || [];
  if (!builds.length) {
    return `
      <div class="reqCard" style="margin-top:12px">
        <div class="reqTitle"><span>Saved Builds</span><span class="badge warn">None yet</span></div>
        <div class="reqList">Save one or more builds to switch quickly and compare them here.</div>
      </div>
    `;
  }

  const rows = builds.map(build => {
    const minSummary = comparisonSummary(minReq, build, platform);
    const recSummary = comparisonSummary(recReq, build, platform);
    const active = build.id === state.buildStore.activeBuildId ? " (active)" : "";
    const platformName = build.platform === "pc" ? "Windows" : build.platform === "mac" ? "macOS" : "Linux";
    return `
      <div class="kv">
        <span><b>${build.name}${active}</b> <span class="small">(${platformName})</span></span>
        <span>
          <span class="${badgeClass(minSummary.status)}">Min: ${minSummary.text}</span>
          <span class="${badgeClass(recSummary.status)}">Rec: ${recSummary.text}</span>
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
  let platform = getActiveBuild()?.platform || "pc";

  function draw() {
    const activeBuild = getActiveBuild();
    const min = app.requirements?.[platform]?.minimum || null;
    const rec = app.requirements?.[platform]?.recommended || null;
    const hasAny = hasUsableRequirement(min) || hasUsableRequirement(rec);

    els.detail.innerHTML = `
      <div class="h1">${app.name || `(appid ${app.appid})`}</div>
      <div class="h2">${app.type || "unknown"} · appid ${app.appid}</div>
      ${hasAny ? "" : `<div class="h2">No data</div>`}

      <div class="tabs">
        <button class="tab ${platform === "pc" ? "active" : ""}" data-p="pc">Windows</button>
        <button class="tab ${platform === "mac" ? "active" : ""}" data-p="mac">macOS</button>
        <button class="tab ${platform === "linux" ? "active" : ""}" data-p="linux">Linux</button>
      </div>

      <div class="grid2">
        ${renderReqCard("Minimum", min, activeBuild, platform)}
        ${renderReqCard("Recommended", rec, activeBuild, platform)}
      </div>

      ${renderSavedBuildComparisons(min, rec, platform)}

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
  const shard = await loadShard(shardForAppid(appid));
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

async function copyDonationAddress() {
  const address = "bc1qhq2l6nz8qlgfhzhtdc36hr3mtcya5wx8j0meauuevyadzj3dqr9qz33l7t";
  try {
    await navigator.clipboard.writeText(address);
    const original = els.copyBtcLabel?.textContent || "Copy BTC address";
    if (els.copyBtcLabel) els.copyBtcLabel.textContent = "BTC copied";
    window.setTimeout(() => {
      if (els.copyBtcLabel) els.copyBtcLabel.textContent = original;
    }, 1800);
  } catch {
    window.prompt("Copy BTC address", address);
  }
}

async function init() {
  state.buildStore = loadBuildStore();
  syncActiveBuildLabel();
  await loadCatalogs();
  state.index = await loadIndex();

  els.search.addEventListener("input", applyFilters);
  els.filter.addEventListener("change", applyFilters);
  els.openSpecs.onclick = openModal;
  els.closeSpecs.onclick = closeModal;
  els.backdrop.onclick = closeModal;
  els.buildSelect.onchange = () => loadBuildIntoForm(els.buildSelect.value);
  els.specCpu.addEventListener("input", () => updateCatalogFieldHelp("cpu"));
  els.specGpu.addEventListener("input", () => updateCatalogFieldHelp("gpu"));
  els.newBuild.onclick = () => loadBuildIntoForm("");
  if (els.copyBtc) els.copyBtc.onclick = copyDonationAddress;
  els.deleteBuild.onclick = () => {
    deleteSelectedBuild();
    renderList();
    if (state.selected) renderDetail(state.selected);
  };
  els.saveSpecs.onclick = () => {
    const saved = saveCurrentBuildFromForm();
    if (!saved) return;
    closeModal();
    renderList();
    if (state.selected) renderDetail(state.selected);
  };

  applyFilters();
}

init().catch(err => {
  els.meta.textContent = `Failed to load site data: ${err.message}`;
});
