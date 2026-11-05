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
  if (b.dataset.page === "review") loadReview();
  if (b.dataset.page === "tax") { loadTaxData(); loadRulesData(); }
  if (b.dataset.page === "learn") { loadEvalReport(); loadCorpus(); loadLearnReport(); pollProgress(); }
  if (b.dataset.page === "wb") loadGuard();
  if (b.dataset.page === "settings") loadSettings();
}));

/* ---------- 设置（阈值 + AI 接口，真数据） ---------- */
async function loadSettings() {
  const s = await api("/api/settings");
  $("#s-min-score").value = s.min_score;
  $("#s-min-margin").value = s.min_margin;
  $("#s-min-fields").value = s.min_fields;
  $("#s-reinforce-p").value = s.reinforce_p;
  $("#s-reinforce-min-n").value = s.reinforce_min_n;
  $("#s-promote-cap").value = s.promote_cap;
  $("#llm-url").value = (s.llm || {}).base_url || "";
  $("#llm-model").value = (s.llm || {}).model || "";
}
$("#btn-savesettings").addEventListener("click", async () => {
  await api("/api/settings", {
    min_score: parseFloat($("#s-min-score").value) || 1.0,
    min_margin: parseFloat($("#s-min-margin").value) || 0.3,
    min_fields: parseInt($("#s-min-fields").value) || 2,
    reinforce_p: parseFloat($("#s-reinforce-p").value) || 0.6,
    reinforce_min_n: parseInt($("#s-reinforce-min-n").value) || 5,
    promote_cap: parseInt($("#s-promote-cap").value) || 50,
  });
  toast("设置已保存");
});
$("#btn-savellm").addEventListener("click", async () => {
  await api("/api/settings", {llm: {
    base_url: $("#llm-url").value.trim(),
    model: $("#llm-model").value.trim(),
    api_key: $("#llm-key").value.trim(),
  }});
  toast("LLM 配置已保存（仅存本机 data/app_state.json）");
});
$("#btn-runllm").addEventListener("click", async () => {
  toast("AI 分类中，请稍候…");
  const j = await api("/api/ai/run_llm", {max_items: 300});
  toast("AI 已分类 " + fmt(j.labeled) + " 条");
  loadOverview();
});

/* ---------- 启动 ---------- */

/* ---------- 写回（三闸门 + 限额 + 计划 + APPLY 弹窗；安全语义与旧版一致） ---------- */
let GUARD = null, LAST_PLAN = null;
const GATE_CN = {locked: "锁定", soft: "软保护", free: "自由"};

async function loadGuard() {
  GUARD = await api("/api/guard");
  /* 三闸门计数从 folders 现算（未登记的夹默认=自由，与旧版一致；
     level_counts 只统计显式登记的夹，会漏掉默认自由的 79 个） */
  const cnt = {locked: 0, soft: 0, free: 0};
  (GUARD.folders || []).forEach(x => { cnt[x.guard] = (cnt[x.guard] || 0) + 1; });
  $("#g-lock").textContent = fmt(cnt.locked || 0);
  $("#g-soft").textContent = fmt(cnt.soft || 0);
  $("#g-free").textContent = fmt(cnt.free || 0);
  const mode = (GUARD.move_scope || {}).mode || "minimal";
  $$("#scope-seg button").forEach(b => b.classList.toggle("on", b.dataset.m === mode));
  $("#lim-run").value = (GUARD.write_limits || {}).per_run ?? 200;
  $("#lim-day").value = (GUARD.write_limits || {}).per_day ?? 1000;
  const h = GUARD.headroom || {};
  const pct = h.per_day ? Math.min(100, (h.moved_today || 0) / h.per_day * 100) : 0;
  $("#lim-bar").style.width = pct + "%";
  $("#lim-bar").className = pct > 80 ? "warn" : "";
  $("#lim-headroom-n").textContent = (h.moved_today || 0) + "/" + (h.per_day ?? "–");
  $("#lim-headroom").textContent = "今日（" + (h.today || "-") + "）已移动 " + fmt(h.moved_today || 0)
    + " 条，当日还剩 " + fmt(h.day_remaining || 0) + " 条；本次最多可动 "
    + fmt(Math.min(h.run_remaining || 0, h.day_remaining || 0)) + " 条。";
  renderGuardList();
  renderScopeAllow();
}
function renderGuardList() {
  if (!GUARD) return;
  const f = $("#guard-filter").value, q = ($("#guard-q").value || "").trim().toLowerCase();
  let list = (GUARD.folders || []).slice();
  if (f) list = list.filter(x => x.guard === f);
  if (q) list = list.filter(x => String(x.title || "").toLowerCase().includes(q));
  $("#guard-list").innerHTML = !list.length ? '<p class="hint">没有匹配的收藏夹。</p>'
    : '<table><thead><tr><th>收藏夹</th><th style="width:150px">级别</th><th style="text-align:right">条数</th></tr></thead><tbody>'
      + list.slice(0, 300).map(x => '<tr><td>' + esc(x.title)
        + (x.pool === 2 ? ' <span class="badge st-hot2">池2</span>' : x.pool === 1 ? ' <span class="badge st-hot">池1</span>' : "")
        + '</td><td><select class="inp" data-fid="' + esc(x.folder_id) + '" style="width:130px">'
        + '<option value="locked"' + (x.guard === "locked" ? " selected" : "") + '>🛡 锁定</option>'
        + '<option value="soft"' + (x.guard === "soft" ? " selected" : "") + '>⚠️ 软保护</option>'
        + '<option value="free"' + (x.guard === "free" ? " selected" : "") + '>○ 自由</option></select></td>'
        + '<td class="num mut" style="text-align:right">' + fmt(x.items) + '</td></tr>').join("")
      + '</tbody></table>' + (list.length > 300 ? '<p class="hint">仅显示前 300 个，请用搜索缩小范围。</p>' : "");
}
function currentScopeMode() {
  const on = [...$$("#scope-seg button")].find(b => b.classList.contains("on"));
  return on ? on.dataset.m : "minimal";
}
function renderScopeAllow() {
  if (!GUARD) return;
  const box = $("#scope-allow-box");
  if (currentScopeMode() !== "minimal") {
    box.innerHTML = '<p class="hint" style="margin:0">当前模式：除锁定夹外，任何夹都可以作为移动源，无需白名单。</p>';
    return;
  }
  const allow = new Set((GUARD.move_scope || {}).allow_sources || []);
  const list = (GUARD.folders || []).filter(x => x.items > 0 && x.guard !== "locked");
  box.innerHTML = '<p class="hint" style="margin:0 0 var(--s2)">白名单（允许作为「移动源」，视频会从这些夹被搬出去）：</p><div class="leaves">'
    + (list.length ? list.slice(0, 120).map(x =>
        '<button class="chip scope-cb' + (allow.has(x.folder_id) ? " on" : "") + '" data-fid="' + esc(x.folder_id) + '">'
        + (allow.has(x.folder_id) ? "✓ " : "") + esc(x.title) + ' ' + fmt(x.items) + '</button>').join("")
      : '<span class="faint">没有可选的夹。</span>')
    + '</div>' + (list.length > 120 ? '<p class="hint">仅显示前 120 个。</p>' : "");
}

