/* B站收藏夹分类工作台 前端逻辑（无框架） */
const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));

async function api(path, body) {
  const opt = body ? {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)} : {};
  const r = await fetch(path, opt);
  const j = await r.json();
  if (j.error) { toast("出错：" + j.error); throw new Error(j.error); }
  return j;
}
function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), 2600);
}
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const STATUS_CN = {auto:"规则", ai:"AI", human:"人工", review:"复核", low:"未分类", none:"不要", hot:"热词", hot2:"个人化"};

let CATEGORIES = [];   // 初始分类名列表
let itemsPage = 1;

/* ---------- 标签页 ---------- */
$$("#tabs button").forEach(b => b.onclick = () => {
  $$("#tabs button").forEach(x => x.classList.remove("on"));
  b.classList.add("on");
  $$("main > section").forEach(s => s.classList.add("hide"));
  $("#tab-" + b.dataset.tab).classList.remove("hide");
  const tab = b.dataset.tab;
  if (tab === "dash") loadOverview();
  if (tab === "review") loadReview();
  if (tab === "items") loadItems(1);
  if (tab === "tax") loadTax();
  if (tab === "rules") loadRules();
  if (tab === "eval") { loadEvalReport(); loadCorpus(); loadLearnReport(); pollProgress(); }
  if (tab === "fun") loadFun();
  if (tab === "wb") { loadSettings(); loadGuard(); }
});

/* ---------- 趣味数据 ---------- */
async function loadFun() {
  const d = await api("/api/insights");
  const pct = (n, total) => total ? Math.round(n / total * 100) : 0;
  $("#fun-cards").innerHTML = [
    ["总收藏", d.total], ["关注UP数", d.unique_ups], ["不同标签", d.unique_tags],
    ["标签覆盖率", Math.round(d.tag_coverage * 100) + "%"], ["失效视频", d.dead],
    ["最疯狂月份", `${d.busiest_month[0] || "-"}（${d.busiest_month[1] || 0}条）`],
  ].map(x => `<div class="card"><b>${esc(x[1])}</b><span>${x[0]}</span></div>`).join("");
  const bars = (rows, total, color) => rows.map(([name, n]) => `
    <div class="row" style="margin:2px 0">
      <span style="width:180px;display:inline-block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(name)}">${esc(name)}</span>
      <span class="bar ${color}"><i style="width:${pct(n, total)}%"></i></span>
      <span class="muted">${n}（${pct(n, total)}%）</span>
    </div>`).join("");
  const tagTotal = d.top_tags.length ? d.top_tags[0][1] : 1;
  const upTotal = d.top_ups.length ? d.top_ups[0][1] : 1;
  $("#fun-tags").innerHTML = bars(d.top_tags, tagTotal, "") || "<em class='muted'>tags 还在补拉中，拉完这里就有了。</em>";
  $("#fun-ups").innerHTML = bars(d.top_ups, upTotal, "g");
  const mTotal = d.monthly.length ? Math.max(...d.monthly.map(x => x[1])) : 1;
  $("#fun-monthly").innerHTML = bars(d.monthly, mTotal, "");
  const cTotal = d.category_rank.length ? d.category_rank[0][1] : 1;
  $("#fun-cats").innerHTML = bars(d.category_rank, cTotal, "g");
}

