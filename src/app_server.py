# -*- coding: utf-8 -*-
"""本地交互式分类软件 · Web 服务（仅绑定 127.0.0.1，零额外依赖）。

启动：python src/main.py app   （浏览器打开 http://127.0.0.1:8787）
"""
from __future__ import annotations

import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from bili_api import BiliApiError
from wb_exec import apply_plan, verify_and_report

PKG_DIR = Path(__file__).resolve().parent          # src/ 目录（仓库或安装包内均成立）
WEBUI = PKG_DIR / "webui"
DATA_DIR = Path.cwd() / "data"                     # 运行目录下的工作数据
CONFIG_PATH = Path.cwd() / "config.yaml"
RULES_PATH = Path.cwd() / "rules.yaml"
HOST, PORT = "127.0.0.1", 8787
DEMO = False

_lock = threading.RLock()
BG_PROGRESS = {"task": "", "running": False, "done": 0, "total": 0, "current": "", "error": "", "result": ""}


def _run_bg(task: str, fn):
    """后台线程执行长任务，进度写入 BG_PROGRESS。"""
    def runner():
        BG_PROGRESS.update({"task": task, "running": True, "done": 0, "total": 0,
                            "current": "", "error": "", "result": ""})
        try:
            result = fn()
            BG_PROGRESS["result"] = str(result)
            BG_PROGRESS["running"] = False
        except Exception as exc:  # noqa: BLE001
            BG_PROGRESS["error"] = str(exc)
            BG_PROGRESS["running"] = False
    t = threading.Thread(target=runner, daemon=True)
    t.start()


def get_engine():
    global _engine
    try:
        return _engine
    except NameError:
        from app_engine import Engine
        _engine = Engine(DATA_DIR)
        return _engine


def get_api():
    global _api
    try:
        return _api
    except NameError:
        if not CONFIG_PATH.exists():
            raise ValueError(
                "未找到 config.yaml：请复制 config.example.yaml 为 config.yaml 并填写 Cookie；"
                "或用 --demo 体验示例数据"
            )
        from export_fav import build_api, load_config
        cfg = load_config(CONFIG_PATH)
        _api = build_api(cfg)
        return _api


# ---------- 演示模式（无 Cookie 可体验） ----------

DEMO_RULES = {
    "weights": {"up": 2.0, "title": 1.0, "tag": 0.6},
    "up_rules": [
        {"match": "示例UP-切片君", "category": "vtb切片"},
        {"match": "示例UP-教画画的鸭", "category": "绘画"},
    ],
    "title_rules": [
        {"keywords": ["切片", "熟肉", "【熟】", "搬运"], "category": "vtb切片"},
        {"keywords": ["翻唱", "MV", "cover", "原创曲"], "category": "歌曲MV"},
        {"keywords": ["教程", "入门", "干货", "指南"], "category": "学习教程"},
        {"keywords": ["绘画", "作画", "速写", "上色"], "category": "绘画"},
        {"keywords": ["MMD", "舞蹈"], "category": "MMD舞蹈"},
        {"keywords": ["手书"], "category": "手书动画"},
        {"keywords": ["明日方舟", "泰拉"], "category": "游戏明日方舟"},
        {"keywords": ["原神"], "category": "游戏原神"},
        {"keywords": ["崩坏"], "category": "游戏崩坏"},
        {"keywords": ["蔚蓝档案", "阿罗娜"], "category": "游戏蔚蓝档案"},
        {"keywords": ["asmr", "音声"], "category": "asmr音声"},
        {"keywords": ["cos"], "category": "cos"},
    ],
    "tag_rules": [],
}
DEMO_CATEGORIES = [
    "vtb切片", "歌曲MV", "学习教程", "绘画", "MMD舞蹈", "手书动画",
    "游戏明日方舟", "游戏原神", "游戏崩坏", "游戏蔚蓝档案", "asmr音声", "cos",
]


def bootstrap_if_empty(eng) -> None:
    """首次启动：从现有导出数据/规则/配置/AI结果播种状态。"""
    if eng.state["items"]:
        return
    export_path = DATA_DIR / "export.json"
    if not export_path.exists():
        print("提示：data/export.json 不存在，先跑 export 命令导出收藏夹。")
        return
    n = eng.import_export(export_path)
    print(f"已导入 {n} 条导出记录")
    import yaml
    if RULES_PATH.exists():
        eng.seed_rules_from_yaml(yaml.safe_load(RULES_PATH.read_text(encoding="utf-8")) or {})
    if CONFIG_PATH.exists():
        import yaml as _y
        cfg = _y.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        eng.seed_taxonomy_from_config(
            (cfg.get("writeback") or {}).get("category_to_folder") or {}
        )
    ai_path = DATA_DIR / "ai_result.csv"
    if ai_path.exists():
        n2 = eng.import_ai_csv(ai_path)
        print(f"已导入 {n2} 条AI标注")
    eng.save()