function renderPlan(j) {
  LAST_PLAN = j;
  const lim = j.limits || {};
  $("#wb-summary").innerHTML = '<p style="margin:0 0 var(--s2)">计划移动 <b class="num">' + fmt(j.total)
    + '</b> 条，' + j.groups.length + ' 组，跳过 ' + fmt(j.skipped) + ' 条。</p>'
    + '<p class="hint">限额：单次 ' + (lim.per_run ?? "-") + ' 条，当日 ' + (lim.per_day ?? "-")
    + ' 条，今日已用 ' + fmt(lim.moved_today ?? 0) + ' → 本次上限 ' + (lim.cap_used ?? "-") + ' 条。</p>'
    + ((j.soft_needs_confirm || []).length
      ? '<p class="hint" style="color:var(--warn)">⚠️ 涉及软保护收藏夹：' + j.soft_needs_confirm.map(esc).join("、") + '，执行时需 CONFIRM-SOFT。</p>' : "")
    + '<table><tbody>' + (j.groups || []).map(g => '<tr><td>' + esc(g.src) + ' <span class="faint">⇒</span> <b>'
      + esc(g.tar) + '</b><span class="faint">（' + esc(g.category) + '）</span>'
      + (g.soft ? ' <span class="badge st-review">软保护</span>' : "")
      + '</td><td class="num mut" style="text-align:right">' + fmt(g.count) + ' 条</td></tr>').join("")
    + '</tbody></table>'
    + '<p class="hint">计划已存 data/app_plan.json；执行前请到 B 站网页端抽查 1–2 条目标夹。</p>';
}

$("#guard-filter").addEventListener("change", renderGuardList);
$("#guard-q").addEventListener("input", renderGuardList);
$("#guard-list").addEventListener("change", async (e) => {
  const sel = e.target.closest("select[data-fid]");
  if (!sel) return;
  await api("/api/guard/set", {folder_id: sel.dataset.fid, level: sel.value});
  toast("已设为：" + GATE_CN[sel.value]);
  loadGuard();
});
$("#scope-seg").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-m]");
  if (!b) return;
  $$("#scope-seg button").forEach(x => x.classList.toggle("on", x === b));
  renderScopeAllow();
});
$("#scope-allow-box").addEventListener("click", (e) => {
  const chip = e.target.closest(".scope-cb");
  if (!chip) return;
  chip.classList.toggle("on");
  chip.textContent = (chip.classList.contains("on") ? "✓ " : "") + chip.textContent.replace(/^✓\s*/, "");
});
$("#btn-savescope").addEventListener("click", async () => {
  const allow = $$("#scope-allow-box .scope-cb.on").map(c => c.dataset.fid);
  await api("/api/scope/set", {mode: currentScopeMode(), allow_sources: allow});
  toast("移动范围已保存");
  loadGuard();
});
$("#btn-savelimits").addEventListener("click", async () => {
  await api("/api/limits/set", {
    per_run: parseInt($("#lim-run").value) || 200,
    per_day: parseInt($("#lim-day").value) || 1000,
  });
  toast("限额已保存");
  loadGuard();
});
$("#wb-status-chips").addEventListener("click", (e) => {
  const chip = e.target.closest(".chip[data-s]");
  if (!chip) return;
  chip.classList.toggle("on");
});
$("#btn-wbplan").addEventListener("click", async () => {
  const statuses = $$("#wb-status-chips .chip.on").map(c => c.dataset.s);
  if (!statuses.length) { toast("至少勾选一个状态"); return; }
  toast("生成计划中…");
  const j = await api("/api/writeback/plan", {statuses: statuses});
  renderPlan(j);
});
$("#btn-apply").addEventListener("click", () => {
  if (!LAST_PLAN || !(LAST_PLAN.groups || []).length) { toast("请先「生成计划（预览）」"); return; }
  $("#dlg-total").textContent = fmt(LAST_PLAN.total);
  $("#dlg-groups").innerHTML = LAST_PLAN.groups.map(g =>
    '<div><span>' + esc(g.src) + ' ⇒ ' + esc(g.tar) + (g.soft ? "（软保护）" : "") + '</span><b class="num">' + fmt(g.count) + ' 条</b></div>').join("");
  $("#dlg-softrow").style.display = (LAST_PLAN.soft_needs_confirm || []).length ? "" : "none";
  $("#applyin").value = ""; $("#softin").value = ""; $("#applygo").disabled = true;
  $("#dlg").showModal();
  refreshIcons();
});
$("#applyin").addEventListener("input", (e) => { $("#applygo").disabled = e.target.value !== "APPLY"; });
$("#dlgclose").addEventListener("click", () => $("#dlg").close());
$("#dlgcancel").addEventListener("click", () => $("#dlg").close());
$("#applygo").addEventListener("click", async () => {
  const body = {confirm: "APPLY"};
  const cs = $("#softin").value.trim();
  if (cs) body.confirm_soft = cs;
  const j = await api("/api/writeback/apply", body);
  $("#dlg").close();
  LAST_PLAN = null;
  $("#wb-result").textContent = "✅ 已移动 " + fmt(j.moved) + " 条，报告：" + j.report;
  toast("已移动 " + fmt(j.moved) + " 条");
  loadGuard();
});