/* ---------- 流水线页 ---------- */
async function loadOverview() {
  const ov = await api("/api/overview");
  const c = ov.counts;
  const cards = [
    ["总数", ov.total, ""],
    ["规则命中", c.auto || 0, "st-auto"],
    ["AI已分", c.ai || 0, "st-ai"],
    ["人工已分", c.human || 0, "st-human"],
    ["待复核", c.review || 0, "st-review"],
    ["未分类", (c.low || 0) + (c.none || 0), "st-low"],
  ];
  $("#stat-cards").innerHTML = cards.map(x =>
    `<div class="card"><b class="${x[2]}">${x[1]}</b>${x[0]}</div>`).join("");

  const max = Math.max(1, ...(ov.by_category.filter(x => x[0] !== "（未分类）").map(x => x[1])));
  $("#cat-dist").innerHTML = ov.by_category.map(([name, n]) => {
    const w = name === "（未分类）" ? 0 : Math.round(n / max * 100);
    return `<div class="row"><span style="width:130px;display:inline-block">${esc(name)}</span>
      <span class="bar"><i style="width:${w}%"></i></span> ${n}</div>`;
  }).join("");

  const tb = $("#stats-table tbody");
  tb.innerHTML = (ov.top_stats || []).slice(0, 40).map(s => {
    const on = s.p >= 0.6 && s.n >= 5;
    return `<tr class="${on ? "" : "muted"}"><td>${esc(s.key)}</td><td>${esc(s.category)}</td>
      <td>${Math.round(s.p * 100)}%</td><td>${s.n}</td>
      <td>${on ? "✅ 可强化" : "样本/概率不足"}</td></tr>`;
  }).join("");

  const pl = $("#pass-list");
  pl.innerHTML = (ov.passes || []).slice().reverse().map(p =>
    `<div class="rev-card">第 ${p.no} 遍（${esc(p.at)}）：
      规则命中 ${p.counts.auto || 0} · AI ${p.counts.ai || 0} · 人工 ${p.counts.human || 0} ·
      待复核 ${p.counts.review || 0} · 未分类 ${(p.counts.low || 0) + (p.counts.none || 0)} ·
      <b>改判 ${p.changed_total}</b> 条 · 新强化规则 ${p.promoted.length} 条
      ${p.promoted.length ? "<div class='muted'>强化：" + p.promoted.map(r => esc(r.keyword + "→" + r.category + " P=" + Math.round(r.p * 100) + "%")).join("；") + "</div>" : ""}
    </div>`).join("") || "<em>还没有跑过。</em>";

  $("#side-foot").innerHTML =
    (ov.demo ? "<b style='color:#e0a800'>🧪 DEMO 模式</b><br>" : "") +
    `共 ${ov.total} 条<br>规则 ${ov.rules.manual + ov.rules.initial} · AI规则 ${ov.rules.ai} · 强化 ${ov.rules.reinforced}`;
}

/* ---------- 手动分类对比 ---------- */
let pollTimer = null;
async function pollProgress() {
  const j = await api("/api/eval/progress");
  const el = $("#eval-progress"), tp = $("#tags-progress");
  const text = j.running
    ? `⏳ ${j.task} ${j.done}/${j.total} ${esc(j.current).slice(0, 24)}`
    : (j.error ? "❌ " + esc(j.error) : (j.result ? "✅ " + esc(j.result) : ""));
  if (j.task === "tags") { if (tp) tp.textContent = text; }
  else { if (el) el.textContent = text; }
  if (j.running) {
    pollTimer = setTimeout(pollProgress, 2000);
  } else if (pollTimer) {
    clearTimeout(pollTimer); pollTimer = null;
    if (j.result && j.task === "eval_fetch") toast(j.result);
    if (j.result && j.task === "tags") toast(j.result);
  }
}
async function evalFetch() {
  const exclude = $("#eval-exclude").value.split(/[,，]/).map(s => s.trim()).filter(Boolean);
  await api("/api/eval/fetch", {exclude});
  toast("后台开始拉取其余收藏夹…");
  pollProgress();
}
async function evalRun() {
  toast("评估中…");
  const j = await api("/api/eval/run", {});
  renderEval(j.report);
  toast(`覆盖率 ${Math.round(j.report.coverage * 100)}%，一致率 ${Math.round(j.report.accuracy * 100)}%`);
}
async function loadEvalReport() {
  const r = await api("/api/eval/report");
  if (r && r.at) renderEval(r);
}
function renderEval(r) {
  if (!r || !r.at) { $("#eval-report").innerHTML = "<em class='muted'>还没有评估结果。</em>"; return; }
  const acc = Math.round((r.accuracy || 0) * 100), cov = Math.round((r.coverage || 0) * 100);
  const bs = r.by_source || {};
  $("#eval-report").innerHTML = `
    <div class="cards">
      <div class="card"><b>${r.total}</b><span>人工分类条目</span></div>
      <div class="card"><b>${cov}%</b><span>盲测覆盖率（${r.covered}条有预测）</span></div>
      <div class="card"><b class="${acc >= 60 ? "" : "st-review"}">${acc}%</b><span>盲测重合率</span></div>
      <div class="card"><b>${r.correct}</b><span>预测正确条数</span></div>
      <div class="card"><b>${r.dead}</b><span>失效跳过</span></div>
    </div>
    <p class="muted">${esc(r.mode || "")} · 预测来源：规则 ${bs.rule || 0} / 热词 ${bs.hot || 0} / 个人化 ${bs.hot2 || 0} / 未预测 ${bs.none || 0}（评估于 ${esc(r.at)}）</p>
    ${(r.conclusion || []).length ? `<div class="panel" style="background:#f4f9ff"><b>📌 结论</b><ul style="margin:6px 0 0 18px;padding:0">${r.conclusion.map(c => `<li>${esc(c)}</li>`).join("")}</ul></div>` : ""}
    <div class="panel"><h3>各收藏夹（标准答案）命中情况（评估于 ${esc(r.at)}）</h3>
      <table><thead><tr><th>收藏夹</th><th>条目</th><th>有预测</th><th>正确</th><th>一致率</th></tr></thead><tbody>
      ${r.per_folder.map(f => `
        <tr><td>${esc(f.folder)}</td><td>${f.n}</td><td>${f.covered}</td><td>${f.correct}</td>
        <td>${f.accuracy === null ? "<span class='muted'>未覆盖</span>"
            : `<span class="bar ${f.accuracy >= 0.6 ? "g" : ""}"><i style="width:${Math.round(f.accuracy * 100)}%"></i></span> ${Math.round(f.accuracy * 100)}%`}</td></tr>`).join("")}
      </tbody></table></div>
    <div class="panel"><h3>高频混淆对（标准答案 ⇒ 引擎判成）</h3>
      ${r.top_confusions.map(([k, n]) => `<span class="tag">${esc(k)} ×${n}</span>`).join(" ") || "<em class='muted'>无</em>"}
    </div>`;
}
async function fetchTags() {
  const cap = parseInt($("#tags-cap").value) || 1000;
  const mode = $("#tags-mode").value;
  const workers = Math.max(1, Math.min(4, parseInt($("#tags-workers").value) || 2));
  await api("/api/tags/fetch", {cap, mode, workers});
  toast(`后台补拉 ${cap} 条标签中（${workers} 线程）…`);
  pollProgress();
}

