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
  saveSpecs: document.getElementById("saveSpecs")
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

function parseClockGhz(text) {
  const normalized = cleanText(text)?.toLowerCase() || "";
  if (!normalized) return null;

  const ghzMatch = normalized.match(/(\d+(?:\.\d+)?)\s*ghz\b/);
  if (ghzMatch) return Number(ghzMatch[1]);

  const mhzMatch = normalized.match(/(\d+(?:\.\d+)?)\s*mhz\b/);
  if (mhzMatch) return Number(mhzMatch[1]) / 1000;

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

function compareCpuRequirement(req, userText) {
  const catalogCmp = compareCatalogComponent("cpu", userText, req?.cpu_match);
  if (catalogCmp.status !== "unknown") return catalogCmp;

  const reqClock = parseClockGhz(req?.cpu);
  const userClock = getCpuClockGhzFromBuild(userText);
  if (reqClock !== null) {
    if (!cleanText(userText)) return { status: "unknown", text: "Your CPU missing", method: null };
    if (userClock === null) return { status: "unknown", text: "Your CPU clock unknown", method: null };
    if (userClock >= reqClock) return { status: "good", text: `Clock meets (${userClock.toFixed(2)} vs ${reqClock.toFixed(2)} GHz)`, method: "clock" };
    return { status: "bad", text: `Clock below (${userClock.toFixed(2)} vs ${reqClock.toFixed(2)} GHz)`, method: "clock" };
  }

  return catalogCmp;
}

function compareGpuRequirement(req, userText) {
  return compareCatalogComponent("gpu", userText, req?.gpu_match);
}

function buildRequirementChecks(req, build) {
  return [
    { key: "cpu", required: Boolean(cleanText(req?.cpu)), result: compareCpuRequirement(req, build?.specs?.cpu) },
    { key: "gpu", required: Boolean(cleanText(req?.gpu)), result: compareGpuRequirement(req, build?.specs?.gpu) },
    { key: "ram", required: req?.ram_gb !== null && req?.ram_gb !== undefined, result: compareNumeric(build?.specs?.ram_gb, req?.ram_gb) },
    { key: "storage", required: req?.storage_gb !== null && req?.storage_gb !== undefined, result: compareNumeric(build?.specs?.storage_gb, req?.storage_gb) }
  ];
}

function badgeClass(status) {
  if (status === "good") return "badge good";
  if (status === "bad") return "badge bad";
  return "badge warn";
}

function requirementLabel(status) {
  if (status === "good") return "Pass";
  if (status === "bad") return "Fail";
  return "Check";
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
        <span class="${badgeClass(comparison.status)}">${requirementLabel(comparison.status)}</span>
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
        candidates: Array.isArray(req[key]?.candidates) ? req[key].candidates : [],
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

function applyFilters() {
  const q = (els.search.value || "").trim().toLowerCase();
  const mode = els.filter.value;
  let apps = state.index.apps;

  if (mode === "game") apps = apps.filter(a => a.type === "game");
  if (mode === "dlc") apps = apps.filter(a => a.type === "dlc");
  if (mode === "hasreqs") apps = apps.filter(a => a.has_requirements);
  if (q) apps = apps.filter(a => (a.name || "").toLowerCase().includes(q));

  state.filtered = apps.slice(0, 200);
  renderList();
}

function renderList() {
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
    badge.className = app.has_requirements ? "badge good" : "badge warn";
    badge.textContent = app.has_requirements ? "Requirements" : "No reqs";

    div.appendChild(left);
    div.appendChild(badge);
    els.list.appendChild(div);
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
  const reqRaw = cleanText(reqMatch?.raw);
  const userComponent = findCatalogComponent(kind, userText);

  if (!reqRaw) return { status: "unknown", text: "No component requirement", method: null };
  if (!reqCandidates.length || minScore === null) return { status: "unknown", text: "Requirement not normalized yet", method: null };
  if (!cleanText(userText)) return { status: "unknown", text: "Your component missing", method: null };
  if (!userComponent || userComponent.score === null || userComponent.score === undefined) {
    return { status: "unknown", text: "Your component not recognized", method: null };
  }
  if (reqCandidates.includes(userComponent.id)) {
    return { status: "good", text: `Exact catalog match (${userComponent.name})`, method: "exact" };
  }
  if (userComponent.score >= minScore) {
    return { status: "good", text: `Score meets (${userComponent.name}, ${userComponent.score} vs ${minScore})`, method: "score" };
  }
  return { status: "bad", text: `Score below (${userComponent.name}, ${userComponent.score} vs ${minScore})`, method: "score" };
}

function comparisonSummary(req, build, platform) {
  if (!hasUsableRequirement(req)) return { status: "warn", text: "Missing" };
  if (!build?.specs) return { status: "warn", text: "Add your specs" };
  if ((build.platform || "pc") !== platform) return { status: "warn", text: "Wrong platform" };

  const checks = buildRequirementChecks(req, build);
  const results = checks.map(check => check.result);

  if (results.some(check => check.status === "bad")) return { status: "bad", text: "Below spec" };

  const requiredChecks = checks.filter(check => check.required);
  const unresolvedRequired = requiredChecks.filter(check => check.result.status === "unknown");
  const allRequiredGood = requiredChecks.length > 0 && requiredChecks.every(check => check.result.status === "good");

  if (allRequiredGood && !unresolvedRequired.length) {
    return { status: "good", text: "Looks good" };
  }

  return { status: "warn", text: "Partial match" };
}

function renderReqCard(title, req, build, platform) {
  if (!hasUsableRequirement(req)) {
    return `
      <div class="reqCard">
        <div class="reqTitle"><span>${title}</span><span class="badge warn">Missing</span></div>
        <div class="reqList">No reliable requirements data for this platform and level.</div>
      </div>
    `;
  }

  const summary = comparisonSummary(req, build, platform);
  const cpuCmp = compareCpuRequirement(req, build?.specs?.cpu);
  const gpuCmp = compareGpuRequirement(req, build?.specs?.gpu);
  const ramCmp = compareNumeric(build?.specs?.ram_gb, req.ram_gb);
  const storageCmp = compareNumeric(build?.specs?.storage_gb, req.storage_gb);

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
        <div class="reqTitle"><span>${title}</span><span class="badge warn">Missing</span></div>
        <div class="reqList">No reliable requirements data for this platform and level.</div>
      </div>
    `;
  }

  const summary = comparisonSummary(req, build, platform);
  const cpuCmp = compareCpuRequirement(req, build?.specs?.cpu);
  const gpuCmp = compareGpuRequirement(req, build?.specs?.gpu);
  const ramCmp = compareNumeric(build?.specs?.ram_gb, req.ram_gb);
  const storageCmp = compareNumeric(build?.specs?.storage_gb, req.storage_gb);

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
      <div class="h2">${hasAny ? "Parsed from current scrape data." : "This record does not have usable requirements for this platform."}</div>

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

      <div style="margin-top:12px;color:var(--muted);font-size:12px">
        CPU and GPU rows now show how they were evaluated: Exact for direct catalog matches, Score for normalized benchmark comparisons, and Clock for old CPU MHz or GHz fallback checks. Windows builds are not treated as macOS or Linux builds.
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
  els.deleteBuild.onclick = () => {
    deleteSelectedBuild();
    if (state.selected) renderDetail(state.selected);
  };
  els.saveSpecs.onclick = () => {
    const saved = saveCurrentBuildFromForm();
    if (!saved) return;
    closeModal();
    if (state.selected) renderDetail(state.selected);
  };

  applyFilters();
}

init().catch(err => {
  els.meta.textContent = `Failed to load site data: ${err.message}`;
});