def bootstrap_demo(eng) -> None:
    """演示模式：无 Cookie、无配置，用内置虚构示例数据体验完整流程。"""
    if eng.state["items"]:
        return
    sample = PKG_DIR / "sample_data" / "sample_export.json"
    n = eng.import_export(sample)
    eng.seed_rules_from_yaml(DEMO_RULES)
    for cat in DEMO_CATEGORIES:
        eng.ensure_leaf(cat)
    eng.save()
    print(f"DEMO：已载入 {n} 条虚构示例数据与演示规则（写回功能不可用）")


# ---------- 工具 ----------

def _validate_external_url(url: str) -> str:
    """LLM 接口地址校验：仅 https 且不得指向内网/本机。"""
    parsed = urllib.parse.urlparse(url or "")
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https":
        raise ValueError("LLM 接口必须是 https://")
    bad = (
        not host or host in ("localhost",) or host.endswith(".local")
        or host.startswith("127.") or host.startswith("10.")
        or host.startswith("192.168.") or host == "::1"
        or host.startswith("169.254.")
        or (host.startswith("172.") and 16 <= int(host.split(".")[1] or 0) <= 31)
    )
    if bad:
        raise ValueError("LLM 接口不允许指向本机/内网地址（如需本地模型请用 CSV 导入导出）")
    return url.rstrip("/")


def call_llm(base_url: str, api_key: str, model: str, batch_items: list, categories: list) -> dict:
    """调用 OpenAI 兼容接口做批量分类，返回 {aid: category}。"""
    import requests

    url = _validate_external_url(base_url) + "/chat/completions"
    payload_items = [
        {
            "aid": it["aid"],
            "title": it["title"],
            "up": it["up_name"],
            "tags": it["tags"],
            "desc": (it["desc"] or "")[:120],
        }
        for it in batch_items
    ]
    prompt = (
        "你是视频收藏分类助手。把每个视频分到给定分类之一，无法判断填 未分类。\n"
        "参考信号优先级：标题 > UP主 ≈ 标签 > 简介。\n"
        "分类列表：" + "、".join(categories) + "\n"
        "只输出 JSON：{\"<aid>\": \"<分类>\", ...}，不要解释。\n"
        "数据：" + json.dumps(payload_items, ensure_ascii=False)
    )
    resp = requests.post(
        url,
        headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        },
        timeout=120,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"].strip()
    if content.startswith("```"):
        content = content.strip("`").lstrip("json").strip()
    data = json.loads(content)
    return {str(k): str(v) for k, v in data.items()}


# ---------- 业务逻辑 ----------

