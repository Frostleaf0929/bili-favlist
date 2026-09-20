// ==UserScript==
// @name         B站收藏夹写回辅助（按 plan.json 批量移动）
// @namespace    local.bili.writeback
// @version      0.1.0
// @description  备用方案：在已登录的B站页面里粘贴 writeback.py 生成的 plan.json，按分类批量移动收藏。每批 10 条、随机 1-2 秒间隔，可中途停止；目标夹不存在时自动创建（私密）。
// @match        https://space.bilibili.com/*
// @match        https://www.bilibili.com/*
// @grant        none
// @run-at       document-idle
// ==/UserScript==

(function () {
  "use strict";

  const API_BASE = "https://api.bilibili.com";
  const BATCH_SIZE = 10;
  const DELAY_MIN = 1000;
  const DELAY_MAX = 2000;

  const getCookie = (name) => {
    const m = document.cookie.match(new RegExp("(?:^|;\\s*)" + name + "=([^;]+)"));
    return m ? m[1] : "";
  };

  let running = false;

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const randDelay = () => sleep(DELAY_MIN + Math.random() * (DELAY_MAX - DELAY_MIN));

  async function postForm(path, params) {
    const body = new URLSearchParams(params);
    const resp = await fetch(API_BASE + path, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: body.toString(),
    });
    const j = await resp.json();
    if (j.code !== 0) {
      const err = new Error("[" + j.code + "] " + (j.message || ""));
      err.code = j.code;
      throw err;
    }
    return j.data || {};
  }

  async function createFolder(title, csrf) {
    return postForm("/x/v3/fav/folder/add", {
      title: title,
      intro: "由收藏夹分类工具自动创建",
      privacy: 1,
      csrf: csrf,
    });
  }

  async function moveBatch(srcId, tarId, aids, mid, csrf) {
    const resources = aids.map((a) => a + ":2").join(",");
    return postForm("/x/v3/fav/resource/move", {
      src_media_id: srcId,
      tar_media_id: tarId,
      mid: mid,
      resources: resources,
      platform: "web",
      csrf: csrf,
    });
  }

  async function runPlan(plan, log) {
    const csrf = getCookie("bili_jct");
    const mid = getCookie("DedeUserID");
    if (!csrf || !mid) {
      log("未检测到登录 Cookie（bili_jct/DedeUserID），请先登录B站。");
      return;
    }

    // 目标夹不存在（dry-run 计划）则先创建
    const folderIdByCategory = {};
    const newFolders = plan.new_folders || {};
    for (const cat of Object.keys(newFolders)) {
      const info = newFolders[cat];
      if (info.media_id) {
        folderIdByCategory[cat] = String(info.media_id);
      } else if (running) {
        try {
          const created = await createFolder(info.title || cat, csrf);
          folderIdByCategory[cat] = String(created.id);
          log("已创建收藏夹「" + cat + "」 => " + created.id);
          await randDelay();
        } catch (e) {
          log("创建收藏夹「" + cat + "」失败：" + e.message);
        }
      }
    }

    const groups = plan.groups || [];
    let fails = 0;
    for (let gi = 0; gi < groups.length; gi++) {
      if (!running) { log("已停止。"); return; }
      const g = groups[gi];
      const tarId = g.tar_media_id ? String(g.tar_media_id) : folderIdByCategory[g.category];
      if (!tarId) { log("跳过：「" + g.category + "」无目标收藏夹"); continue; }
      const items = g.items || [];
      let moved = 0;
      for (let i = 0; i < items.length; i += BATCH_SIZE) {
        if (!running) { log("已停止。"); return; }
        const batch = items.slice(i, i + BATCH_SIZE);
        const aids = batch.map((it) => it.aid);
        try {
          await moveBatch(g.src_media_id, tarId, aids, mid, csrf);
          moved += batch.length;
          fails = 0;
          log("[" + (gi + 1) + "/" + groups.length + "] 「" + g.category + "」" + moved + "/" + items.length);
        } catch (e) {
          if (e.code === 11010 || e.code === 11011) {
            moved += batch.length;
            log("[" + (gi + 1) + "/" + groups.length + "] 整批跳过（内容不存在/失效）");
          } else {
            fails++;
            log("失败 [" + e.code + "] " + e.message + "（连续第 " + fails + " 次）");
            if (fails >= 3) { log("连续失败 3 次，疑似风控，已停止。"); return; }
            await sleep(5000);
          }
        }
        await randDelay();
      }
    }
    log("全部完成。");
  }

  function buildPanel() {
    if (document.getElementById("bili-wb-panel")) return;
    const panel = document.createElement("div");
    panel.id = "bili-wb-panel";
    panel.style.cssText = [
      "position:fixed", "right:20px", "bottom:20px", "width:460px",
      "background:#fff", "border:1px solid #ccc", "border-radius:8px",
      "box-shadow:0 4px 16px rgba(0,0,0,.2)", "z-index:999999",
      "font:12px/1.6 system-ui,sans-serif", "padding:10px", "color:#333",
    ].join(";");
    panel.innerHTML =
      '<div style="font-weight:700;margin-bottom:6px">B站收藏夹写回辅助' +
      ' <span style="font-weight:400;color:#888">（粘贴 plan.json）</span></div>' +
      '<textarea id="bili-wb-input" style="width:100%;height:140px;box-sizing:border-box;' +
      'font:11px monospace" placeholder="粘贴 writeback.py 生成的 data/plan.json 内容"></textarea>' +
      '<div style="margin:6px 0">' +
      '<button id="bili-wb-start" style="margin-right:8px">开始移动</button>' +
      '<button id="bili-wb-stop">停止</button></div>' +
      '<div id="bili-wb-log" style="height:180px;overflow:auto;background:#f7f7f7;padding:6px;' +
      'white-space:pre-wrap;font:11px monospace"></div>';
    document.body.appendChild(panel);

    const logEl = panel.querySelector("#bili-wb-log");
    const log = (msg) => {
      const line = document.createElement("div");
      line.textContent = new Date().toTimeString().slice(0, 8) + " " + msg;
      logEl.appendChild(line);
      logEl.scrollTop = logEl.scrollHeight;
    };

    panel.querySelector("#bili-wb-start").addEventListener("click", () => {
      if (running) return;
      let plan;
      try {
        plan = JSON.parse(panel.querySelector("#bili-wb-input").value);
      } catch (e) {
        log("plan.json 解析失败：" + e.message);
        return;
      }
      if (!plan.groups || !plan.groups.length) {
        log("plan.json 里没有 groups，请先运行 writeback.py 生成计划。");
        return;
      }
      running = true;
      log("开始：共 " + plan.groups.length + " 组。");
      runPlan(plan, log).finally(() => { running = false; });
    });
    panel.querySelector("#bili-wb-stop").addEventListener("click", () => {
      running = false;
      log("已请求停止（当前批次完成后退出）。");
    });
  }

  buildPanel();
})();
