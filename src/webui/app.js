/* B站收藏夹分类工作台 · 新版前端（无框架）
   本轮接真数据：总览 / 条目库（其余页占位，见 index.html）
   后端 API 契约见 src/app_server.py；设计令牌见 theme.css */
const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));
const ROOT = $("#bfp");

async function api(path, body) {
  let r;
  try {
    r = await fetch(path, body ? {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)} : {});
  } catch (e) {
    toast("网络错误：服务未启动或已停止");
    throw e;
  }
  const j = await r.json();
  if (j.error) { toast("出错：" + j.error); throw new Error(j.error); }
  return j;
}
function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove("show"), 2600);
}
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const fmt = (n) => Number(n || 0).toLocaleString("en-US");
/* 遍次报告里的 promoted 在不同版本可能是「数量」或「规则列表」，统一取数量 */
const promCount = (p) => Array.isArray(p) ? p.length : (p || 0);
const STATUS_CN = {auto:"规则", ai:"AI", human:"人工", review:"复核", low:"未分类", none:"不要", hot:"热词", hot2:"个人化"};

function refreshIcons(){ try { window.lucide && lucide.createIcons(); } catch (e) {} }

/* ---------- 个性化偏好（主题/强调色/毛玻璃/密度，localStorage 持久化） ---------- */
let P = {theme:"dark", accent:"indigo", glass:"on", density:"cozy"};
try { Object.assign(P, JSON.parse(localStorage.getItem("bfp_prefs") || "{}")); } catch (e) {}
const savePrefs = () => { try { localStorage.setItem("bfp_prefs", JSON.stringify(P)); } catch (e) {} };

function applyPrefs() {
  setTheme(P.theme, P.theme, true);
  setAccent(P.accent, true);
  setGlass(P.glass === "on", true);
  setDensity(P.density, true);
}
function setTheme(t, mark, skipSave) {
  const resolved = t === "auto"
    ? ((window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches) ? "light" : "dark")
    : t;
  ROOT.dataset.theme = resolved;
  $("#themebtn").innerHTML = '<i data-lucide="' + (resolved === "dark" ? "moon" : "sun") + '"></i>';
  $$(".themeopt").forEach(b => b.classList.toggle("on", b.dataset.t === (mark || t)));
  refreshIcons();
  if (!skipSave) { P.theme = mark || t; savePrefs(); }
}
window.setTheme = setTheme;
window.toggleTheme = function () {
  const next = ROOT.dataset.theme === "dark" ? "light" : "dark";
  setTheme(next, next);
};
function setAccent(a, skipSave) {
  ROOT.dataset.accent = a;
  $$(".adot").forEach(d => d.classList.toggle("on", d.dataset.a === a));
  if (!skipSave) { P.accent = a; savePrefs(); }
}
window.setGlass = function (on, skipSave) {
  ROOT.dataset.glass = on ? "on" : "off";
  const ck = $("#glassck"); if (ck) ck.checked = !!on;
  if (!skipSave) { P.glass = on ? "on" : "off"; savePrefs(); }
};
function setDensity(v, skipSave) {
  ROOT.dataset.density = v;
  $$(".denopt").forEach(b => b.classList.toggle("on", b.dataset.d === v));
  if (!skipSave) { P.density = v; savePrefs(); }
}
window.setDensity = setDensity;
window.toggleSide = function () { ROOT.classList.toggle("sidecol"); };

/* ---------- 页面切换（侧栏 IA：6 导航 + 设置） ---------- */
const T = {dash:["总览","分类流水线一屏掌握"],items:["条目库","筛选、搜索与批量标注"],review:["复核队列","规则改判与低置信条目逐条确认"],tax:["分类与规则","两级分类体系与四块规则"],learn:["学习与评估","盲测重合率 · 语料池 · 热词 · 权重"],wb:["写回","三闸门 · 限额 · 计划预览 · 二次确认"],settings:["设置与个性化","主题 · 强调色 · 材质 · 密度 · 阈值"]};
$$(".nav").forEach(b => b.addEventListener("click", () => {
  $$(".nav").forEach(x => x.classList.toggle("on", x === b));
  $$(".page").forEach(s => s.classList.toggle("on", s.id === "page-" + b.dataset.page));
  $("#ptitle").textContent = T[b.dataset.page][0];
  $("#psub").textContent = T[b.dataset.page][1];
  if (b.dataset.page === "dash") loadOverview();
  if (b.dataset.page === "items") loadItems(1);
}));

/* ---------- 强调色圆点（顶栏 + 设置页共用） ---------- */
$$(".adot").forEach(d => d.addEventListener("click", () => setAccent(d.dataset.a)));