def build_writeback_plan(statuses=("auto", "ai", "human", "hot", "hot2", "review")):
    eng = get_engine()
    api = get_api()
    from app_engine import GUARD_LOCKED, GUARD_SOFT
    folders = {str(f["id"]): f for f in api.list_created_folders()}

    # 目标夹：叶子分类优先，其次所属大分类夹；锁定夹绝不作为目标
    targets = {}
    for leaf_name, leaf in eng.state["taxonomy"]["leaves"].items():
        fid = eng.effective_folder(leaf_name)
        if not fid:
            continue
        if eng.guard_level(fid) == GUARD_LOCKED:
            print(f"[锁定] 分类「{leaf_name}」绑定的收藏夹处于锁定保护，跳过该目标")
            continue
        targets[leaf_name] = fid

    head = eng.write_headroom()
    cap = min(head["run_remaining"], head["day_remaining"])

    rows, skipped = [], []
    for it in eng.state["items"]:
        if it.get("dead"):
            continue
        if it.get("status") not in statuses:
            continue
        sid = str(it.get("src_media_id") or "")
        if eng.guard_level(sid) == GUARD_LOCKED:
            skipped.append({"aid": it["aid"], "bvid": it["bvid"], "title": it["title"][:40],
                            "reason": "源夹已锁定，绝不从该夹移出"})
            continue
        if not eng.source_allowed(sid):
            skipped.append({"aid": it["aid"], "bvid": it["bvid"], "title": it["title"][:40],
                            "reason": "源夹不在当前移动范围内"})
            continue
        cat = it.get("category") or ""
        tar = targets.get(cat)
        if not tar:
            continue
        soft = (eng.guard_level(sid) == GUARD_SOFT or eng.guard_level(tar) == GUARD_SOFT)
        rows.append((it, cat, tar, soft))

    # 限额：按条目自然顺序截断，总数不超过 cap
    # （不把软保护条目排到最后——它们本就需要二次确认，排序只会让它们永远够不到）
    kept, capped_off = [], []
    for it, cat, tar, soft in rows:
        if len(kept) < cap:
            kept.append((it, cat, tar, soft))
        else:
            capped_off.append({"aid": it["aid"], "bvid": it["bvid"], "title": it["title"][:40],
                               "reason": f"超出本次限额（本次上限 {cap} 条），下次再来"})

    tar_ids = sorted({tar for _, _, tar, _ in kept})
    tar_aids = {}
    for tid in tar_ids:
        tar_aids[tid] = api.list_folder_aids(tid)

    groups = {}
    for it, cat, tar, soft in kept:
        aid = int(it["aid"])
        src = str(it.get("src_media_id") or "")
        if aid in tar_aids.get(tar, set()):
            skipped.append({"aid": it["aid"], "bvid": it["bvid"], "title": it["title"][:40],
                            "reason": "已在目标收藏夹"})
            continue
        if src == tar:
            skipped.append({"aid": it["aid"], "bvid": it["bvid"], "title": it["title"][:40],
                            "reason": "源收藏夹与目标相同"})
            continue
        key = (src, tar)
        groups.setdefault(key, {"category": cat, "items": [], "soft": False})
        groups[key]["items"].append({"aid": aid, "bvid": it["bvid"], "title": it["title"]})
        groups[key]["soft"] = groups[key]["soft"] or soft

    plan_groups = []
    for (src, tar), g in sorted(groups.items()):
        plan_groups.append({
            "src_media_id": src,
            "src_title": folders.get(src, {}).get("title", src),
            "tar_media_id": tar,
            "tar_title": folders.get(tar, {}).get("title", tar),
            "src_guard": eng.guard_level(src),
            "tar_guard": eng.guard_level(tar),
            "soft": g["soft"],
            "category": g["category"],
            "tar_count_before": len(tar_aids.get(tar, set())),
            "items": g["items"],
        })
    planned = sum(len(g["items"]) for g in plan_groups)
    return {
        "generated_at": now_str(),
        "apply": False,
        "new_folders": {},
        "groups": plan_groups,
        "skipped": skipped + capped_off,
        "limits": {
            "per_run": head["per_run"], "per_day": head["per_day"],
            "moved_today": head["moved_today"], "cap_used": cap, "planned": planned,
        },
        "scope": dict(eng.state.get("move_scope") or {}),
        "soft_needs_confirm": sorted({
            t for t in (
                [g["src_title"] if g["src_guard"] == GUARD_SOFT else None for g in plan_groups]
                + [g["tar_title"] if g["tar_guard"] == GUARD_SOFT else None for g in plan_groups]
            ) if t
        }),
    }


def now_str() -> str:
    import datetime as dt
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------- HTTP ----------