/* ---------- 启动 ---------- */

/* ---------- 学习与评估（真数据：eval / corpus / learn 全链） ---------- */
let BG_POLL = null;
function pollProgress() {
  api("/api/eval/progress").then(j => {
    const text = j.running
      ? "⏳ " + j.task + " " + j.done + "/" + j.total + " " + String(j.current || "").slice(0, 24)
      : (j.error ? "❌ " + j.error : (j.result ? "✅ " + j.result : ""));
    $("#bg-progress").textContent = text;
    if (j.running) { clearTimeout(BG_POLL); BG_POLL = setTimeout(pollProgress, 2000); }
    else if (BG_POLL) { clearTimeout(BG_POLL); BG_POLL = null; if (j.result) toast(j.result); }
  }).catch(() => {});
}

function renderEval(r) {
  if (!r || !r.at) {
    $("#ev-acc").textContent = "–"; $("#ev-accg").textContent = "–"; $("#ev-cov").textContent = "–";
    $("#ev-concl").innerHTML = "<li>还没有评估结果——到「语料与学习」里跑一次盲测。</li>";
    $("#ev-conf").innerHTML = '<p class="faint">暂无分歧数据。</p>';
    $("#ev-detail").innerHTML = "";
    return;
  }
  const acc = Math.round((r.accuracy || 0) * 100), accg = Math.round((r.group_accuracy || 0) * 100);
  const cov = Math.round((r.coverage || 0) * 100);
  $("#ev-acc").textContent = acc + "%"; $("#ev-accg").textContent = accg + "%"; $("#ev-cov").textContent = cov + "%";
  const compat = r.accuracy_compat != null ? Math.round(r.accuracy_compat * 100) : null;
  $("#ev-cov-d").textContent = "真盲测口径 = 评估集中未参与热词学习的 " + fmt((r.out_corpus || {}).n || 0)
    + " 条（协议 v2 修泄漏）"
    + (compat != null ? "；兼容口径（含候选别名）" + compat + "%" : "")
    + (r.in_corpus && r.in_corpus.n ? "；语料内参考 " + fmt(r.in_corpus.n) + " 条 " + Math.round((r.in_corpus.accuracy || 0) * 100) + "%（含泄漏，不作数）" : "");
  $("#ev-concl").innerHTML = (r.conclusion || []).map(c => "<li>" + esc(c) + "</li>").join("") || "<li>（无结论输出）</li>";
  const conf = (r.top_confusions || []).slice(0, 3);
  const max = conf.length ? conf[0][1] : 1;
  const OPS = [.8, .55, .4];
  $("#ev-conf").innerHTML = conf.length ? conf.map((x, i) =>
    '<div class="dbar"><span class="mut" title="' + esc(x[0]) + '">' + esc(x[0]) + '</span><span class="tr"><i style="width:'
    + Math.round(x[1] / max * 100) + '%;opacity:' + OPS[i] + '"></i></span><span class="n">' + fmt(x[1]) + '</span></div>').join("")
    : '<p class="faint">无。</p>';
  const bs = r.by_source || {};
  $("#ev-meta").textContent = "盲测模式：忽略夹来源与标注，仅用规则+热词预测 · 主口径=语料外真盲测（协议 v2）"
    + " · 预测来源（全量客观）：规则 " + fmt(bs.rule || 0) + " / 热词 " + fmt(bs.hot || 0)
    + " / 个人化 " + fmt(bs.hot2 || 0) + " / 未预测 " + fmt(bs.none || 0) + "（评估于 " + r.at + "）";
  $("#ev-detail").innerHTML =
    '<table><thead><tr><th>收藏夹</th><th>口径</th><th>条目</th><th>有预测</th><th>正确</th><th>一致率</th></tr></thead><tbody>'
    + (r.per_folder || []).map(f => '<tr><td>' + esc(f.folder) + '</td><td>'
      + (f.subjective ? '<span class="badge st-hot2">主观</span>' : f.in_corpus ? '<span class="badge st-hot">语料内</span>' : '<span class="badge st-auto">真盲测</span>')
      + '</td><td class="num">' + f.n + '</td><td class="num">'
      + f.covered + '</td><td class="num">' + f.correct + '</td><td class="num">'
      + (f.accuracy === null ? '<span class="faint">未覆盖</span>' : Math.round(f.accuracy * 100) + "%") + '</td></tr>').join("")
    + '</tbody></table>'
    + ((r.alias_candidates || []).length
      ? '<p class="hint" style="margin-top:var(--s3)">候选别名（语料外夹 ≈ 高占比预测夹，待确认）：</p><div class="leaves">'
        + r.alias_candidates.map(c => '<span class="leaf">' + esc(c.folder) + ' ≈ ' + esc(c.target)
          + '<b>' + Math.round(c.frac * 100) + '% · ' + fmt(c.n) + '条</b></span>').join("") + '</div>'
      : "")
    + '<p class="hint" style="margin-top:var(--s3)">高频混淆对（标准答案 ⇒ 引擎判成）：</p><div class="leaves">'
    + (r.top_confusions || []).map(x => '<span class="leaf">' + esc(x[0]) + '<b>' + fmt(x[1]) + '</b></span>').join("")
    + '</div><p class="hint" style="margin-top:var(--s3)">组级混淆对：</p><div class="leaves">'
    + (r.top_group_confusions || []).map(x => '<span class="leaf">' + esc(x[0]) + '<b>' + fmt(x[1]) + '</b></span>').join("")
    + '</div>'
    + ((r.class_metrics || []).length
      ? '<p class="hint" style="margin-top:var(--s3)">类级 P/R/F1（真盲测严格口径，样本小仅供参考）：</p><table><thead><tr><th>分类</th><th>支持数</th><th>精确率</th><th>召回</th><th>F1</th></tr></thead><tbody>'
        + r.class_metrics.filter(c => c.support > 0).slice(0, 20).map(c => '<tr><td>' + esc(c.cls) + '</td><td class="num">' + c.support
          + '</td><td class="num">' + (c.precision == null ? "–" : Math.round(c.precision * 100) + "%")
          + '</td><td class="num">' + (c.recall == null ? "–" : Math.round(c.recall * 100) + "%")
          + '</td><td class="num">' + (c.f1 == null ? "–" : Math.round(c.f1 * 100) + "%") + '</td></tr>').join("")
        + '</tbody></table>'
      : "")
    + ((r.history || []).length
      ? '<p class="hint" style="margin-top:var(--s3)">评估历史（协议 v2 起累积，验收以同口径对比为准）：</p><table><thead><tr><th>时间</th><th>细分（真盲测）</th><th>兼容口径</th><th>组级</th><th>覆盖</th><th>样本</th></tr></thead><tbody>'
        + r.history.slice().reverse().map(h => '<tr><td class="num mut">' + esc(h.at) + '</td><td class="num">'
          + Math.round((h.accuracy || 0) * 100) + '%</td><td class="num">'
          + (h.accuracy_compat == null ? "–" : Math.round(h.accuracy_compat * 100) + "%") + '</td><td class="num">'
          + Math.round((h.group_accuracy || 0) * 100) + '%</td><td class="num">' + Math.round((h.coverage || 0) * 100)
          + '%</td><td class="num">' + fmt(h.n_out) + '</td></tr>').join("")
        + '</tbody></table>'
      : "");
}
async function loadEvalReport() {
  renderEval(await api("/api/eval/report"));
}