/* ---------- 语料双池 + 热词/权重学习 ---------- */
async function loadCorpus() {
  const j = await api("/api/corpus");
  $("#corpus-list").innerHTML = j.folders.map(f => `
    <label class="rule-row" style="border:0">
      <select class="pool-sel" data-title="${esc(f.title)}">
        <option value="0" ${f.pool === 0 ? "selected" : ""}>不参与</option>
        <option value="1" ${f.pool === 1 ? "selected" : ""}>池1·客观</option>
        <option value="2" ${f.pool === 2 ? "selected" : ""}>池2·个人化</option>
      </select>
      <b>${esc(f.title)}</b> <span class="muted">${f.count} 条</span>
      ${f.hint ? "<span class='tag' style='background:#fff3e0;color:#b26a00'>疑似情绪化</span>" : ""}
      ${f.protected ? "<span class='tag' style='background:#fde8e8;color:#b02a2a'>🛡已保护</span>" : ""}
    </label>`).join("") || "<em class='muted'>评估集为空，先点①从B站拉取。</em>";
  $("#corpus-status").textContent =
    `池1 ${j.pool1.length} 个 / 池2 ${j.pool2.length} 个 / 保护 ${j.protected.length} 个夹`;
}
async function corpusSave() {
  const pool1 = [], pool2 = [];
  $$(".pool-sel").forEach(s => {
    if (s.value === "1") pool1.push(s.dataset.title);
    if (s.value === "2") pool2.push(s.dataset.title);
  });
  const j = await api("/api/corpus/set", {pool1, pool2});
  toast(`已保存：池1 ${j.pool1} 个，池2 ${j.pool2} 个` +
        (j.newly_protected.length ? `；新保护夹：${j.newly_protected.join("、")}` : ""));
  loadCorpus();
}
function corpusSelectN(minN) {
  $$(".pool-sel").forEach(s => {
    const row = s.closest("label");
    const n = parseInt((row.textContent.match(/(\d+) 条/) || [0, 0])[1]);
    if (n >= minN) s.value = "1";
  });
}
function corpusSelectAll(on) { $$(".pool-sel").forEach(s => s.value = on ? "1" : "0"); }
async function learnHotwords() {
  toast("学习池1热词表中…");
  const j = await api("/api/learn/hotwords", {});
  const s = j.summary;
  toast(`池1热词：${s.keys} 个键（标题 ${s.by_field.b || 0} / 标签 ${s.by_field.g || 0} / UP ${s.by_field.u || 0}）`);
  loadLearnReport();
}
async function learnHotwords2() {
  toast("池2个人化特征学习中…");
  const j = await api("/api/learn/hotwords2", {});
  toast(`池2特征键 ${j.summary.keys} 个（命中将归入「个人化」，原夹受保护不动）`);
  loadLearnReport();
}
async function learnWeights() {
  toast("学权重+回验中…");
  const j = await api("/api/learn/weights", {});
  renderLearn(j.report);
  toast(`留出集准确率 ${Math.round(j.report.heldout_accuracy * 100)}%`);
}
async function importRules() {
  const j = await api("/api/rules/import", {});
  toast(`已回导 ${j.imported} 条热词`);
}
async function loadLearnReport() {
  const j = await api("/api/learn/report");
  if (j.weight_report) renderLearn(j.weight_report);
  else if (j.hotword_keys) $("#learn-report").innerHTML =
    `<p class="muted">热词表已学习：${j.hotword_keys} 个键；尚未做权重回验。</p>`;
}
function renderLearn(r) {
  const w = r.best_weights || {};
  $("#learn-report").innerHTML = `
    <div class="cards">
      <div class="card"><b>${Math.round((r.heldout_accuracy || 0) * 100)}%</b><span>留出集准确率（${r.test}条）</span></div>
      <div class="card"><b>${Math.round((r.reclass_agree || 0) / Math.max(1, (r.reclass_agree || 0) + (r.reclass_disagree || 0)) * 100)}%</b><span>全语料重分类一致率</span></div>
      <div class="card"><b>${r.keys_train || "-"}</b><span>训练切分热词键数</span></div>
    </div>
    <p>学习权重：标题 <b>${w.title}</b> · 标签 <b>${w.tag}</b> · UP主 <b>${w.up}</b>
       <span class="muted">（评估于 ${esc(r.at)}，语料 ${r.corpus} 条，训练 ${r.train} / 留出 ${r.test}）</span></p>
    ${(r.top_trials || []).length ? `<p class="muted">权重试验TOP5：${r.top_trials.map(t =>
      `标题${t.w.title}/标签${t.w.tag}/UP${t.w.up}→${Math.round(t.acc * 100)}%`).join("；")}</p>` : ""}
    ${(r.changed_examples || []).length ? `<p><b>重分类不一致示例（回验发现）：</b></p>
      <table><tbody>${r.changed_examples.slice(0, 10).map(x =>
        `<tr><td>${esc(x.title)}</td><td class="muted">手动: ${esc(x.truth)}</td><td>引擎: ${esc(x.pred)}</td></tr>`).join("")}</tbody></table>` : ""}`;
}
$("#btn-run1").onclick = async () => { toast("跑一遍中…"); const j = await api("/api/pipeline/run", {passes: 1}); toast("完成：改判 " + j.reports[0].changed_total + " 条，新强化 " + j.reports[0].promoted.length + " 条"); loadOverview(); };
$("#btn-run2").onclick = async () => { toast("连跑两遍…"); const j = await api("/api/pipeline/run", {passes: 2}); const last = j.reports[j.reports.length - 1]; toast("两遍完成：末遍改判 " + last.changed_total + " 条"); loadOverview(); };
$("#btn-ai-emit").onclick = async () => { const j = await api("/api/ai/emit", {}); toast("已导出 " + j.count + " 条 → " + j.file); };
$("#btn-ai-import").onclick = async () => { const j = await api("/api/ai/import", {}); toast("已导入 " + j.count + " 条AI结果"); loadOverview(); };
$("#btn-ai-llm").onclick = () => runLLM();

