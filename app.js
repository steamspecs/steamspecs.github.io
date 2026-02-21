const state = {
  index: null,
  filtered: [],
  selected: null,
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

  specCpu: document.getElementById("specCpu"),
  specGpu: document.getElementById("specGpu"),
  specRam: document.getElementById("specRam"),
  specVram: document.getElementById("specVram"),
  specStorage: document.getElementById("specStorage"),
  saveSpecs: document.getElementById("saveSpecs"),
  clearSpecs: document.getElementById("clearSpecs")
};

function loadSpecs() {
  try {
    const raw = localStorage.getItem("steamSpecChecker_specs");
    if (!raw) return null;
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function saveSpecs(specs) {
  localStorage.setItem("steamSpecChecker_specs", JSON.stringify(specs));
}

function clearSpecs() {
  localStorage.removeItem("steamSpecChecker_specs");
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
  if (reqVal === null || reqVal === undefined || Number.isNaN(reqVal)) return { status: "unknown", text: "No numeric requirement" };
  if (userVal === null || userVal === undefined || Number.isNaN(userVal)) return { status: "unknown", text: "Your value missing" };
  if (userVal >= reqVal) return { status: "good", text: `Meets (${userVal} vs ${reqVal})` };
  return { status: "bad", text: `Below (${userVal} vs ${reqVal})` };
}

function badgeClass(status) {
  if (status === "good") return "badge good";
  if (status === "bad") return "badge bad";
  return "badge warn";
}

async function loadIndex() {
  const res = await fetch("data/index.json", { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to load index");
  return await res.json();
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
  state.shardCache.set(shardId, data);
  return data;
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
  els.meta.textContent = `Loaded ${total} apps. Showing ${shown} results.`;

  for (const a of state.filtered) {
    const div = document.createElement("div");
    div.className = "item";
    div.onclick = () => selectApp(a.appid);

    const left = document.createElement("div");
    const t = document.createElement("div");
    t.className = "itemTitle";
    t.textContent = a.name || `(appid ${a.appid})`;

    const s = document.createElement("div");
    s.className = "itemSub";
    s.textContent = `${a.type || "unknown"} · appid ${a.appid}`;

    left.appendChild(t);
    left.appendChild(s);

    const b = document.createElement("div");
    b.className = a.has_requirements ? "badge good" : "badge warn";
    b.textContent = a.has_requirements ? "Requirements" : "No reqs";

    div.appendChild(left);
    div.appendChild(b);
    els.list.appendChild(div);
  }
}

function pickReq(app, platform, level) {
  const req = app.requirements?.[platform]?.[level] || null;
  return req;
}

function renderReqCard(title, req, userSpecs) {
  if (!req) {
    return `
      <div class="reqCard">
        <div class="reqTitle">${title}<span class="badge warn">Missing</span></div>
        <div class="reqList">No requirements data for this platform and level.</div>
      </div>
    `;
  }

  const ramCmp = compareNumeric(userSpecs?.ram_gb, req.ram_gb);
  const vramCmp = compareNumeric(userSpecs?.vram_gb, req.vram_gb);
  const stoCmp = compareNumeric(userSpecs?.storage_gb, req.storage_gb);

  return `
    <div class="reqCard">
      <div class="reqTitle">
        <span>${title}</span>
        <span class="${badgeClass(ramCmp.status === "bad" || vramCmp.status === "bad" || stoCmp.status === "bad" ? "bad" : "good")}">
          ${userSpecs ? "Compared" : "Set your specs"}
        </span>
      </div>
      <div class="reqList">
        <div class="kv"><span><b>OS</b></span><span class="small">${req.os || "Unknown"}</span></div>
        <div class="kv"><span><b>CPU</b></span><span class="small">${req.cpu || "Unknown"}</span></div>
        <div class="kv"><span><b>GPU</b></span><span class="small">${req.gpu || "Unknown"}</span></div>

        <div class="kv"><span><b>RAM</b></span><span>${fmtGb(req.ram_gb)} ${userSpecs ? ` · ${ramCmp.text}` : ""}</span></div>
        <div class="kv"><span><b>VRAM</b></span><span>${fmtGb(req.vram_gb)} ${userSpecs ? ` · ${vramCmp.text}` : ""}</span></div>
        <div class="kv"><span><b>Storage</b></span><span>${fmtGb(req.storage_gb)} ${userSpecs ? ` · ${stoCmp.text}` : ""}</span></div>

        <div class="kv"><span><b>DirectX</b></span><span>${fmtNum(req.directx)}</span></div>
        <div class="kv"><span><b>OpenGL</b></span><span>${fmtNum(req.opengl)}</span></div>
        <div class="kv"><span><b>Vulkan</b></span><span>${req.vulkan ? "Yes" : "Unknown or no"}</span></div>

        ${req.notes ? `<div class="kv"><span><b>Notes</b></span><span class="small">${req.notes}</span></div>` : ""}
      </div>
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

    els.detail.innerHTML = `
      <div class="h1">${app.name || `(appid ${app.appid})`}</div>
      <div class="h2">${app.type || "unknown"} · appid ${app.appid}</div>

      <div class="tabs">
        <button class="tab ${platform === "pc" ? "active" : ""}" data-p="pc">Windows</button>
        <button class="tab ${platform === "mac" ? "active" : ""}" data-p="mac">macOS</button>
        <button class="tab ${platform === "linux" ? "active" : ""}" data-p="linux">Linux</button>
      </div>

      <div class="grid2">
        ${renderReqCard("Minimum", min, userSpecs)}
        ${renderReqCard("Recommended", rec, userSpecs)}
      </div>

      <div style="margin-top:12px;color:var(--muted);font-size:12px">
        CPU and GPU matching is shown as text only. Numeric comparisons apply to RAM, VRAM, and storage when available.
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

  const s = state.specs || {};
  els.specCpu.value = s.cpu || "";
  els.specGpu.value = s.gpu || "";
  els.specRam.value = s.ram_gb ?? "";
  els.specVram.value = s.vram_gb ?? "";
  els.specStorage.value = s.storage_gb ?? "";
}

function closeModal() {
  els.backdrop.classList.add("hidden");
  els.modal.classList.add("hidden");
}

function readSpecsFromForm() {
  const toNum = (v) => {
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  };
  return {
    cpu: els.specCpu.value.trim() || null,
    gpu: els.specGpu.value.trim() || null,
    ram_gb: toNum(els.specRam.value),
    vram_gb: toNum(els.specVram.value),
    storage_gb: toNum(els.specStorage.value)
  };
}

async function init() {
  state.specs = loadSpecs();
  state.index = await loadIndex();

  els.search.addEventListener("input", applyFilters);
  els.filter.addEventListener("change", applyFilters);

  els.openSpecs.onclick = openModal;
  els.closeSpecs.onclick = closeModal;
  els.backdrop.onclick = closeModal;

  els.saveSpecs.onclick = () => {
    state.specs = readSpecsFromForm();
    saveSpecs(state.specs);
    closeModal();
    if (state.selected) renderDetail(state.selected);
  };

  els.clearSpecs.onclick = () => {
    state.specs = null;
    clearSpecs();
    closeModal();
    if (state.selected) renderDetail(state.selected);
  };

  applyFilters();
}

init().catch(err => {
  els.meta.textContent = `Failed to load site data: ${err.message}`;
});