async function loadCorpus() {
  const j = await api("/api/corpus");
  $("#cp-p1").textContent = "池1 客观 " + (j.pool1 || []).length + " 夹";
  $("#cp-p2").textContent = "池2 个人化 " + (j.pool2 || []).length + " 夹";
  $("#cp-prot").textContent = "🛡 保护 " + (j.protected || []).length + " 夹";
  $("#corpus-list").innerHTML = (j.folders || []).map(f =>
    '<div class="btnrow" style="margin:0"><select class="inp pool-sel" data-title="' + esc(f.title) + '" style="width:130px">'
    + '<option value="0"' + (f.pool === 0 ? " selected" : "") + '>不参与</option>'
    + '<option value="1"' + (f.pool === 1 ? " selected" : "") + '>池1·客观</option>'
    + '<option value="2"' + (f.pool === 2 ? " selected" : "") + '>池2·个人化</option></select>'
    + '<b style="font-size:var(--fs-sm)">' + esc(f.title) + '</b><span class="faint">' + fmt(f.count) + ' 条</span>'
    + (f.hint ? '<span class="badge st-review">疑似情绪化</span>' : "")
    + (f.protected ? '<span class="badge st-low">🛡已保护</span>' : "") + '</div>').join("")
    || '<p class="faint">评估集为空——先在「评估集与标签工具」里从B站拉取其余收藏夹。</p>';
  $("#cp-status").textContent = "池1 " + (j.pool1 || []).length + " / 池2 " + (j.pool2 || []).length
    + " / 保护 " + (j.protected || []).length + " 个夹";
}