/* ---------- 总览（真数据：/api/overview + /api/guard + /api/eval/report） ---------- */
let OV = null;
async function loadOverview() {
  const [ov, guard, ev] = await Promise.all([
    api("/api/overview"),
    api("/api/guard").catch(() => null),
    api("/api/eval/report").catch(() => null),
  ]);
  OV = ov;
  const c = ov.counts || {};
  const pass = (ov.passes && ov.passes.length) ? ov.passes[ov.passes.length - 1] : null;

  $("#demopill").style.display = ov.demo ? "" : "none";
  $("#connlbl").textContent = ov.demo ? "演示模式 · 虚构数据" : "已配置 config.yaml";

  $("#st-total-v").textContent = fmt(ov.total);
  $("#st-total-d").textContent = "导入于 " + String(ov.imported_at || "–").slice(0, 10);
  const autoed = (c.auto || 0) + (c.hot || 0) + (c.hot2 || 0);
  $("#st-auto-v").textContent = fmt(autoed);
  $("#st-auto-d").textContent = "规则 " + fmt(c.auto || 0) + " · 热词 " + fmt(c.hot || 0) + " · 个人化 " + fmt(c.hot2 || 0);
  $("#st-review-v").textContent = fmt(c.review || 0);
  $("#st-review-d").textContent = pass ? "第 " + pass.no + " 遍改判 " + fmt(pass.changed_total) + " 条" : "尚无流水线记录";
  $("#st-low-v").textContent = fmt(c.low || 0);

  const revN = c.review || 0;
  $("#navrev").textContent = revN;
  $("#navrev").style.display = revN > 0 ? "" : "none";
  $("#revhint").textContent = fmt(revN);

  $("#pass-meta").textContent = pass
    ? "最近一遍：第 " + pass.no + " 遍 · " + pass.at + " · 改判 " + fmt(pass.changed_total) + " 条 · 新强化规则 " + fmt(promCount(pass.promoted)) + " 条"
    : "尚无流水线记录，点「跑一遍」开始自动分类。";
  $("#changed-h").textContent = pass ? "最近改判（第 " + pass.no + " 遍 · 节选）" : "最近改判";
  const ch = (pass && pass.changed && pass.changed.length) ? pass.changed.slice(0, 8) : [];
  $("#changed-body").innerHTML = ch.length
    ? ch.map(x => '<tr><td class="tt"><b title="' + esc(x.title) + '">' + esc(x.title) + '</b></td>'
        + '<td><span class="badge st-low">' + esc(x.old === "-" ? "未分类" : x.old) + '</span></td>'
        + '<td><span class="faint">→</span></td>'
        + '<td><span class="badge st-auto">' + esc(x.new === "-" ? "未分类" : x.new) + '</span></td></tr>').join("")
    : '<tr><td class="faint">暂无改判明细（跑一遍流水线后显示）。</td></tr>';

  const hr = guard && guard.headroom ? guard.headroom : null;
  const moved = hr ? hr.moved_today : 0, perDay = hr ? hr.per_day : 0;
  const pct = perDay > 0 ? Math.min(100, moved / perDay * 100) : 0;
  const qb = $("#wb-quota-bar");
  qb.style.width = pct + "%";
  qb.className = pct > 80 ? "warn" : "";
  $("#wb-quota-n").textContent = hr ? moved + "/" + perDay : "–";
  $("#wbn").textContent = hr ? moved + "/" + perDay : "–";
  $("#wbhint").textContent = fmt(moved);

  const acc = ev && ev.accuracy != null ? Math.round(ev.accuracy * 100) : null;
  const accg = ev && ev.group_accuracy != null ? Math.round(ev.group_accuracy * 100) : null;
  $("#acc-n").textContent = acc == null ? "–" : acc + "%";
  $("#acc-bar").style.width = (acc || 0) + "%";
  $("#accg-n").textContent = accg == null ? "–" : accg + "%";
  $("#accg-bar").style.width = (accg || 0) + "%";

  const list = (ov.by_category || []).filter(x => x[0] !== "（未分类）").slice(0, 8);
  const max = list.length ? list[0][1] : 0;
  const OPS = [.85, .72, .62, .52, .44, .37, .30, .24];
  $("#catdist").innerHTML = list.length
    ? list.map((x, i) => '<div class="dbar"><span>' + esc(x[0]) + '</span><span class="tr"><i style="width:'
        + Math.round(x[1] / max * 100) + '%;opacity:' + OPS[i] + '"></i></span><span class="n">' + fmt(x[1]) + '</span></div>').join("")
    : '<p class="faint" style="margin:6px 0">暂无已分类条目（导入或跑一遍流水线后显示）。</p>';
  refreshIcons();
}

/* ---------- 流水线动作（总览页按钮） ---------- */
async function runPipeline(passes) {
  const btns = [$("#btn-run1"), $("#btn-run2"), $("#btn-aiq")];
  btns.forEach(b => b.disabled = true);
  toast("正在跑流水线，请稍候…");
  try {
    const j = await api("/api/pipeline/run", {passes: passes});
    const r = j.reports && j.reports[j.reports.length - 1];
    if (r) toast("第 " + r.no + " 遍完成：改判 " + fmt(r.changed_total) + " 条 · 新强化规则 " + fmt(promCount(r.promoted)) + " 条");
    await loadOverview();
  } finally {
    btns.forEach(b => b.disabled = false);
  }
}
$("#btn-run1").addEventListener("click", () => runPipeline(1));
$("#btn-run2").addEventListener("click", () => runPipeline(2));
$("#btn-aiq").addEventListener("click", async () => {
  try {
    const j = await api("/api/ai/emit", {});
    toast("已导出 " + fmt(j.count) + " 条到 AI 队列文件");
  } catch (e) {}
});