/* ---------- 待审复核 ---------- */
async function loadReview() {
  const sort = $("#rev-sort").value;
  const j = await api("/api/items?status=review&sort=" + sort + "&page_size=50&page=1");
  const j2 = await api("/api/items?status=low&sort=" + sort + "&page_size=30&page=1");
  const rows = j.items.concat(j2.items);
  $("#review-list").innerHTML = rows.map(it => reviewCard(it)).join("") ||
    "<em>队列空。跑一遍流水线或让AI分类后这里会有条目。</em>";
  bindAssign();
}
function reviewCard(it) {
  const sigs = (it.signals || []).map(s => `<span class="tag">${esc(s)}</span>`).join(" ");
  const tags = (it.tags || "").split(",").filter(Boolean).slice(0, 6).map(t => `<span class="tag">${esc(t)}</span>`).join("");
  return `<div class="rev-card" data-aid="${it.aid}">
    <div class="t">${esc(it.title)}</div>
    <div class="muted">UP：${esc(it.up_name)} ｜ ${esc(it.fav_time)} ｜ 分数 ${it.score} ｜ 状态 <span class="st-${it.status}">${STATUS_CN[it.status] || it.status}</span> ｜ 信号：${sigs || "无"}</div>
    <div>${tags}</div>
    <div class="muted">${esc((it.desc || "").slice(0, 80))}</div>
    <div class="row">设为 ${catSelect(it.category, "assign")} <button data-act="save">确认</button>
      <button data-act="none">标为不要</button></div>
  </div>`;
}
function catSelect(current, cls) {
  const opts = ['<option value="">未分类</option>'].concat(
    CATEGORIES.map(c => `<option ${c === current ? "selected" : ""}>${esc(c)}</option>`));
  return `<select class="${cls}">${opts.join("")}</select>`;
}
function bindAssign() {
  $$("#review-list .rev-card").forEach(card => {
    const aid = card.dataset.aid;
    card.querySelector('[data-act="save"]').onclick = async () => {
      const cat = card.querySelector("select.assign").value;
      await api("/api/label", {aid, category: cat});
      toast(aid + " → " + (cat || "未分类")); card.remove();
    };
    card.querySelector('[data-act="none"]').onclick = async () => {
      await api("/api/label", {aid, category: "未分类"}); card.remove();
    };
  });
}