function renderLearn(r) {
  const w = r.best_weights || {};
  const agree = r.reclass_agree || 0, dis = r.reclass_disagree || 0;
  const acc = Math.round((r.heldout_accuracy || 0) * 100);
  $("#learn-result").style.display = "";
  $("#learn-result").innerHTML = '<h3><i data-lucide="graduation-cap"></i>最近一次权重学习</h3>'
    + '<div class="dbar"><span class="mut">留出集准确率</span><span class="tr"><i style="width:' + acc + '%"></i></span><span class="n">' + acc + '%</span></div>'
    + '<div class="dbar"><span class="mut">全语料一致率</span><span class="tr"><i style="width:'
    + Math.round(agree / Math.max(1, agree + dis) * 100) + '%"></i></span><span class="n">'
    + Math.round(agree / Math.max(1, agree + dis) * 100) + '%</span></div>'
    + '<p class="hint">学得权重：标题 ' + esc(w.title) + ' · 标签 ' + esc(w.tag) + ' · UP主 ' + esc(w.up)
    + '（语料 ' + fmt(r.corpus) + ' 条，训练 ' + fmt(r.train) + ' / 留出 ' + fmt(r.test) + ' · ' + esc(r.at || "") + '）</p>'
    + ((r.changed_examples || []).length
      ? '<p class="hint" style="margin-top:var(--s2)">重分类不一致示例（回验发现）：</p><table><tbody>'
        + r.changed_examples.slice(0, 8).map(x => '<tr><td class="tt"><b>' + esc(x.title) + '</b></td><td class="faint">手动: '
          + esc(x.truth) + '</td><td class="faint">引擎: ' + esc(x.pred) + '</td></tr>').join("")
        + '</tbody></table>' : "");
  refreshIcons();
}
async function loadLearnReport() {
  const j = await api("/api/learn/report");
  if (j.weight_report) renderLearn(j.weight_report);
  else if (j.hotword_keys) {
    $("#learn-result").style.display = "";
    $("#learn-result").innerHTML = '<p class="faint">热词表已学习：' + fmt(j.hotword_keys) + ' 个键；尚未做权重回验。</p>';
  }
}

$("#btn-hotwords").addEventListener("click", async () => {
  toast("学习池1热词表中…");
  const j = await api("/api/learn/hotwords", {});
  const s = j.summary;
  toast("池1热词：" + fmt(s.keys) + " 个键（标题 " + fmt(s.by_field.b || 0) + " / 标签 " + fmt(s.by_field.g || 0) + " / UP " + fmt(s.by_field.u || 0) + "）");
  loadLearnReport();
});
$("#btn-hotwords2").addEventListener("click", async () => {
  toast("池2个人化特征学习中…");
  const j = await api("/api/learn/hotwords2", {});
  toast("池2特征键 " + fmt(j.summary.keys) + " 个（命中将归入「个人化」，原夹受保护不动）");
  loadLearnReport();
});
$("#btn-weights").addEventListener("click", async () => {
  toast("学权重 + 切分回验中…");
  const j = await api("/api/learn/weights", {});
  renderLearn(j.report);
  toast("留出集准确率 " + Math.round((j.report.heldout_accuracy || 0) * 100) + "%");
});
$("#cp-sel5").addEventListener("click", () => {
  $$(".pool-sel").forEach(s => {
    const n = parseInt((s.closest(".btnrow").textContent.match(/([0-9,]+) 条/) || [0, "0"])[1].replace(/,/g, ""));
    if (n >= 5) s.value = "1";
  });
});
$("#cp-selall").addEventListener("click", () => $$(".pool-sel").forEach(s => s.value = "0"));
$("#cp-save").addEventListener("click", async () => {
  const pool1 = [], pool2 = [];
  $$(".pool-sel").forEach(s => {
    if (s.value === "1") pool1.push(s.dataset.title);
    if (s.value === "2") pool2.push(s.dataset.title);
  });
  const j = await api("/api/corpus/set", {pool1: pool1, pool2: pool2});
  toast("已保存：池1 " + j.pool1 + " 个，池2 " + j.pool2 + " 个"
    + (j.newly_protected.length ? "；新保护夹：" + j.newly_protected.join("、") : ""));
  loadCorpus();
  loadOverview();
});
$("#btn-evalfetch").addEventListener("click", async () => {
  const exclude = $("#eval-exclude").value.split(/[,，]/).map(s => s.trim()).filter(Boolean);
  await api("/api/eval/fetch", {exclude: exclude});
  toast("后台开始拉取其余收藏夹…");
  clearTimeout(BG_POLL); BG_POLL = setTimeout(pollProgress, 1500);
});
$("#btn-evalrun").addEventListener("click", async () => {
  toast("评估中…");
  const j = await api("/api/eval/run", {});
  renderEval(j.report);
  loadOverview();
  toast("覆盖率 " + Math.round((j.report.coverage || 0) * 100) + "%，细分夹一致率 " + Math.round((j.report.accuracy || 0) * 100) + "%");
});
$("#btn-tags").addEventListener("click", async () => {
  const cap = parseInt($("#tags-cap").value) || 1000;
  const mode = $("#tags-mode").value;
  const workers = Math.max(1, Math.min(4, parseInt($("#tags-workers").value) || 2));
  await api("/api/tags/fetch", {cap: cap, mode: mode, workers: workers});
  toast("后台补拉 " + cap + " 条标签中（" + workers + " 线程）…");
  clearTimeout(BG_POLL); BG_POLL = setTimeout(pollProgress, 1500);
});
$("#btn-ruleimport").addEventListener("click", async () => {
  const j = await api("/api/rules/import", {});
  toast("已回导 " + fmt(j.imported) + " 条热词");
});