/* ---------- 条目库（真数据：/api/items + /api/bulk_label） ---------- */
const PS = 50;
const IF = {f: "all", q: "", page: 1};
let CATS = null;

async function ensureCats() {
  if (CATS) return;
  try {
    const tx = await api("/api/taxonomy");
    const names = new Set();
    (tx.groups || []).forEach(g => (g.leaves || []).forEach(l => l && l.name && names.add(l.name)));
    (tx.loose || []).forEach(l => names.add(l && l.name ? l.name : l));
    CATS = Array.from(names).sort((a, b) => a.localeCompare(b, "zh"));
    $("#bulk-cat").innerHTML = '<option value="">设为分类…</option>'
      + CATS.map(n => '<option value="' + esc(n) + '">' + esc(n) + '</option>').join("");
  } catch (e) { CATS = []; }
}

async function loadItems(page) {
  IF.page = page;
  await ensureCats();
  const qs = new URLSearchParams({page: IF.page, page_size: PS, sort: "fav_time"});
  if (IF.f !== "all") qs.set("status", IF.f);
  if (IF.q) qs.set("q", IF.q);
  const j = await api("/api/items?" + qs.toString());
  const pages = Math.max(1, Math.ceil((j.total || 0) / PS));
  $("#itemsbody").innerHTML = (j.items || []).length ? (j.items || []).map(it =>
    '<tr data-aid="' + esc(it.aid) + '">'
    + '<td><input type="checkbox" class="ck" data-aid="' + esc(it.aid) + '" aria-label="选择"></td>'
    + '<td class="tt"><b title="' + esc(it.title) + '">' + esc(it.title) + '</b><span>' + esc(it.up_name || "") + (it.dead ? "（失效）" : "") + '</span></td>'
    + '<td><span class="badge st-' + esc(it.status) + '">' + (STATUS_CN[it.status] || esc(it.status)) + '</span></td>'
    + '<td>' + (it.category ? esc(it.category) : "—") + '</td>'
    + '<td class="faint">' + (esc((it.signals || []).join(" · ")) || "—") + '</td>'
    + '<td class="num mut">' + esc(it.fav_time || "") + '</td></tr>').join("")
    : '<tr><td colspan="6" class="faint">没有符合条件的条目。</td></tr>';
  $("#pginfo").textContent = "每页 " + PS + " · 第 " + j.page + " / " + pages + " 页 · 共 " + fmt(j.total) + " 条";
  $("#pg-prev").disabled = j.page <= 1;
  $("#pg-next").disabled = j.page >= pages;
  bulkSync();
}
$("#pg-prev").addEventListener("click", () => loadItems(Math.max(1, IF.page - 1)));
$("#pg-next").addEventListener("click", () => loadItems(IF.page + 1));
$("#items-toolrow").addEventListener("click", (e) => {
  const chip = e.target.closest(".chip[data-f]");
  if (!chip) return;
  $$("#items-toolrow .chip").forEach(x => x.classList.toggle("on", x === chip));
  IF.f = chip.dataset.f;
  loadItems(1);
});
$("#q").addEventListener("keydown", (e) => {
  if (e.key === "Enter") { IF.q = e.target.value.trim(); loadItems(1); }
});

function bulkSync() {
  const n = $$("#itemsbody input.ck:checked").length;
  $("#bulkbar").classList.toggle("show", n > 0);
  if (n > 0) $("#bulknum").textContent = n;
}
$("#ckall").addEventListener("change", (e) => {
  $$("#itemsbody input.ck").forEach(i => i.checked = e.target.checked);
  bulkSync();
});
$("#itemsbody").addEventListener("change", (e) => { if (e.target.classList.contains("ck")) bulkSync(); });
$("#bulkgo").addEventListener("click", async () => {
  const cat = $("#bulk-cat").value;
  if (!cat) { toast("请先选择要设为的分类"); return; }
  const aids = $$("#itemsbody input.ck:checked").map(i => i.dataset.aid);
  if (!aids.length) { toast("未勾选任何条目"); return; }
  const j = await api("/api/bulk_label", {aids: aids, category: cat});
  toast("已把 " + fmt(j.count) + " 条标为「" + cat + "」");
  $("#ckall").checked = false;
  await loadItems(IF.page);
  loadOverview();
});

/* ---------- 启动 ---------- */
applyPrefs();
refreshIcons();
loadOverview().catch(() => { $("#connlbl").textContent = "连接失败 · 请检查服务"; });