/* ---------- 全部条目 ---------- */
async function loadItems(page) {
  itemsPage = page || 1;
  const st = $("#f-status").value, cat = $("#f-cat").value, q = encodeURIComponent($("#f-q").value);
  const j = await api(`/api/items?status=${st}&category=${encodeURIComponent(cat)}&q=${q}&page=${itemsPage}&page_size=50&sort=fav_time`);
  $("#items-total").textContent = "共 " + j.total + " 条";
  $("#items-table tbody").innerHTML = j.items.map(it => `
    <tr>
      <td><input type="checkbox" class="row-sel" data-aid="${it.aid}"></td>
      <td class="muted">${esc(it.fav_time)}</td>
      <td>${esc(it.title)}${it.dead ? " <b class='st-review'>失效</b>" : ""}</td>
      <td class="muted">${esc(it.up_name)}</td>
      <td class="muted">${(it.signals || []).join("/")}</td>
      <td class="st-${it.status}">${STATUS_CN[it.status] || it.status}</td>
      <td>${catSelect(it.category, "row-cat")} <button data-aid="${it.aid}" data-act="save1">存</button></td>
    </tr>`).join("");
  $$("#items-table [data-act='save1']").forEach(b => b.onclick = async () => {
    const tr = b.closest("tr");
    await api("/api/label", {aid: b.dataset.aid, category: tr.querySelector(".row-cat").value});
    toast("已保存");
  });
}
$("#items-more").onclick = () => loadItems(itemsPage + 1);
$("#sel-all").onchange = () => {
  const on = $("#sel-all").checked;
  $$(".row-sel").forEach(c => c.checked = on);
};
async function bulkLabel() {
  const cat = $("#bulk-cat").value;
  const aids = $$(".row-sel").filter(c => c.checked).map(c => c.dataset.aid);
  if (!aids.length) { toast("先勾选条目"); return; }
  const j = await api("/api/bulk_label", {aids, category: cat});
  toast("已批量设置 " + j.count + " 条 → " + (cat || "未分类"));
  loadItems(1);
}