/* ---------- 启动 ---------- */

/* ---------- 页内分段切换（分类与规则 / 学习与评估） ---------- */
$$(".seg[data-seg]").forEach(g => g.addEventListener("click", (e) => {
  const b = e.target.closest("button[data-val]");
  if (!b) return;
  $$('.seg[data-seg="' + g.dataset.seg + '"] button').forEach(x => x.classList.toggle("on", x === b));
  $$('[data-segpanel="' + g.dataset.seg + '"]').forEach(p => p.classList.toggle("on", p.dataset.val === b.dataset.val));
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

/* ---------- 复核队列（真数据：review 50 + low 30，确认/不要走 /api/label） ---------- */
const REV = {sort: "margin", page: 1};

function reviewCard(it) {
  const sigs = (it.signals || []).map(s =>
    '<span class="badge" style="--sc:var(--text-3)">' + esc(s) + '</span>').join("");
  const tags = (it.tags || "").split(",").filter(Boolean).slice(0, 6).map(t =>
    '<span class="badge" style="--sc:var(--text-3)">' + esc(t) + '</span>').join("");
  const suggest = it.category
    ? '<span class="badge st-review">建议 ' + esc(it.category) + '</span>'
    : '<span class="badge st-low">低置信 · 分差 ' + Number(it.margin || 0).toFixed(2) + '</span>';
  const meta = esc(it.up_name || "") + " · " + esc(it.fav_time || "") + " · 分数 " + Number(it.score || 0).toFixed(2)
    + ' · <span class="badge st-' + esc(it.status) + '">' + (STATUS_CN[it.status] || esc(it.status)) + '</span>';
  const opts = ['<option value="">未分类</option>'].concat(
    CATS.map(c => '<option ' + (c === it.category ? "selected" : "") + ' value="' + esc(c) + '">' + esc(c) + '</option>')).join("");
  return '<div class="card rev" data-aid="' + esc(it.aid) + '">'
    + '<div><b>' + esc(it.title) + (it.dead ? "（失效）" : "") + '</b>'
    + '<div class="faint" style="margin-top:3px">' + meta + '</div>'
    + '<div class="why">' + suggest + sigs + tags + '</div>'
    + ((it.desc || "") ? '<p class="faint" style="margin:7px 0 0">' + esc(String(it.desc).slice(0, 80)) + '</p>' : "")
    + '</div>'
    + '<div class="btnrow"><select class="inp assign" style="width:160px">' + opts + '</select>'
    + '<button class="btn primary" data-act="save"><i data-lucide="check"></i>确认</button>'
    + '<button class="btn ghost" data-act="none">不要</button></div></div>';
}

async function loadReview(reset) {
  await ensureCats();
  if (reset !== false) {
    REV.page = 1;
    const [jr, jl] = await Promise.all([
      api("/api/items?status=review&sort=" + REV.sort + "&page_size=50&page=1"),
      api("/api/items?status=low&sort=" + REV.sort + "&page_size=30&page=1"),
    ]);
    const rows = jr.items.concat(jl.items);
    $("#rev-count").textContent = "待复核 " + fmt(jr.total) + " 条 · 未分类 " + fmt(jl.total) + " 条";
    $("#reviewlist").innerHTML = rows.length ? rows.map(reviewCard).join("")
      : '<p class="faint">队列空。跑一遍流水线或让 AI 分类后这里会有条目。</p>';
    $("#rev-more").disabled = jr.total <= 50;
  }
  bindReview();
  refreshIcons();
}

function bindReview() {
  $$("#reviewlist .rev").forEach(card => {
    if (card.dataset.bound) return;
    card.dataset.bound = "1";
    const aid = card.dataset.aid;
    card.querySelector('[data-act="save"]').addEventListener("click", async () => {
      const cat = card.querySelector("select.assign").value;
      await api("/api/label", {aid: aid, category: cat});
      toast("已确认 → " + (cat || "未分类"));
      card.remove();
      loadOverview();
    });
    card.querySelector('[data-act="none"]').addEventListener("click", async () => {
      await api("/api/label", {aid: aid, category: "未分类"});
      toast("已标为不要（排除）");
      card.remove();
      loadOverview();
    });
  });
}

$("#rev-more").addEventListener("click", async () => {
  REV.page += 1;
  const j = await api("/api/items?status=review&sort=" + REV.sort + "&page_size=50&page=" + REV.page);
  if (!(j.items || []).length) {
    REV.page -= 1;
    $("#rev-more").disabled = true;
    toast("没有更多了");
    return;
  }
  $("#reviewlist").insertAdjacentHTML("beforeend", j.items.map(reviewCard).join(""));
  bindReview();
  refreshIcons();
});
$("#rev-sort").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-s]");
  if (!b) return;
  $$("#rev-sort button").forEach(x => x.classList.toggle("on", x === b));
  REV.sort = b.dataset.s;
  loadReview();
});