class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):  # 精简日志
        pass

    def _send(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    # --- GET ---

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path.startswith("/api/"):
            self._api_get(path, dict(urllib.parse.parse_qsl(parsed.query)))
            return
        self._static(path)

    def _api_get(self, path: str, qs: dict):
        eng = get_engine()
        if path == "/api/eval/progress":
            self._json(dict(BG_PROGRESS))  # 免锁直读，供长任务期间轮询
            return
        with _lock:
            try:
                if path == "/api/overview":
                    payload = eng.overview()
                    payload["demo"] = DEMO
                    self._json(payload)
                elif path == "/api/items":
                    self._json(self._list_items(eng, qs))
                elif path == "/api/rules":
                    self._json(eng.state["rules"])
                elif path == "/api/taxonomy":
                    self._json(self._taxonomy_view(eng))
                elif path == "/api/settings":
                    self._json(eng.state["settings"])
                elif path == "/api/passes":
                    self._json(eng.state["passes"])
                elif path == "/api/eval/report":
                    self._json(eng.state.get("eval_report") or {})
                elif path == "/api/corpus":
                    counts: dict = {}
                    id_by_title: dict = {}
                    for it in eng.state.get("eval_items") or []:
                        t = it.get("truth") or ""
                        if t:
                            counts[t] = counts.get(t, 0) + 1
                            id_by_title.setdefault(t, str(it.get("src_media_id") or ""))
                    p1 = set(eng.state.get("corpus_folders") or [])
                    p2 = set(eng.state.get("corpus2_folders") or [])
                    protected = set(eng.state.get("protected_folders") or [])
                    self._json({
                        "folders": [
                            {"title": t, "media_id": id_by_title.get(t, ""),
                             "count": counts[t],
                             "pool": 2 if t in p2 else (1 if t in p1 else 0),
                             "hint": eng.subjective_hint(t, counts[t]),
                             "protected": id_by_title.get(t, "") in protected}
                            for t in sorted(counts, key=lambda x: -counts[x])
                        ],
                        "pool1": sorted(p1), "pool2": sorted(p2),
                        "protected": sorted(protected),
                    })
                elif path == "/api/guard":
                    snap = eng.guard_snapshot()
                    titles = eng.state.get("folder_titles") or {}
                    by_id: dict = {}
                    for it in (eng.state.get("items") or []) + (eng.state.get("eval_items") or []):
                        sid = str(it.get("src_media_id") or "")
                        if not sid:
                            continue
                        rec = by_id.setdefault(
                            sid, {"folder_id": sid, "title": "", "items": 0}
                        )
                        rec["items"] += 1
                        if not rec["title"]:
                            rec["title"] = (
                                it.get("truth") or it.get("src_folder_title")
                                or titles.get(sid, "")
                            )
                    for fid, title in titles.items():
                        rec = by_id.setdefault(
                            str(fid), {"folder_id": str(fid), "title": title, "items": 0}
                        )
                        if not rec["title"]:
                            rec["title"] = title
                    for g in snap["guards"]:
                        by_id.setdefault(
                            g["folder_id"],
                            {"folder_id": g["folder_id"], "title": g["title"], "items": 0},
                        )
                    p1 = set(eng.state.get("corpus_folders") or [])
                    p2 = set(eng.state.get("corpus2_folders") or [])
                    folder_list = []
                    for rec in by_id.values():
                        rec["guard"] = eng.guard_level(rec["folder_id"])
                        t = rec["title"]
                        rec["pool"] = 2 if t in p2 else (1 if t in p1 else 0)
                        folder_list.append(rec)
                    folder_list.sort(key=lambda x: -x["items"])
                    self._json({
                        "guards": snap["guards"],
                        "level_counts": snap["level_counts"],
                        "folders": folder_list,
                        "move_scope": dict(eng.state.get("move_scope") or {}),
                        "write_limits": dict(eng.state.get("write_limits") or {}),
                        "headroom": eng.write_headroom(),
                        "write_log": (eng.state.get("write_log") or [])[-20:],
                    })
                elif path == "/api/insights":
                    self._json(eng.insights())
                elif path == "/api/learn/report":
                    self._json({
                        "hotwords": eng.state.get("hotwords") or {},
                        "hotword_keys": len(eng.state.get("hotwords") or {}),
                        "hotwords2": eng.state.get("hotwords2") or {},
                        "hotword2_keys": len(eng.state.get("hotwords2") or {}),
                        "learned_weights": eng.state.get("learned_weights"),
                        "weight_report": eng.state.get("weight_report"),
                        "corpus_folders": eng.state.get("corpus_folders") or [],
                        "corpus2_folders": eng.state.get("corpus2_folders") or [],
                        "protected_folders": eng.state.get("protected_folders") or [],
                    })
                elif path == "/api/rules/export.md":
                    md = eng.export_rules_md()
                    out = DATA_DIR / "rules_export.md"
                    out.write_text(md, encoding="utf-8")
                    body = md.encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/markdown; charset=utf-8")
                    self.send_header("Content-Disposition",
                                     "attachment; filename=rules_export.md")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                elif path == "/api/rules/export.yaml":
                    import yaml as _y
                    payload = _y.safe_dump(
                        eng.export_rules_yaml(), allow_unicode=True, sort_keys=False
                    )
                    out = DATA_DIR / "rules_export.yaml"
                    out.write_text(payload, encoding="utf-8")
                    body = payload.encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/x-yaml; charset=utf-8")
                    self.send_header("Content-Disposition",
                                     "attachment; filename=rules_export.yaml")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                else:
                    self._json({"error": "not found"}, 404)
            except Exception as exc:  # noqa: BLE001
                self._json({"error": str(exc)}, 500)

    def _list_items(self, eng, qs: dict):
        status = qs.get("status") or ""
        category = qs.get("category") or ""
        q = (qs.get("q") or "").lower()
        sort = qs.get("sort") or "fav_time"
        page = max(1, int(qs.get("page") or 1))
        page_size = min(200, max(10, int(qs.get("page_size") or 50)))

        items = list(eng.state["items"])
        if status:
            items = [it for it in items if it.get("status") == status]
        if category:
            if category.startswith("group:"):
                gname = category[len("group:"):]
                leaves = {
                    name for name, leaf in eng.state["taxonomy"]["leaves"].items()
                    if leaf.get("parent") == gname
                }
                items = [it for it in items if it.get("category") in leaves]
            elif category == "（未分类）":
                items = [it for it in items if not it.get("category")]
            else:
                items = [it for it in items if it.get("category") == category]
        if q:
            items = [
                it for it in items
                if q in (it.get("title") or "").lower()
                or q in (it.get("up_name") or "").lower()
                or q in (it.get("tags") or "").lower()
            ]
        if sort == "margin":   # 不确定度优先：分差最小 = 最拿不准
            items.sort(key=lambda it: (it.get("margin") if it.get("margin") is not None else 999))
        elif sort == "score":
            items.sort(key=lambda it: (it.get("score") or 0), reverse=True)
        else:
            items.sort(key=lambda it: (it.get("fav_time") or ""), reverse=True)
        total = len(items)
        start = (page - 1) * page_size
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": items[start:start + page_size],
        }

    def _taxonomy_view(self, eng):
        groups = []
        for gname, g in eng.state["taxonomy"]["groups"].items():
            leaves = [
                {"name": name, "folder": leaf.get("folder") or "",
                 "effective_folder": eng.effective_folder(name),
                 "count": eng.overview_category_count(name)}
                for name, leaf in eng.state["taxonomy"]["leaves"].items()
                if leaf.get("parent") == gname
            ]
            groups.append({"name": gname, "folder": g.get("folder") or "", "leaves": leaves})
        loose = [
            {"name": name, "folder": leaf.get("folder") or "",
             "effective_folder": eng.effective_folder(name),
             "count": eng.overview_category_count(name)}
            for name, leaf in eng.state["taxonomy"]["leaves"].items()
            if not leaf.get("parent")
        ]
        return {"groups": sorted(groups, key=lambda x: x["name"]),
                "loose": sorted(loose, key=lambda x: x["name"])}

    # --- 静态文件 ---

    def _static(self, path: str):
        if path in ("/", "/index.html"):
            fname = "index.html"
        else:
            fname = path.lstrip("/")
        fpath = (WEBUI / fname).resolve()
        try:
            fpath.relative_to(WEBUI.resolve())
        except ValueError:
            self._send(403, b"forbidden", "text/plain")
            return
        if not fpath.exists():
            self._send(404, b"not found", "text/plain")
            return
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
        }.get(fpath.suffix, "application/octet-stream")
        self._send(200, fpath.read_bytes(), ctype)

    # --- POST ---

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if not parsed.path.startswith("/api/"):
            self._send(404, b"not found", "text/plain")
            return
        try:
            body = self._body()
        except Exception:
            body = {}
        with _lock:
            try:
                self._api_post(parsed.path, body)
            except Exception as exc:  # noqa: BLE001
                self._json({"error": str(exc)}, 500)

    def _api_post(self, path: str, body: dict):
        eng = get_engine()

        if path == "/api/label":
            eng.set_label(
                str(body.get("aid")), str(body.get("category") or ""), source="human"
            )
            eng.save()
            self._json({"ok": True})
        elif path == "/api/bulk_label":
            n = 0
            for aid in body.get("aids") or []:
                eng.set_label(str(aid), str(body.get("category") or ""), source="human")
                n += 1
            eng.save()
            self._json({"ok": True, "count": n})
        elif path == "/api/pipeline/run":
            passes = int(body.get("passes") or 1)
            reports = [eng.run_pass() for _ in range(max(1, min(5, passes)))]
            self._json({"ok": True, "reports": reports})
        elif path == "/api/rules/toggle":
            for rules in eng.state["rules"].values():
                for r in rules:
                    if r.get("id") == body.get("id"):
                        r["enabled"] = bool(body.get("enabled"))
            eng.save()
            self._json({"ok": True})
        elif path == "/api/rules/delete":
            for name, rules in eng.state["rules"].items():
                eng.state["rules"][name] = [
                    r for r in rules if r.get("id") != body.get("id")
                ]
            eng.save()
            self._json({"ok": True})
        elif path == "/api/rules/add":
            block = str(body.get("block") or "initial")
            if block not in eng.state["rules"]:
                raise ValueError("规则块无效")
            rule = {
                "id": (block[:1] + str(len(eng.state["rules"][block]) + 1) + "u"),
                "field": str(body.get("field") or "title"),
                "keywords": [k.strip() for k in (body.get("keywords") or []) if k.strip()],
                "category": str(body.get("category") or ""),
                "weight": float(body.get("weight") or 1.0),
                "strong": bool(body.get("strong")),
                "enabled": True,
            }
            if body.get("regex"):
                rule["regex"] = str(body.get("regex"))
            if not rule["keywords"] and not rule.get("regex"):
                raise ValueError("关键词/正则至少填一个")
            eng.ensure_leaf(rule["category"])
            eng.state["rules"][block].append(rule)
            eng.save()
            self._json({"ok": True, "rule": rule})
        elif path == "/api/taxonomy/leaf_parent":
            eng.set_leaf_parent(str(body.get("leaf")), str(body.get("parent") or ""))
            self._json({"ok": True})
        elif path == "/api/taxonomy/folder":
            eng.set_folder(str(body.get("kind")), str(body.get("name")), str(body.get("folder") or ""))
            self._json({"ok": True})
        elif path == "/api/taxonomy/group":
            eng.add_group(str(body.get("name") or "").strip(), str(body.get("folder") or ""))
            self._json({"ok": True})
        elif path == "/api/taxonomy/group_delete":
            eng.delete_group(str(body.get("name") or ""))
            self._json({"ok": True})
        elif path == "/api/settings":
            st = eng.state["settings"]
            for key in ("min_score", "min_margin", "min_fields", "reinforce_p", "reinforce_min_n"):
                if key in body:
                    st[key] = body[key]
            if "llm" in body:
                llm = dict(st.get("llm") or {})
                llm.update(body["llm"])
                st["llm"] = llm
            eng.save()
            self._json({"ok": True, "settings": st})
        elif path == "/api/ai/emit":
            n = eng.emit_ai_csv(DATA_DIR / "ai_queue.csv", int(body.get("limit") or 0))
            self._json({"ok": True, "count": n, "file": str(DATA_DIR / "ai_queue.csv")})
        elif path == "/api/ai/import":
            n = eng.import_ai_csv(Path(str(body.get("path") or DATA_DIR / "ai_result.csv")))
            self._json({"ok": True, "count": n})
        elif path == "/api/ai/run_llm":
            self._run_llm(eng, body)
        elif path == "/api/eval/fetch":
            if BG_PROGRESS["running"]:
                raise ValueError("已有后台任务在跑，请等它结束")
            picked = [str(x).strip() for x in (body.get("exclude") or []) if str(x).strip()]
            if picked:
                exclude = picked
            else:
                # 未指定时，自动排除"正在分类的那批夹"（= 已导入条目的来源夹）
                exclude = sorted({
                    str(it.get("src_media_id"))
                    for it in eng.state["items"]
                    if it.get("src_media_id")
                })
            api = get_api()

            def job():
                def on_progress(done, total, current):
                    BG_PROGRESS["done"], BG_PROGRESS["total"], BG_PROGRESS["current"] = done, total, current
                eng2 = get_engine()
                # 长任务不持有全局锁：引擎按夹增量保存，单用户场景下安全
                n = eng2.build_eval_from_api(api, exclude_media_ids=exclude, progress=on_progress)
                return f"评估集共 {n} 条"

            _run_bg("eval_fetch", job)
            self._json({"ok": True, "started": True})
        elif path == "/api/eval/progress":
            self._json(dict(BG_PROGRESS))
        elif path == "/api/eval/run":
            report = get_engine().run_evaluation()
            self._json({"ok": True, "report": report})
        elif path == "/api/eval/report":
            self._json(get_engine().state.get("eval_report") or {})
        elif path == "/api/tags/fetch":
            if BG_PROGRESS["running"]:
                raise ValueError("已有后台任务在跑，请等它结束")
            cap = max(1, min(50000, int(body.get("cap") or 1000)))
            mode = str(body.get("mode") or "random")
            workers = int(body.get("workers") or 2)
            cd_every = int(body.get("cooldown_every") or (500 if cap > 2000 else 0))
            cd_sec = float(body.get("cooldown_sec") or 45.0)
            api = get_api()

            def job():
                eng2 = get_engine()
                BG_PROGRESS["total"] = cap
                def on_prog(done, total, current):
                    BG_PROGRESS["done"], BG_PROGRESS["total"], BG_PROGRESS["current"] = done, total, current
                n = eng2.fetch_tags_batch(api, cap=cap, mode=mode, workers=workers,
                                          progress=on_prog,
                                          cooldown_every=cd_every, cooldown_sec=cd_sec)
                BG_PROGRESS["done"] = n
                return f"补拉了 {n} 条标签"

            _run_bg("tags", job)
            self._json({"ok": True, "started": True})
        elif path == "/api/corpus/set":
            r = eng.set_pools(
                [str(x) for x in (body.get("pool1") or [])],
                [str(x) for x in (body.get("pool2") or [])],
            )
            self._json({"ok": True, **r})
        elif path == "/api/guard/set":
            r = eng.set_guard(
                str(body.get("folder_id") or ""),
                str(body.get("level") or ""),
                reason=str(body.get("reason") or "手动设置"),
            )
            self._json({"ok": True, **r})
        elif path == "/api/scope/set":
            r = eng.set_move_scope(
                str(body.get("mode") or ""),
                [str(x) for x in (body.get("allow_sources") or [])],
            )
            self._json({"ok": True, **r})
        elif path == "/api/limits/set":
            r = eng.set_write_limits(
                per_run=body.get("per_run"), per_day=body.get("per_day")
            )
            self._json({"ok": True, "write_limits": r, "headroom": eng.write_headroom()})
        elif path == "/api/learn/hotwords2":
            summary = eng.learn_hotwords2(
                min_n=int(body.get("min_n") or 3),
                p_th=float(body.get("p_th") or 0.6),
            )
            self._json({"ok": True, "summary": summary})
        elif path == "/api/learn/hotwords":
            summary = eng.learn_hotwords(
                min_n=int(body.get("min_n") or 5),
                p_th=float(body.get("p_th") or 0.6),
            )
            self._json({"ok": True, "summary": summary})
        elif path == "/api/learn/weights":
            report = eng.learn_weights(split=float(body.get("split") or 0.8))
            self._json({"ok": True, "report": report})
        elif path == "/api/rules/import":
            p = Path(str(body.get("path") or DATA_DIR / "rules_export.md"))
            n = eng.import_rules_md(p)
            self._json({"ok": True, "imported": n})
        elif path == "/api/writeback/plan":
            allowed = {"auto", "ai", "human", "hot", "hot2", "review", "low", "none"}
            picked = [str(x) for x in (body.get("statuses") or []) if str(x) in allowed]
            statuses = tuple(picked) if picked else ("auto", "ai", "human", "hot", "hot2", "review")
            plan = build_writeback_plan(statuses=statuses)
            (DATA_DIR / "app_plan.json").write_text(
                json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            summary = [
                {"category": g["category"], "src": g["src_title"], "tar": g["tar_title"],
                 "count": len(g["items"]), "soft": g.get("soft", False)}
                for g in plan["groups"]
            ]
            self._json({"ok": True, "groups": summary,
                        "statuses": list(statuses),
                        "skipped": len(plan["skipped"]),
                        "limits": plan.get("limits") or {},
                        "soft_needs_confirm": plan.get("soft_needs_confirm") or [],
                        "total": sum(len(g["items"]) for g in plan["groups"])})
        elif path == "/api/writeback/apply":
            if str(body.get("confirm") or "") != "APPLY":
                raise ValueError("请输入确认文本 APPLY")
            plan_path = DATA_DIR / "app_plan.json"
            if not plan_path.exists():
                raise ValueError("请先生成计划（预览）")
            plan = json.loads(plan_path.read_text(encoding="utf-8"))

            # 二次确认：计划涉及软保护夹时必须额外输入确认串
            soft_names = plan.get("soft_needs_confirm") or []
            if soft_names and str(body.get("confirm_soft") or "") != "CONFIRM-SOFT":
                raise ValueError(
                    "本次计划涉及软保护收藏夹：" + "、".join(soft_names)
                    + "。请先逐条核对清单，再输入 CONFIRM-SOFT 确认执行。"
                )

            # 额度复核：计划可能已过期，按实际条数再算一次
            head = eng.write_headroom()
            planned = sum(len(g["items"]) for g in plan.get("groups") or [])
            if planned > head["day_remaining"]:
                raise ValueError(
                    f"超出当日写回额度：本计划 {planned} 条，今日还剩 {head['day_remaining']} 条。"
                    "请缩小移动范围或调高限额后重新生成计划。"
                )

            # 竞态复核：计划生成后若有夹被改成锁定，必须拦下
            from app_engine import GUARD_LOCKED as _LOCKED
            for g in plan.get("groups") or []:
                if eng.guard_level(g["src_media_id"]) == _LOCKED:
                    raise ValueError(
                        f"计划已过期：源夹「{g.get('src_title')}」现已锁定，请重新生成计划。"
                    )
                if eng.guard_level(g["tar_media_id"]) == _LOCKED:
                    raise ValueError(
                        f"计划已过期：目标夹「{g.get('tar_title')}」现已锁定，请重新生成计划。"
                    )

            plan["apply"] = True
            batch = int(get_settings_batch())
            state = apply_plan(get_api(), plan, DATA_DIR / "app_wb_state.json", False, batch)
            verify_and_report(get_api(), plan, state, DATA_DIR / "app_report.md")
            moved = sum(state.get("moved_per_tar", {}).values())
            eng.record_write(
                moved,
                targets=[g["tar_media_id"] for g in plan.get("groups") or []],
                sources=[g["src_media_id"] for g in plan.get("groups") or []],
                note=f"计划生成于 {plan.get('generated_at')}",
            )
            self._json({"ok": True, "moved": moved,
                        "report": str(DATA_DIR / "app_report.md")})
        else:
            self._json({"error": "not found"}, 404)

    def _run_llm(self, eng, body: dict):
        settings = eng.state["settings"]
        llm = settings.get("llm") or {}
        base_url = str(body.get("base_url") or llm.get("base_url") or "")
        api_key = str(body.get("api_key") or llm.get("api_key") or "")
        model = str(body.get("model") or llm.get("model") or "")
        if not (base_url and api_key and model):
            raise ValueError("请先在设置里填 LLM 接口（https 地址 + key + 模型名）")
        batch_size = max(5, min(100, int(body.get("batch_size") or llm.get("batch_size") or 30)))
        max_items = max(1, min(2000, int(body.get("max_items") or 300)))
        categories = [name for name in eng.state["taxonomy"]["leaves"]]
        pending = [it for it in eng.state["items"] if it.get("status") in ("low", "review")]
        pending = pending[:max_items]
        labeled = 0
        for i in range(0, len(pending), batch_size):
            batch = pending[i:i + batch_size]
            result = call_llm(base_url, api_key, model, batch, categories)
            for it in batch:
                cat = result.get(str(it["aid"]))
                if cat:
                    eng.set_label(str(it["aid"]), cat, source="ai", confidence="llm")
                    labeled += 1
        eng.save()
        self._json({"ok": True, "labeled": labeled, "pending_before": len(pending)})

    def _get(self):
        return self


def get_settings_batch() -> int:
    eng = get_engine()
    from export_fav import build_api, load_config
    cfg_path = CONFIG_PATH
    if not cfg_path.exists():
        return 10
    cfg = load_config(cfg_path)
    return int((cfg.get("settings") or {}).get("batch_size", 10))


def bootstrap_if_empty(eng) -> None:
    """首次启动：从现有导出数据/规则/配置/AI结果播种状态。"""
    if eng.state["items"]:
        return
    export_path = DATA_DIR / "export.json"
    if not export_path.exists():
        print("提示：data/export.json 不存在，先跑 export 命令导出收藏夹。")
        return
    n = eng.import_export(export_path)
    print(f"已导入 {n} 条导出记录")
    import yaml
    rules_path = RULES_PATH
    if rules_path.exists():
        eng.seed_rules_from_yaml(yaml.safe_load(rules_path.read_text(encoding="utf-8")) or {})
    cfg_path = CONFIG_PATH
    if cfg_path.exists():
        import yaml as _y
        cfg = _y.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        eng.seed_taxonomy_from_config(
            (cfg.get("writeback") or {}).get("category_to_folder") or {}
        )
    ai_path = DATA_DIR / "ai_result.csv"
    if ai_path.exists():
        n2 = eng.import_ai_csv(ai_path)
        print(f"已导入 {n2} 条AI标注")
    eng.save()


def main() -> None:
    global DEMO, HOST, PORT
    import argparse
    parser = argparse.ArgumentParser(description="B站收藏夹分类工作台（本地 Web）")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--demo", action="store_true", help="演示模式：无 Cookie，用内置示例数据")
    parser.add_argument("--no-browser", action="store_true", help="启动后不自动打开浏览器")
    args = parser.parse_args()
    HOST, PORT = args.host, args.port
    DEMO = args.demo or not CONFIG_PATH.exists()

    eng = get_engine()
    if DEMO:
        bootstrap_demo(eng)
    else:
        bootstrap_if_empty(eng)
    overview = eng.overview()
    print(f"状态文件：{DATA_DIR / 'app_state.json'}")
    print(f"已载入 {overview['total']} 条；状态分布 {overview['counts']}")
    if DEMO:
        print("【DEMO 模式】未检测到 config.yaml：示例数据仅供体验，导出/写回不可用。")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"分类工作台已启动：http://{HOST}:{PORT}  （Ctrl+C 停止）")
    if not args.no_browser:
        import threading as _th
        import webbrowser
        _th.Timer(1.0, lambda: webbrowser.open(f"http://{HOST}:{PORT}")).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("已停止")


if __name__ == "__main__":
    main()