/* ---------- 分类体系 ---------- */
async function loadTax() {
  await refreshCategories();
  const t = await api("/api/taxonomy");
  $("#tax-tree").innerHTML = t.groups.map(g => `
    <div class="group-block">
      <b>📁 ${esc(g.name)}</b>
      <span class="muted">B站夹 media_id：</span>
      <input value="${esc(g.folder)}" data-group="${esc(g.name)}" class="g-folder" size="12">
      <button data-group="${esc(g.name)}" data-act="gsave">存夹id</button>
      <button data-group="${esc(g.name)}" data-act="gdel">删除组（不删分类）</button>
      ${g.leaves.map(leafBlock).join("")}
    </div>`).join("");
  $("#tax-loose").innerHTML = t.loose.map(leafBlock).join("") || "<em>无</em>";
  bindTax();
}
function leafBlock(l) {
  return `<div class="rule-row" data-leaf="${esc(l.name)}">
    🏷 <b>${esc(l.name)}</b> <span class="muted">(${l.count}条)</span>
    → B站夹 <input value="${esc(l.effective_folder)}" class="leaf-folder" size="12" placeholder="留空=用大分类夹的">
    <button data-act="lsave">存</button>
    <span class="muted">合并到</span>
    <select class="leaf-parent"><option value="">（不合并）</option>${
      (window._groups || []).map(g => `<option ${g === l.name ? "disabled" : ""} ${isParent(l, g) ? "selected" : ""}>${esc(g)}</option>`).join("")
    }</select>
    <button data-act="lparent">确定</button>
  </div>`;
}
function isParent(leaf, g) { return leaf._parent === g; }
function bindTax() {
  $$("[data-act='gsave']").forEach(b => b.onclick = async () => {
    const name = b.dataset.group;
    const v = document.querySelector(`.g-folder[data-group='${CSS.escape(name)}']`) ||
              $$(".g-folder").find(i => i.dataset.group === name);
    await api("/api/taxonomy/folder", {kind: "group", name, folder: v ? v.value : ""});
    toast("已保存大分类夹 " + name); loadTax();
  });
  $$("[data-act='gdel']").forEach(b => b.onclick = async () => {
    await api("/api/taxonomy/group_delete", {name: b.dataset.group}); loadTax();
  });
  $$("[data-leaf]").forEach(row => {
    const leaf = row.dataset.leaf;
    row.querySelector("[data-act='lsave']").onclick = async () => {
      await api("/api/taxonomy/folder", {kind: "leaf", name: leaf, folder: row.querySelector(".leaf-folder").value});
      toast("已保存 " + leaf);
    };
    row.querySelector("[data-act='lparent']").onclick = async () => {
      await api("/api/taxonomy/leaf_parent", {leaf, parent: row.querySelector(".leaf-parent").value});
      toast(leaf + " 分组已更新"); loadTax();
    };
  });
}
async function addGroup() {
  const name = $("#new-group").value.trim();
  if (!name) { toast("填个大分类夹名"); return; }
  await api("/api/taxonomy/group", {name});
  $("#new-group").value = ""; toast("已创建 " + name); loadTax();
}

/* ---------- 规则 ---------- */
async function loadRules() {
  await refreshCategories();
  const rules = await api("/api/rules");
  const titles = {manual: "手写规则（如 UP mid 精确）", initial: "初筛规则（关键词死规则块）",
                  ai: "AI细化规则块", reinforced: "强化规则（共现概率自动升级）"};
  $("#rules-blocks").innerHTML = Object.entries(rules).map(([block, list]) => `
    <div class="panel"><h3>${titles[block] || block}（${list.length}）</h3>
      ${list.map(r => `
        <div class="rule-row ${r.enabled ? "" : "off"}">
          <code>${esc(r.id)}</code>
          <span class="tag">${esc(r.field)}${r.mid !== undefined && r.mid !== null ? "(mid=" + esc(r.mid) + ")" : ""}</span>
          ${esc((r.keywords || []).join("，"))}${r.regex ? "<code> /" + esc(r.regex) + "/</code>" : ""}
          → <b>${esc(r.category)}</b> 权重${r.weight}
          ${r.p !== undefined ? `<span class="muted">P=${Math.round((r.p || 0) * 100)}% n=${r.n}</span>` : ""}
          ${r.strong ? "<span class='tag'>强规则</span>" : ""}
          <button data-id="${esc(r.id)}" data-en="${r.enabled ? 0 : 1}" data-act="toggle">${r.enabled ? "停用" : "启用"}</button>
          <button data-id="${esc(r.id)}" data-act="del">删除</button>
        </div>`).join("") || "<em class='muted'>空</em>"}
    </div>`).join("");
  $$("#rules-blocks [data-act='toggle']").forEach(b => b.onclick = async () => {
    await api("/api/rules/toggle", {id: b.dataset.id, enabled: b.dataset.en === "1"});
    loadRules();
  });
  $$("#rules-blocks [data-act='del']").forEach(b => b.onclick = async () => {
    await api("/api/rules/delete", {id: b.dataset.id}); loadRules();
  });
}
async function addRule() {
  const kws = $("#r-kw").value.split(/[,，]/).map(s => s.trim()).filter(Boolean);
  const j = await api("/api/rules/add", {
    block: $("#r-block").value, field: $("#r-field").value, keywords: kws,
    regex: $("#r-regex").value.trim(), category: $("#r-cat").value,
    weight: parseFloat($("#r-weight").value) || 1.0, strong: $("#r-strong").checked,
  });
  toast("规则已添加 " + j.rule.id); $("#r-kw").value = ""; $("#r-regex").value = "";
  loadRules();
}

/* ---------- 保护名单 / 移动范围 / 限额 ---------- */
let GUARD_DATA = null;