/* ---------- 分类与规则（真数据：/api/taxonomy + /api/rules 四块 CRUD） ---------- */
let TAX = null;
const BLOCK_CN = {manual: "手写", initial: "初筛", ai: "AI", reinforced: "强化"};
let RULES = null, RULE_FILTER = "all";

async function loadTaxData() {
  TAX = await api("/api/taxonomy");
  const groups = TAX.groups || [], loose = TAX.loose || [];
  const allLeaves = groups.reduce((n, g) => n + g.leaves.length, 0) + loose.length;
  const bound = groups.reduce((n, g) => n + g.leaves.filter(l => l.effective_folder).length, 0)
    + loose.filter(l => l.effective_folder).length;
  $("#tax-sum").textContent = groups.length + " 个大分类夹 · " + allLeaves + " 个叶分类 · "
    + bound + " 个已绑收藏夹 · " + (allLeaves - bound) + " 个未绑（写回时跳过）。点叶分类可编辑绑定与归组。";

  $("#tax-groups").innerHTML = groups.map(g => {
    const cnt = g.leaves.reduce((n, l) => n + l.count, 0);
    return '<div class="card"><h3><i data-lucide="folder-tree"></i>' + esc(g.name)
      + ' <span class="faint">' + g.leaves.length + ' 叶 · ' + fmt(cnt) + ' 条</span></h3>'
      + '<div class="btnrow"><label class="faint">B站夹 <input class="inp num g-folder" data-group="' + esc(g.name) + '" value="' + esc(g.folder) + '" style="width:140px" placeholder="media_id"></label>'
      + '<button class="btn ghost" data-act="gsave" data-group="' + esc(g.name) + '">存夹id</button>'
      + '<button class="btn ghost" data-act="gdel" data-group="' + esc(g.name) + '">删除组</button></div>'
      + '<div class="leaves">' + (g.leaves.map(leafChip).join("") || '<span class="faint">空组（还没有叶分类归进来）</span>') + '</div>'
      + '<div class="leafedit" data-editgroup="' + esc(g.name) + '" style="margin-top:var(--s3)"></div></div>';
  }).join("") || '<p class="faint">还没有大分类夹——在上方输入名字新建。</p>';
  $("#tax-loose").innerHTML = loose.map(leafChip).join("") || '<span class="faint">无——所有叶分类都已归组。</span>';
  refreshIcons();
}
function leafChip(l) {
  return '<button class="leaf" data-leaf="' + esc(l.name) + '">' + esc(l.name) + '<b>' + fmt(l.count) + '</b></button>';
}
function openLeafEditor(leafName) {
  let leaf = null, groupName = "";
  (TAX.groups || []).forEach(g => (g.leaves || []).forEach(l => { if (l.name === leafName) { leaf = l; groupName = g.name; } }));
  if (!leaf) (TAX.loose || []).forEach(l => { if (l.name === leafName) { leaf = l; } });
  if (!leaf) return;
  $$("#tax-groups .leafedit").forEach(x => x.innerHTML = "");
  $("#tax-edit-loose").innerHTML = "";
  const holder = groupName
    ? [...$$("#tax-groups .leafedit")].find(x => x.dataset.editgroup === groupName)
    : $("#tax-edit-loose");
  const opts = ['<option value=""' + (groupName ? "" : " selected") + '>（不合并）</option>']
    .concat((TAX.groups || []).map(g => '<option ' + (g.name === groupName ? "selected" : "") + ' value="' + esc(g.name) + '">' + esc(g.name) + '</option>')).join("");
  holder.innerHTML = '<div class="btnrow"><b>' + esc(leafName) + '</b>'
    + '<label class="faint">B站夹 <input class="inp num" data-field="folder" value="' + esc(leaf.folder) + '" placeholder="留空=用大分类夹的" style="width:150px"></label>'
    + '<button class="btn ghost" data-act="lsave" data-leaf="' + esc(leafName) + '">存夹id</button>'
    + '<label class="faint">合并到 <select class="inp" data-field="parent">' + opts + '</select></label>'
    + '<button class="btn ghost" data-act="lparent" data-leaf="' + esc(leafName) + '">确定</button>'
    + '<button class="btn ghost" data-act="eclose">收起</button></div>';
}