async function loadGuard() {
  const j = await api("/api/guard");
  GUARD_DATA = j;
  const list = j.folders || [];
  const cnt = { locked: 0, soft: 0, free: 0 };
  list.forEach(x => { cnt[x.guard] = (cnt[x.guard] || 0) + 1; });
  $("#guard-counts").textContent =
    `共 ${list.length} 个夹 ｜ 🛡锁定 ${cnt.locked} ｜ ⚠️软保护 ${cnt.soft} ｜ ○自由 ${cnt.free}`;
  $("#scope-mode").value = (j.move_scope || {}).mode || "minimal";
  $("#lim-run").value = (j.write_limits || {}).per_run ?? 200;
  $("#lim-day").value = (j.write_limits || {}).per_day ?? 1000;
  const h = j.headroom || {};
  $("#lim-headroom").textContent =
    `今日（${h.today || "-"}）已移动 ${h.moved_today || 0} 条，当日还剩 ${h.day_remaining || 0} 条；` +
    `本次最多可动 ${Math.min(h.run_remaining || 0, h.day_remaining || 0)} 条。`;
  renderGuard();
  renderScopeAllow();
}

function renderGuard() {
  if (!GUARD_DATA) return;
  const f = $("#guard-filter").value;
  const q = ($("#guard-q").value || "").trim().toLowerCase();
  let list = GUARD_DATA.folders || [];
  if (f) list = list.filter(x => x.guard === f);
  if (q) list = list.filter(x => String(x.title || "").toLowerCase().includes(q));
  if (!list.length) { $("#guard-list").innerHTML = "<p class='hint'>没有匹配的收藏夹。</p>"; return; }
  const poolTag = p => p === 2 ? " <span class='hint'>[池2]</span>" : p === 1 ? " <span class='hint'>[池1]</span>" : "";
  $("#guard-list").innerHTML = list.slice(0, 300).map(x => `
    <div class="row">
      <span style="min-width:220px">${esc(x.title)}${poolTag(x.pool)}</span>
      <span class="hint" style="min-width:70px">${x.items} 条</span>
      <select onchange="setGuard('${x.folder_id}', this.value)">
        <option value="locked" ${x.guard === "locked" ? "selected" : ""}>🛡 锁定</option>
        <option value="soft" ${x.guard === "soft" ? "selected" : ""}>⚠️ 软保护</option>
        <option value="free" ${x.guard === "free" ? "selected" : ""}>○ 自由</option>
      </select>
    </div>`).join("") +
    (list.length > 300 ? "<p class='hint'>仅显示前 300 个，请用搜索缩小范围。</p>" : "");
}

async function setGuard(fid, level) {
  await api("/api/guard/set", {folder_id: fid, level: level});
  toast("已设为：" + (level === "locked" ? "锁定" : level === "soft" ? "软保护" : "自由"));
  await loadGuard();
}

function renderScopeAllow() {
  if (!GUARD_DATA) return;
  const mode = $("#scope-mode").value;
  const box = $("#scope-allow-box");
  if (mode !== "minimal") {
    box.innerHTML = "<p class='hint'>当前模式：除锁定夹外，任何夹都可以作为移动源，无需白名单。</p>";
    return;
  }
  const allow = new Set((GUARD_DATA.move_scope || {}).allow_sources || []);
  const list = (GUARD_DATA.folders || []).filter(x => x.items > 0 && x.guard !== "locked");
  box.innerHTML = "<p class='hint'>勾选允许作为「移动源」的收藏夹（视频会从这些夹被搬出去）：</p>" +
    (list.length ? list.slice(0, 120).map(x => `
      <label class="row" style="display:inline-flex;margin-right:14px">
        <input type="checkbox" value="${x.folder_id}" ${allow.has(x.folder_id) ? "checked" : ""}>
        ${esc(x.title)} <span class="hint">(${x.items})</span>
      </label>`).join("") : "<p class='hint'>没有可选的夹。</p>");
}

function onScopeModeChange() { renderScopeAllow(); }

async function saveScope() {
  const allow = $$("#scope-allow-box input[type=checkbox]").filter(c => c.checked).map(c => c.value);
  await api("/api/scope/set", {mode: $("#scope-mode").value, allow_sources: allow});
  toast("移动范围已保存");
  await loadGuard();
}

async function saveLimits() {
  await api("/api/limits/set", {
    per_run: parseInt($("#lim-run").value) || 200,
    per_day: parseInt($("#lim-day").value) || 1000,
  });
  toast("限额已保存");
  await loadGuard();
}

/* ---------- 写回 & 设置 ---------- */
async function wbPlan() {
  const sel = $$("#wb-status option").filter(o => o.selected).map(o => o.value);
  const j = await api("/api/writeback/plan", {statuses: sel});
  const lim = j.limits || {};
  let html = `<p>计划移动 <b>${j.total}</b> 条，${j.groups.length} 组，跳过 ${j.skipped} 条。</p>`;
  html += `<p class="hint">限额：单次 ${lim.per_run ?? "-"} 条，当日 ${lim.per_day ?? "-"} 条，`
        + `今日已用 ${lim.moved_today ?? 0} 条 → 本次上限 ${lim.cap_used ?? "-"} 条。</p>`;
  if ((j.soft_needs_confirm || []).length) {
    html += `<p style="color:#b8860b"><b>⚠️ 本次计划涉及软保护收藏夹：`
          + `${j.soft_needs_confirm.map(esc).join("、")}</b>，执行时需额外输入 CONFIRM-SOFT。</p>`;
  }
  html += j.groups.map(g => `<div class="row">→ <b>${esc(g.category)}</b>：${esc(g.src)} ⇒ ${esc(g.tar)}，${g.count} 条`
        + (g.soft ? " <span class='hint'>[软保护]</span>" : "") + "</div>").join("");
  html += "<p class='hint'>计划已存 data/app_plan.json，去B站核对后再执行。</p>";
  $("#wb-summary").innerHTML = html;
}

async function wbApply() {
  if ($("#wb-confirm").value !== "APPLY") { toast("请输入 APPLY"); return; }
  const body = {confirm: "APPLY"};
  const cs = $("#wb-confirm-soft").value.trim();
  if (cs) body.confirm_soft = cs;
  const j = await api("/api/writeback/apply", body);
  $("#wb-result").innerHTML = `<p>✅ 已移动 <b>${j.moved}</b> 条，报告：${esc(j.report)}</p>`;
  $("#wb-confirm").value = ""; $("#wb-confirm-soft").value = "";
  loadGuard();
}
async function loadSettings() {
  const s = await api("/api/settings");
  $("#s-min-score").value = s.min_score; $("#s-min-margin").value = s.min_margin;
  $("#s-min-fields").value = s.min_fields; $("#s-reinforce-p").value = s.reinforce_p;
  $("#s-reinforce-min-n").value = s.reinforce_min_n; $("#s-promote-cap").value = s.promote_cap;
  $("#llm-url").value = (s.llm || {}).base_url || ""; $("#llm-model").value = (s.llm || {}).model || "";
}
async function saveSettings() {
  await api("/api/settings", {
    min_score: parseFloat($("#s-min-score").value) || 1.0,
    min_margin: parseFloat($("#s-min-margin").value) || 0.3,
    min_fields: parseInt($("#s-min-fields").value) || 2,
    reinforce_p: parseFloat($("#s-reinforce-p").value) || 0.6,
    reinforce_min_n: parseInt($("#s-reinforce-min-n").value) || 5,
    promote_cap: parseInt($("#s-promote-cap").value) || 50,
  });
  toast("设置已保存");
}
async function saveLLM() {
  await api("/api/settings", {llm: {
    base_url: $("#llm-url").value.trim(), model: $("#llm-model").value.trim(),
    api_key: $("#llm-key").value.trim(),
  }});
  toast("LLM 配置已保存（仅存本机 data/app_state.json）");
}
async function runLLM() {
  toast("AI 分类中，请稍候…");
  const j = await api("/api/ai/run_llm", {max_items: 300});
  toast("AI 已分类 " + j.labeled + " 条");
  loadOverview();
}

/* ---------- 公共 ---------- */
async function refreshCategories() {
  const t = await api("/api/taxonomy");
  CATEGORIES = t.loose.concat(...t.groups.map(g => g.leaves)).map(x => x.name);
  window._groups = t.groups.map(g => g.name);
  const opts = CATEGORIES.map(c => `<option>${esc(c)}</option>`).join("");
  const groupOpts = t.groups.map(g =>
    `<option value="group:${esc(g.name)}">📁 ${esc(g.name)}（组视图）</option>`).join("");
  $("#f-cat").innerHTML = '<option value="">全部分类</option>'
    + groupOpts + '<optgroup label="初始分类">' + opts + "</optgroup>";
  $("#bulk-cat").innerHTML = '<option value="">未分类</option>' + opts;
  $("#r-cat").innerHTML = opts;
}
loadOverview().then(loadSettings);