let RULE_STATS = {};
async function loadRulesData() {
  await ensureCats();
  $("#r-cat").innerHTML = (CATS || []).map(c => '<option value="' + esc(c) + '">' + esc(c) + '</option>').join("");
  const [rules, stats] = await Promise.all([api("/api/rules"), api("/api/rules/stats").catch(() => ({rules: {}}))]);
  RULES = rules;
  RULE_STATS = stats.rules || {};
  renderRules();
}
function renderRules() {
  const blocks = RULES || {};
  const total = Object.values(blocks).reduce((n, l) => n + (l || []).length, 0);
  $("#rule-sum").textContent = "手写 " + (blocks.manual || []).length + " · 初筛 " + (blocks.initial || []).length
    + " · AI " + (blocks.ai || []).length + " · 强化 " + (blocks.reinforced || []).length + "（共 " + fmt(total) + " 条）";
  const rows = [];
  Object.entries(blocks).forEach(([block, list]) => {
    if (RULE_FILTER !== "all" && RULE_FILTER !== block) return;
    (list || []).forEach(r => rows.push([block, r]));
  });
  $("#rulesbody").innerHTML = rows.length ? rows.map(ruleRow).join("")
    : '<tr><td colspan="8" class="faint">该块暂无规则。</td></tr>';
}
function ruleRow(pair) {
  const block = pair[0], r = pair[1];
  const kws = (r.keywords || []).join("，");
  const pn = (r.p !== undefined && r.p !== null)
    ? ' <span class="faint">P=' + Math.round((r.p || 0) * 100) + '% · n=' + fmt(r.n) + '</span>' : "";
  const mid = (r.mid !== undefined && r.mid !== null) ? " (mid=" + esc(r.mid) + ")" : "";
  const st = RULE_STATS[r.id] || {};
  const precCell = st.fired
    ? '<span class="num">' + Math.round((st.precision || 0) * 100) + '%</span><span class="faint"> · ' + fmt(st.fired) + '次</span>'
    : '<span class="faint">未命中</span>';
  return '<tr>'
    + '<td>' + (BLOCK_CN[block] || esc(block)) + '</td>'
    + '<td>' + esc(r.field) + mid + '</td>'
    + '<td class="faint" style="max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="' + esc(kws) + '">'
    + esc(kws) + (r.regex ? ' / ' + esc(r.regex) + ' /' : "") + pn + '</td>'
    + '<td>' + esc(r.category) + '</td>'
    + '<td class="num">' + esc(r.weight) + '</td>'
    + '<td><span class="badge ' + (r.enabled ? "st-auto" : "st-low") + '">' + (r.enabled ? "启用" : "停用") + '</span>'
    + (r.strong ? ' <span class="badge st-review">强</span>' : "") + '</td>'
    + '<td>' + precCell + '</td>'
    + '<td><button class="btn ghost" data-act="toggle" data-id="' + esc(r.id) + '" data-en="' + (r.enabled ? 0 : 1) + '">' + (r.enabled ? "停用" : "启用") + '</button> '
    + '<button class="btn ghost" data-act="del" data-id="' + esc(r.id) + '">删除</button></td></tr>';
}

$("#btn-addgroup").addEventListener("click", async () => {
  const name = $("#new-group").value.trim();
  if (!name) { toast("填个大分类夹名"); return; }
  await api("/api/taxonomy/group", {name: name});
  $("#new-group").value = "";
  toast("已创建大分类夹 " + name);
  loadTaxData();
});
$("#rule-chips").addEventListener("click", (e) => {
  const chip = e.target.closest(".chip[data-b]");
  if (!chip) return;
  $$("#rule-chips .chip").forEach(x => x.classList.toggle("on", x === chip));
  RULE_FILTER = chip.dataset.b;
  renderRules();
});
$("#btn-addrule").addEventListener("click", async () => {
  const kws = $("#r-kw").value.split(/[,，]/).map(s => s.trim()).filter(Boolean);
  if (!kws.length && !$("#r-regex").value.trim()) { toast("至少填关键词或正则"); return; }
  const j = await api("/api/rules/add", {
    block: $("#r-block").value, field: $("#r-field").value, keywords: kws,
    regex: $("#r-regex").value.trim(), category: $("#r-cat").value,
    weight: parseFloat($("#r-weight").value) || 1.0, strong: $("#r-strong").checked,
  });
  toast("规则已添加 " + j.rule.id);
  $("#r-kw").value = ""; $("#r-regex").value = "";
  loadRulesData();
});
$("#page-tax").addEventListener("click", async (e) => {
  const chip = e.target.closest("button.leaf[data-leaf]");
  if (chip) { openLeafEditor(chip.dataset.leaf); return; }
  const b = e.target.closest("[data-act]");
  if (!b) return;
  const act = b.dataset.act;
  if (act === "gsave") {
    const inp = [...$$("#tax-groups .g-folder")].find(i => i.dataset.group === b.dataset.group);
    await api("/api/taxonomy/folder", {kind: "group", name: b.dataset.group, folder: inp ? inp.value : ""});
    toast("已保存大分类夹绑定 " + b.dataset.group);
    loadTaxData();
  } else if (act === "gdel") {
    await api("/api/taxonomy/group_delete", {name: b.dataset.group});
    toast("已删除组（叶分类保留）");
    loadTaxData();
  } else if (act === "lsave") {
    const row = b.closest(".btnrow");
    await api("/api/taxonomy/folder", {kind: "leaf", name: b.dataset.leaf, folder: row.querySelector('[data-field="folder"]').value});
    toast("已保存叶分类绑定 " + b.dataset.leaf);
    loadTaxData();
  } else if (act === "lparent") {
    const row = b.closest(".btnrow");
    await api("/api/taxonomy/leaf_parent", {leaf: b.dataset.leaf, parent: row.querySelector('[data-field="parent"]').value});
    toast(b.dataset.leaf + " 归组已更新");
    loadTaxData();
  } else if (act === "eclose") {
    b.closest(".leafedit").innerHTML = "";
    $("#tax-edit-loose").innerHTML = "";
  } else if (act === "toggle") {
    await api("/api/rules/toggle", {id: b.dataset.id, enabled: b.dataset.en === "1"});
    loadRulesData();
  } else if (act === "del") {
    await api("/api/rules/delete", {id: b.dataset.id});
    toast("规则已删除");
    loadRulesData();
  }
});

/* ---------- 启动 ---------- */
applyPrefs();
refreshIcons();
loadOverview().catch(() => { $("#connlbl").textContent = "连接失败 · 请检查服务"; });
