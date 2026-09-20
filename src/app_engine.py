# -*- coding: utf-8 -*-
"""分类引擎 v2：多信号打分、共现概率强化规则、两级分类、多遍复查流水线。

核心规则（按用户需求）：
- 单一关键词（单字段单命中）不允许自动归类，必须多信号联合（可配置最少字段数）；
- AI/人工每次给条目定类，都会统计「关键词↔分类」共现概率；
  某关键词对某分类的 P >= reinforce_p（默认0.6）且样本数 >= reinforce_min_n 时，
  自动把该关键词升级为「强化规则」（独立规则块，可停用）；
- 分类体系两级：初始分类（leaf，可来自规则/AI/人工）可合并进大分类夹（group），
  写回时以 leaf 或其所属 group 绑定的B站收藏夹为目标；
- 流水线可反复运行，每遍生成差异报告，改判条目进入复核队列（review）。
"""
from __future__ import annotations

import copy
import csv
import datetime as _dt
import json
import re
from pathlib import Path

from bili_api import BiliApiError

STATE_VERSION = 2

DEFAULT_SETTINGS = {
    "min_score": 1.0,        # 最高分类得分下限
    "min_margin": 0.3,       # 与第二名分差
    "min_fields": 2,         # 至少命中几个不同信号字段（单关键词不自动命中）
    "reinforce_p": 0.6,      # 共现概率阈值
    "reinforce_min_n": 5,    # 强化所需最小样本数
    "promote_cap": 50,       # 每遍最多新强化规则数
    "llm": {"base_url": "", "api_key": "", "model": "", "batch_size": 30},
}

# ---- 收藏夹保护等级（写回时的安全闸门）----
GUARD_LOCKED = "locked"   # 锁定：既不能作移动目标，也不能作移动源
GUARD_SOFT = "soft"       # 软保护：可动，但需在计划里单独列出并经二次确认
GUARD_FREE = "free"       # 自由：正常参与
GUARD_LEVELS = (GUARD_LOCKED, GUARD_SOFT, GUARD_FREE)

# ---- 写回限额（防手滑 / 防异常批量搬运）----
DEFAULT_WRITE_LIMITS = {"per_run": 200, "per_day": 1000}

# 移动范围模式
SCOPE_MINIMAL = "minimal"        # 默认最小授权：仅 allow_sources 里的夹可作移动源
SCOPE_ALL_UNLOCKED = "all_unlocked"  # 除锁定夹外，任何夹都可作移动源


def now_str() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Engine:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.state_path = self.data_dir / "app_state.json"
        self.state = self._empty_state()
        self._load()

    # ---------- 状态管理 ----------

    def _empty_state(self) -> dict:
        return {
            "version": STATE_VERSION,
            "imported_at": "",
            "items": [],
            "item_index": {},
            "rules": {"manual": [], "initial": [], "ai": [], "reinforced": []},
            "taxonomy": {"groups": {}, "leaves": {}},
            "stats": {},
            "labels": {},
            "passes": [],
            "settings": copy.deepcopy(DEFAULT_SETTINGS),
            "corpus_folders": [],       # 学习池1（客观内容夹，学出的热词直达该分类）
            "corpus2_folders": [],      # 学习池2（情绪化/个人化夹，只学特征不映射原夹）
            "protected_folders": [],    # 受保护收藏夹 id：绝不作为写回目标/移动源
            "hotwords": {},             # 池1热词表: key -> {cats: [[cat, p, n], ...]}
            "hotwords2": {},            # 池2热词表（最优先检查，命中→【个人化】）
            "learned_weights": None,    # {"title": w, "tag": w, "up": w}
            "weight_report": None,      # 权重回验报告
            # ---- 写回安全闸门 ----
            "folder_guard": {},         # folder_id -> {"level": locked|soft|free, "reason","at"}
            "move_scope": {             # 哪些夹允许作为「移动源」（视频从哪搬出去）
                "mode": SCOPE_MINIMAL,  # 默认最小授权
                "allow_sources": [],    # minimal 模式下白名单
            },
            "write_limits": dict(DEFAULT_WRITE_LIMITS),
            "write_log": [],            # 每次写回追加一条，用于统计当日用量
        }

    PERSONAL_CATEGORY = "【个人化】"   # 池2命中的统一去处（新夹，绝不写回原夹）
    HOT2_MIN_SCORE = 1.5              # 池2命中门槛：单个UP名(2.0)或两个特征词(2.0)才触发
    HOT2_MIN_MARGIN = 0.25

    def _load(self) -> None:
        if self.state_path.exists():
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
            self.state = raw
            settings = copy.deepcopy(DEFAULT_SETTINGS)
            settings.update(raw.get("settings") or {})
            self.state["settings"] = settings
        # 旧状态文件缺新键时补默认值
        for key in ("corpus_folders", "corpus2_folders", "protected_folders",
                    "hotwords", "hotwords2"):
            self.state.setdefault(key, [] if "folders" in key else {})
        self.state.setdefault("folder_guard", {})
        self.state.setdefault("move_scope", {"mode": SCOPE_MINIMAL, "allow_sources": []})
        self.state.setdefault("write_limits", dict(DEFAULT_WRITE_LIMITS))
        self.state.setdefault("write_log", [])
        # 迁移：旧的 protected_folders（一维名单）→ folder_guard 的 locked 级
        for fid in self.state.get("protected_folders") or []:
            self.state["folder_guard"].setdefault(
                str(fid), {"level": GUARD_LOCKED, "reason": "迁移自旧保护名单", "at": now_str()}
            )
        self.state["item_index"] = {str(it["aid"]): it for it in self.state["items"]}
        # 迁移期补默认：最小授权模式下若从未播种过白名单，填入主夹
        self.seed_move_scope()

    def save(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.state["item_index"] = {}
        self.state_path.write_text(
            json.dumps(self.state, ensure_ascii=False), encoding="utf-8"
        )
        self.state["item_index"] = {str(it["aid"]): it for it in self.state["items"]}

    # ---------- 数据导入 ----------

    def import_export(self, export_path: Path) -> int:
        data = json.loads(Path(export_path).read_text(encoding="utf-8"))
        items = []
        for it in data.get("items") or []:
            aid = str(it.get("aid") or "")
            if not aid:
                continue
            old = self.state["item_index"].get(aid) or {}
            items.append(
                {
                    "aid": aid,
                    "bvid": it.get("bvid") or "",
                    "title": it.get("title") or "",
                    "up_name": it.get("up_name") or "",
                    "up_mid": str(it.get("up_mid") or ""),
                    "desc": it.get("desc") or "",
                    "tags": it.get("tags") or "",
                    "fav_time": it.get("fav_time") or "",
                    "dead": it.get("dead") or "",
                    "type": it.get("type"),
                    "src_media_id": str(it.get("src_media_id") or ""),
                    "src_folder_title": it.get("src_folder_title") or "",
                    # 分类结果
                    "status": old.get("status") or "low",
                    "category": old.get("category") or "",
                    "score": old.get("score") or 0,
                    "margin": old.get("margin") or 0,
                    "signals": old.get("signals") or [],
                }
            )
        self.state["items"] = items
        self.state["item_index"] = {str(it["aid"]): it for it in items}
        self.state["imported_at"] = now_str()
        self.save()
        return len(items)

    def import_ai_csv(self, path: Path, source: str = "ai") -> int:
        """导入 AI 结果 CSV（列：aid,category,confidence,note）。"""
        n = 0
        with Path(path).open(encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                aid = str(row.get("aid") or "").strip()
                cat = str(row.get("category") or "").strip()
                if not aid or aid not in self.state["item_index"]:
                    continue
                self.set_label(
                    aid,
                    cat,
                    source=source,
                    confidence=str(row.get("confidence") or ""),
                    note=str(row.get("note") or ""),
                )
                n += 1
        self.save()
        return n

    def seed_rules_from_yaml(self, rules_yaml: dict) -> None:
        """把 rules.yaml 的旧格式规则迁移为 v2 分块结构（一次性）。"""
        if any(self.state["rules"].values()):
            return
        weights = rules_yaml.get("weights") or {}
        for r in rules_yaml.get("up_rules") or []:
            kws = r.get("keywords") or ([r["match"]] if r.get("match") else [])
            rule = {
                "id": f"m{len(self.state['rules']['manual']) + 1}",
                "field": "up",
                "keywords": [str(k) for k in kws],
                "mid": r.get("mid"),
                "category": r["category"],
                "weight": float(r.get("weight", weights.get("up", 2.0))),
                "strong": True,
                "enabled": True,
            }
            self.state["rules"]["manual"].append(rule)
        for r in rules_yaml.get("title_rules") or []:
            self.state["rules"]["initial"].append(
                {
                    "id": f"i{len(self.state['rules']['initial']) + 1}",
                    "field": "title",
                    "keywords": [str(k) for k in (r.get("keywords") or [])],
                    "regex": r.get("regex"),
                    "category": r["category"],
                    "weight": float(r.get("weight", weights.get("title", 1.0))),
                    "strong": False,
                    "enabled": True,
                }
            )
        for r in rules_yaml.get("tag_rules") or []:
            self.state["rules"]["initial"].append(
                {
                    "id": f"i{len(self.state['rules']['initial']) + 1}",
                    "field": "tag",
                    "keywords": [str(k) for k in (r.get("keywords") or [])],
                    "category": r["category"],
                    "weight": float(r.get("weight", weights.get("tag", 0.6))),
                    "strong": False,
                    "enabled": True,
                }
            )

    def seed_taxonomy_from_config(self, category_to_folder: dict) -> None:
        """把 config 的 分类->收藏夹映射 迁移为两级体系初始状态。"""
        leaves = self.state["taxonomy"]["leaves"]
        for name, folder in (category_to_folder or {}).items():
            if name in leaves:
                leaves[name]["folder"] = str(folder)
            else:
                leaves[name] = {"parent": "", "folder": str(folder)}

    # ---------- 分类体系 ----------

    def effective_folder(self, leaf_name: str) -> str:
        leaf = self.state["taxonomy"]["leaves"].get(leaf_name) or {}
        if leaf.get("folder"):
            return str(leaf["folder"])
        parent = leaf.get("parent") or ""
        group = self.state["taxonomy"]["groups"].get(parent) or {}
        return str(group.get("folder") or "")

    def set_leaf_parent(self, leaf_name: str, parent: str) -> None:
        leaves = self.state["taxonomy"]["leaves"]
        if leaf_name not in leaves:
            leaves[leaf_name] = {"parent": "", "folder": ""}
        leaves[leaf_name]["parent"] = parent or ""
        self.save()

    def set_folder(self, kind: str, name: str, folder: str) -> None:
        container = (
            self.state["taxonomy"]["leaves"] if kind == "leaf"
            else self.state["taxonomy"]["groups"]
        )
        if name in container:
            container[name]["folder"] = str(folder or "")
            self.save()

    def add_group(self, name: str, folder: str = "") -> None:
        self.state["taxonomy"]["groups"].setdefault(name, {"folder": str(folder or "")})
        self.save()

    def delete_group(self, name: str) -> None:
        self.state["taxonomy"]["groups"].pop(name, None)
        for leaf in self.state["taxonomy"]["leaves"].values():
            if leaf.get("parent") == name:
                leaf["parent"] = ""
        self.save()

    def ensure_leaf(self, name: str) -> None:
        self.state["taxonomy"]["leaves"].setdefault(name, {"parent": "", "folder": ""})

    # ---------- 打分（多信号，单关键词不自动命中）----------

    @staticmethod
    def _field_text(item: dict, field: str) -> str:
        cached = item.get("_texts")
        if isinstance(cached, dict) and field in cached:
            return cached[field]
        if field == "title":
            return item.get("title") or ""
        if field == "tag":
            return item.get("tags") or ""
        if field == "up":
            return item.get("up_name") or ""
        if field == "desc":
            return item.get("desc") or ""
        return ""

    @staticmethod
    def prep_items(items: list) -> None:
        """批量打分前缓存小写字段文本（纯性能优化，保存前清除）。"""
        for it in items:
            it["_texts"] = {
                "title": (it.get("title") or "").lower(),
                "tag": (it.get("tags") or "").lower(),
                "up": (it.get("up_name") or "").lower(),
                "desc": (it.get("desc") or "").lower(),
            }

    @staticmethod
    def cleanup_items(items: list) -> None:
        for it in items:
            it.pop("_texts", None)

    def _rule_hits(self, rule: dict, item: dict) -> list:
        """返回该规则在此条目上命中的关键词列表。"""
        if not rule.get("enabled", True):
            return []
        mid = rule.get("mid")
        if mid is not None:
            return [f"mid:{mid}"] if str(item.get("up_mid") or "") == str(mid) else []
        text = self._field_text(item, rule.get("field") or "title").lower()
        if not text:
            return []
        kws = rule.get("keywords") or []
        hits = [k for k in kws if str(k).lower() in text]
        if not hits and rule.get("regex"):
            try:
                if re.search(rule["regex"], text, re.I):
                    hits = [f"re:{rule['regex']}"]
            except re.error:
                pass
        return hits

    def score_item(self, item: dict) -> dict:
        """多信号打分。返回 {category, score, margin, signals, matched}"""
        weights: dict = {}
        signals: dict = {}
        matched: list = []
        for block_name, rules in self.state["rules"].items():
            for rule in rules:
                hits = self._rule_hits(rule, item)
                if not hits:
                    continue
                cat = rule.get("category") or ""
                if not cat:
                    continue
                weight = float(rule.get("weight") or 1.0)
                weights[cat] = weights.get(cat, 0.0) + weight * len(hits)
                signals.setdefault(cat, set()).add(rule.get("field") or "title")
                for h in hits:
                    matched.append(
                        {"field": rule.get("field") or ("up_mid" if rule.get("mid") else "title"),
                         "kw": h, "category": cat, "rule_id": rule.get("id"),
                         "block": block_name}
                    )
        if not weights:
            return {"category": "", "score": 0.0, "margin": 0.0, "signals": [], "matched": []}
        ranked = sorted(weights.items(), key=lambda kv: kv[1], reverse=True)
        top_cat, top_score = ranked[0]
        margin = top_score - (ranked[1][1] if len(ranked) > 1 else 0.0)
        sig = sorted(signals.get(top_cat) or [])
        return {
            "category": top_cat,
            "score": round(top_score, 2),
            "margin": round(margin, 2),
            "signals": sig,
            "matched": matched,
        }

    def _is_auto(self, result: dict) -> bool:
        """自动命中条件（按需求：单一关键词不允许直接命中）：
        - 强规则（如 UP mid 精确匹配）可直接命中；
        - 否则需：得分与分差达标，且该分类命中 >=min_fields 个不同关键词
          （或跨 >=min_fields 个不同信号字段）。"""
        st = self.state["settings"]
        cat = result.get("category")
        if not cat:
            return False
        if result["score"] < float(st.get("min_score", 1.0)):
            return False
        if result["margin"] < float(st.get("min_margin", 0.3)):
            return False
        strong_hit = any(
            m["category"] == cat and self._rule_is_strong(m["rule_id"])
            for m in result.get("matched") or []
        )
        if strong_hit:
            return True
        need = max(2, int(st.get("min_fields", 2)))
        n_signals = len(result.get("signals") or [])
        n_keywords = sum(
            1 for m in result.get("matched") or [] if m["category"] == cat
        )
        return n_keywords >= need or n_signals >= need

    def _rule_is_strong(self, rule_id: str) -> bool:
        for rules in self.state["rules"].values():
            for r in rules:
                if r.get("id") == rule_id:
                    return bool(r.get("strong"))
        return False

    # ---------- 标注（人工/AI）与统计强化 ----------

    def set_label(self, aid: str, category: str, source: str = "human",
                  confidence: str = "", note: str = "") -> None:
        item = self.state["item_index"].get(str(aid))
        if not item:
            return
        category = (category or "").strip()
        labels = self.state["labels"]
        labels[str(aid)] = {
            "category": category,
            "source": source,
            "confidence": confidence,
            "note": note,
            "at": now_str(),
        }
        if not category or category == "未分类":
            item["status"] = "none"
            item["category"] = ""
        else:
            self.ensure_leaf(category)
            item["status"] = source if source in ("human", "ai") else "ai"
            item["category"] = category
        self._apply_labels_to_items()

    def _apply_labels_to_items(self) -> None:
        """把 labels 应用到 items（规则 auto 的不覆盖）。"""
        for aid, lab in self.state["labels"].items():
            item = self.state["item_index"].get(aid)
            if not item or item.get("status") == "auto":
                continue
            cat = lab.get("category") or ""
            if not cat or cat == "未分类":
                item["status"] = "none"
                item["category"] = ""
            else:
                item["status"] = lab.get("source") or "ai"
                item["category"] = cat

    def recompute_stats(self) -> None:
        """统计「关键词↔分类」共现：关键词空间 = 规则命中词 + 标签 + UP名。"""
        stats: dict = {}
        for item in self.state["items"]:
            lab = self.state["labels"].get(str(item["aid"]))
            if not lab:
                cat = item.get("category") if item.get("status") in ("auto",) else ""
                if not cat:
                    continue
            else:
                cat = lab.get("category") or ""
            if not cat or cat == "未分类":
                continue
            result = self.score_item(item)
            keys = set()
            for m in result.get("matched") or []:
                keys.add((m["field"] or "title") + ":" + str(m["kw"]).lower())
            for tag in (item.get("tags") or "").split(","):
                tag = tag.strip()
                if tag:
                    keys.add("tag:" + tag.lower())
            if item.get("up_name"):
                keys.add("up:" + str(item["up_name"]).strip().lower())
            for key in keys:
                bucket = stats.setdefault(key, {})
                bucket[cat] = bucket.get(cat, 0) + 1
        self.state["stats"] = stats

    def promote_reinforced_rules(self) -> list:
        """共现概率达到阈值的 (关键词,分类) 升级为强化规则。"""
        st = self.state["settings"]
        p_th = float(st.get("reinforce_p", 0.6))
        n_th = int(st.get("reinforce_min_n", 5))
        cap = int(st.get("promote_cap", 50))
        promoted = []
        existing = set()
        for rules in self.state["rules"].values():
            for r in rules:
                for kw in r.get("keywords") or []:
                    existing.add((r.get("field") or "title", str(kw).lower(), r.get("category")))
        for key, bucket in sorted(self.state["stats"].items()):
            if len(promoted) >= cap:
                break
            field, _, kw = key.partition(":")
            if not kw:
                continue
            total = sum(bucket.values())
            best_cat, best_n = max(bucket.items(), key=lambda kv: kv[1])
            p = best_n / total if total else 0.0
            if best_n < n_th or p < p_th:
                continue
            if best_cat == "未分类" or not best_cat:
                continue
            if (field, kw, best_cat) in existing:
                continue
            self.ensure_leaf(best_cat)
            rid = f"x{len(self.state['rules']['reinforced']) + 1}"
            self.state["rules"]["reinforced"].append(
                {
                    "id": rid,
                    "field": field,
                    "keywords": [kw],
                    "category": best_cat,
                    "weight": 1.0,
                    "strong": False,
                    "enabled": True,
                    "p": round(p, 3),
                    "n": best_n,
                }
            )
            existing.add((field, kw, best_cat))
            promoted.append({"id": rid, "field": field, "keyword": kw,
                             "category": best_cat, "p": round(p, 3), "n": best_n})
        return promoted

    # ---------- 流水线（可多遍）----------

    def run_pass(self) -> dict:
        """跑一遍完整流程：打分→套标注→统计→强化→复打分→一致性核验。
        判定优先级：人工/AI标注 > 池2个人化 > 规则 > 池1热词 > 低置信。"""
        self.prep_items(self.state["items"])
        # 1) 规则/热词/个人化 统一判定
        for item in self.state["items"]:
            result = self.score_item(item)
            item["score"] = result["score"]
            item["margin"] = result["margin"]
            item["signals"] = result["signals"]
            if item.get("status") in ("human", "ai", "none"):
                continue  # 已有标注的保留，不被覆盖
            status, cat = self._classify_item(item)
            if status == "auto" and item.get("status") == "auto" and item.get("category") == cat:
                continue  # 与上一遍一致，避免反复横跳进复核
            if status != "low":
                self.ensure_leaf(cat)
                if item.get("status") in ("auto", "hot", "hot2") and item.get("category") != cat:
                    item["status"] = "review"  # 曾被分类又被改判 → 复核队列
                else:
                    item["status"] = status
                item["category"] = cat
            else:
                item["status"] = "low"
                item["category"] = ""
        # 2) 重新套用标注（AI/人工优先于一切规则）
        self._apply_labels_to_items()
        # 3) 统计 + 强化
        self.recompute_stats()
        promoted = self.promote_reinforced_rules()
        # 4) 强化规则生效后再判定一遍，记录改判
        changed = []
        for item in self.state["items"]:
            before = item.get("category") or ""
            result = self.score_item(item)
            item["score"] = result["score"]
            item["margin"] = result["margin"]
            item["signals"] = result["signals"]
            if item.get("status") in ("human", "ai", "none"):
                continue
            status, cat = self._classify_item(item)
            if status != "low":
                self.ensure_leaf(cat)
                item["status"] = status
                item["category"] = cat
            else:
                item["status"] = "low"
                item["category"] = ""
            after = item.get("category") or ""
            if before != after:
                changed.append({"aid": item["aid"], "title": item["title"][:40],
                                "old": before or "-", "new": after or "-"})
                if before and item["status"] in ("auto", "hot", "hot2"):
                    item["status"] = "review"  # 有过分类又被改判 → 复核队列
        # 5) 报告
        counts: dict = {}
        for item in self.state["items"]:
            counts[item["status"]] = counts.get(item["status"], 0) + 1
        report = {
            "no": len(self.state["passes"]) + 1,
            "at": now_str(),
            "counts": counts,
            "changed": changed[:200],
            "changed_total": len(changed),
            "promoted": promoted,
        }
        self.state["passes"].append(report)
        self.cleanup_items(self.state["items"])
        self.save()
        return report

    # ---------- AI 队列 ----------

    def emit_ai_csv(self, path: Path, limit: int = 0) -> int:
        rows = []
        for item in self.state["items"]:
            if item.get("status") in ("low", "review"):
                rows.append(item)
                if limit and len(rows) >= limit:
                    break
        with Path(path).open("w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["aid", "bvid", "title", "up_name", "tags", "desc", "signals"])
            for it in rows:
                w.writerow([
                    it["aid"], it["bvid"], it["title"], it["up_name"],
                    it["tags"], (it["desc"] or "")[:150], ",".join(it.get("signals") or []),
                ])
        return len(rows)

    # ---------- 评估：用人工整理的收藏夹做标准答案 ----------

    def build_eval_from_api(self, api, exclude_media_ids=(), progress=None) -> int:
        """拉取其余收藏夹条目作为评估集（truth = 收藏夹名）。支持断点续拉。"""
        folders = api.list_created_folders()
        self.state["folder_titles"] = {
            str(f["id"]): str(f.get("title") or "") for f in folders
        }
        exclude = {str(x) for x in exclude_media_ids}
        done_ids = set(self.state.get("eval_done_folders") or [])
        todo = [
            f for f in folders
            if str(f["id"]) not in exclude and str(f["id"]) not in done_ids
        ]
        eval_items = list(self.state.get("eval_items") or [])
        seen_keys = {str(e["aid"]) + ":" + str(e["src_media_id"]) for e in eval_items}
        total_pages = sum(max(1, -(-int(f.get("media_count") or 0) // 20)) for f in todo) or 1
        done_pages = 0
        for f in todo:
            fid, title = str(f["id"]), str(f.get("title") or "")
            for pn, info, medias in api.iter_folder_resources(fid, ps=20):
                for m in medias:
                    aid = str(m.get("id") or "")
                    key = aid + ":" + fid
                    if not aid or key in seen_keys:
                        continue
                    seen_keys.add(key)
                    attr = int(m.get("attr") or 0)
                    bvid = m.get("bv_id") or ""
                    upper = m.get("upper") or {}
                    eval_items.append(
                        {
                            "aid": aid,
                            "bvid": bvid,
                            "title": m.get("title") or "",
                            "up_name": upper.get("name") or "",
                            "up_mid": str(upper.get("mid") or ""),
                            "desc": (m.get("intro") or "").replace("\n", " ").strip(),
                            "tags": "",
                            "fav_time": "",
                            "dead": "是" if (attr in (1, 9) or not bvid) else "",
                            "src_media_id": fid,
                            "truth": title,
                        }
                    )
                done_pages += 1
                if progress:
                    progress(done_pages, total_pages, title)
            done_ids.add(fid)
            self.state["eval_items"] = eval_items
            self.state["eval_done_folders"] = sorted(done_ids)
            self.save()
        self.state["eval_items"] = eval_items
        self.save()
        return len(eval_items)

    def run_evaluation(self) -> dict:
        """盲测：对评估集条目【忽略其收藏夹来源、不查任何标注】，仅用
        规则 + 个人热词表预测，再与人工分类（truth=收藏夹名）对比重合率。"""
        folder_titles = self.state.get("folder_titles") or {}
        hotwords = self.state.get("hotwords") or {}
        weights = self.state.get("learned_weights") or {"title": 1.0, "tag": 0.6, "up": 2.0}
        self.prep_items(self.state.get("eval_items") or [])
        rows = []
        for it in self.state.get("eval_items") or []:
            truth = it.get("truth") or ""
            pred_cat, pred_folder, source = "", "", "none"
            status, cat = self._classify_item(it)
            if cat:
                pred_cat = cat
                source = status
            if pred_cat:
                fid = self.effective_folder(pred_cat)
                pred_folder = folder_titles.get(fid, "")
                if not pred_folder:
                    pred_folder = pred_cat
            rows.append(
                {
                    "aid": it["aid"], "title": it["title"][:50], "truth": truth,
                    "pred": pred_folder or "（未预测）", "source": source,
                    "dead": it.get("dead") or "",
                }
            )
        self.cleanup_items(self.state.get("eval_items") or [])

        live = [r for r in rows if not r["dead"]]
        pool2 = set(self.state.get("corpus2_folders") or [])
        obj = [r for r in live if r["truth"] not in pool2]
        subj = [r for r in live if r["truth"] in pool2]
        obj_covered = [r for r in obj if r["source"] != "none"]
        obj_correct = [r for r in obj_covered if r["pred"] == r["truth"]]
        personal_hits = sum(1 for r in subj if r["pred"] == self.PERSONAL_CATEGORY)
        # 组级口径：预测夹与标准夹同属一个大分类夹也算一致（细分粒度差异不扣分）
        title_group: dict = {}
        for leaf_name, leaf in self.state["taxonomy"]["leaves"].items():
            parent = leaf.get("parent") or ""
            if not parent:
                continue
            fid = self.effective_folder(leaf_name)
            if fid:
                title_group[folder_titles.get(fid, "")] = parent
        group_correct = 0
        group_confusions: dict = {}
        for r in obj_covered:
            pg = title_group.get(r["pred"])
            tg = title_group.get(r["truth"])
            if r["pred"] == r["truth"]:
                group_correct += 1
            elif pg and pg == tg:
                group_correct += 1
            elif r["truth"]:
                key = (tg or "（未归组）") + " ⇒ " + (pg or r["pred"])
                group_confusions[key] = group_confusions.get(key, 0) + 1
        per: dict = {}
        confusions: dict = {}
        for r in obj:
            stat = per.setdefault(r["truth"], {"n": 0, "covered": 0, "correct": 0})
            stat["n"] += 1
            if r["source"] != "none":
                stat["covered"] += 1
                if r["pred"] == r["truth"]:
                    stat["correct"] += 1
                elif r["truth"] and r["pred"] != "（未预测）":
                    key = r["truth"] + " ⇒ " + r["pred"]
                    confusions[key] = confusions.get(key, 0) + 1
        per_list = [
            {
                "folder": k, "n": v["n"], "covered": v["covered"],
                "correct": v["correct"],
                "accuracy": round(v["correct"] / v["covered"], 3) if v["covered"] else None,
                "subjective": k in pool2,
            }
            for k, v in sorted(per.items(), key=lambda kv: -kv[1]["n"])
        ]
        source_counts: dict = {}
        for r in live:
            source_counts[r["source"]] = source_counts.get(r["source"], 0) + 1
        acc = len(obj_correct) / len(obj_covered) if obj_covered else 0
        cov = len(obj_covered) / len(obj) if obj else 0
        gacc = group_correct / len(obj_covered) if obj_covered else 0
        # 白话结论（可读性：直接给判断，不给裸数字）
        concl = []
        if obj_covered:
            concl.append(
                f"客观内容夹上，算法每 5 条预测里有 {round(len(obj_correct)/len(obj_covered)*5, 1)} 条"
                f"和你的手动分类一致（细分夹重合率 {round(acc*100)}%）"
            )
            if any(title_group.get(r["truth"]) for r in obj_covered):
                concl.append(
                    f"若按大分类夹口径考核（同组即算对），重合率为 {round(gacc*100)}%"
                    "——细分粒度差异已在组内消化"
                )
        concl.append(
            f"算法敢下判断的覆盖面是客观夹的 {round(cov*100)}%"
            + ("；其余主要是标题无信息量的长尾" if cov < 0.9 else "")
        )
        if pool2:
            concl.append(
                f"{len(pool2)} 个情绪化/个人化夹不参与重合率考核（排除人为随意分组的干扰），"
                f"只考核个人化特征识别：{personal_hits}/{len(subj)} 条被正确标为「个人化」"
                f"（{round(personal_hits/len(subj)*100) if subj else 0}%）"
            )
        top_conf = sorted(confusions.items(), key=lambda kv: -kv[1])[:3]
        if top_conf:
            concl.append("主要分歧：" + "；".join(k for k, _ in top_conf) + "——多为细分粒度差异，归并大分类夹后可消除")
        report = {
            "at": now_str(),
            "mode": "blind（规则+热词，忽略夹来源与标注）",
            "total": len(live),
            "dead": len(rows) - len(live),
            "covered": len(obj_covered),
            "coverage": round(cov, 3),
            "correct": len(obj_correct),
            "accuracy": round(acc, 3),
            "group_accuracy": round(gacc, 3),
            "group_correct": group_correct,
            "top_group_confusions": sorted(group_confusions.items(), key=lambda kv: -kv[1])[:15],
            "by_source": source_counts,
            "subjective_total": len(subj),
            "personal_hits": personal_hits,
            "conclusion": concl,
            "per_folder": per_list,
            "top_confusions": sorted(confusions.items(), key=lambda kv: -kv[1])[:30],
        }
        self.state["eval_report"] = report
        self.save()
        return report

    # ---------- 趣味数据 ----------

    def insights(self) -> dict:
        items = [it for it in self.state["items"] if not it.get("dead")]
        tag_n: dict = {}
        up_n: dict = {}
        month_n: dict = {}
        tag_covered = 0
        for it in items:
            tags = {t.strip() for t in (it.get("tags") or "").split(",") if t.strip()}
            if tags:
                tag_covered += 1
            for t in tags:
                tag_n[t] = tag_n.get(t, 0) + 1
            up = it.get("up_name") or ""
            if up:
                up_n[up] = up_n.get(up, 0) + 1
            ft = (it.get("fav_time") or "")[:7]
            if ft:
                month_n[ft] = month_n.get(ft, 0) + 1
        months = sorted(month_n)
        busiest = max(month_n.items(), key=lambda kv: kv[1]) if month_n else ("", 0)
        span_days = ""
        if months:
            span_days = f"{months[0]} ~ {months[-1]}"
        by_cat: dict = {}
        for it in items:
            c = it.get("category") or "（未分类）"
            by_cat[c] = by_cat.get(c, 0) + 1
        return {
            "total": len(items),
            "top_tags": sorted(tag_n.items(), key=lambda kv: -kv[1])[:50],
            "top_ups": sorted(up_n.items(), key=lambda kv: -kv[1])[:30],
            "unique_ups": len(up_n),
            "unique_tags": len(tag_n),
            "tag_coverage": round(tag_covered / len(items), 3) if items else 0,
            "monthly": [[m, month_n[m]] for m in months],
            "busiest_month": [busiest[0], busiest[1]],
            "span": span_days,
            "category_rank": sorted(by_cat.items(), key=lambda kv: -kv[1])[:25],
            "dead": sum(1 for it in self.state["items"] if it.get("dead")),
        }

    def fetch_tags_batch(self, api, cap: int = 50, mode: str = "random",
                         workers: int = 2, progress=None,
                         cooldown_every: int = 0, cooldown_sec: float = 45.0) -> int:
        """并发补拉标签（v2）：主列表+评估集按 bvid 去重，random 随机抽样。
        cooldown_every>0 时每拉完一批暂停 cooldown_sec 秒（防风控）。"""
        import random as _random
        import time as _time
        from concurrent.futures import ThreadPoolExecutor

        workers = max(1, min(4, int(workers)))
        pool = {}
        for it in (self.state["items"] + (self.state.get("eval_items") or [])):
            bvid = it.get("bvid") or ""
            if not bvid or it.get("dead") or (it.get("tags") or "").strip():
                continue
            pool.setdefault(bvid, []).append(it)
        bvids = list(pool.keys())
        if mode == "random" and len(bvids) > cap:
            rng = _random.SystemRandom()
            bvids = rng.sample(bvids, cap)
        else:
            bvids = bvids[:cap]
        if not bvids:
            return 0

        results: dict = {}
        done = {"n": 0}
        lock = __import__("threading").Lock()

        def work(bvid):
            try:
                names = api.fetch_tags(bvid)
            except BiliApiError:
                names = []
            results[bvid] = ",".join(names)
            with lock:
                done["n"] += 1
                if progress:
                    progress(done["n"], len(bvids), bvid)
            _time.sleep(0.4 + _random.SystemRandom().random() * 0.5)

        if cooldown_every and cooldown_every > 0:
            chunks = [bvids[i:i + cooldown_every] for i in range(0, len(bvids), cooldown_every)]
        else:
            chunks = [bvids]
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for ci, chunk in enumerate(chunks):
                list(ex.map(work, chunk))
                for bvid in chunk:   # 每批落盘一次，断点安全
                    for it in pool.get(bvid, []):
                        it["tags"] = results.get(bvid, "")
                self.save()
                if ci < len(chunks) - 1:
                    _time.sleep(cooldown_sec)

        self.save()
        return len(bvids)

    # ---------- 个人热词学习（思路1+2：按夹勾选语料 → 学热词 → 导出） ----------

    @staticmethod
    def extract_keys(item: dict) -> list:
        """统一证据抽取：标题二字(bigram)/标签/UP名。返回 [(key, field), ...]"""
        keys = []
        title = re.sub(r"\s+", "", (item.get("title") or "").lower())
        for i in range(len(title) - 1):
            keys.append(("b:" + title[i:i + 2], "title"))
        for tag in (item.get("tags") or "").split(","):
            tag = tag.strip().lower()
            if tag:
                keys.append(("g:" + tag, "tag"))
        up = (item.get("up_name") or "").strip().lower()
        if up:
            keys.append(("u:" + up, "up"))
        return keys

    def _corpus_items(self, pool: int = 1, min_folder_n: int = 5) -> list:
        selected = set(self.state.get("corpus_folders" if pool == 1 else "corpus2_folders") or [])
        folder_n: dict = {}
        for it in self.state.get("eval_items") or []:
            t = it.get("truth") or ""
            if t:
                folder_n[t] = folder_n.get(t, 0) + 1
        out = []
        for it in self.state.get("eval_items") or []:
            t = it.get("truth") or ""
            if not t or t not in selected or folder_n[t] < min_folder_n or it.get("dead"):
                continue
            out.append(it)
        return out

    def set_pools(self, pool1: list, pool2: list) -> dict:
        """设置双学习池；池2 的收藏夹自动设为「锁定」保护（绝不写回）。"""
        self.state["corpus_folders"] = [str(x) for x in pool1]
        self.state["corpus2_folders"] = [str(x) for x in pool2]
        title_to_id: dict = {}
        for it in self.state.get("eval_items") or []:
            t = it.get("truth") or ""
            if t:
                title_to_id.setdefault(t, str(it.get("src_media_id") or ""))
        protected = set(self.state.get("protected_folders") or [])
        newly = []
        for t in self.state["corpus2_folders"]:
            fid = title_to_id.get(t)
            if fid and fid not in protected:
                protected.add(fid)
                newly.append(t)
        self.state["protected_folders"] = sorted(protected)
        # 同步到分级保护：池2 一律 locked
        for t in self.state["corpus2_folders"]:
            fid = title_to_id.get(t)
            if fid:
                self.set_guard(fid, GUARD_LOCKED, reason="池2 情绪化/个人化夹（自动）", _save=False)
        self.seed_move_scope()
        self.save()
        return {"pool1": len(pool1), "pool2": len(pool2), "newly_protected": newly}

    # ---------- 收藏夹保护等级 / 移动范围 / 限额 ----------

    def guard_level(self, folder_id) -> str:
        """返回某收藏夹的保护等级；未登记过的一律按自由处理。"""
        fid = str(folder_id or "")
        if not fid:
            return GUARD_FREE
        entry = (self.state.get("folder_guard") or {}).get(fid) or {}
        lvl = entry.get("level") or ""
        if lvl in GUARD_LEVELS:
            return lvl
        # 兜底：仍按旧名单判断
        return GUARD_LOCKED if fid in (self.state.get("protected_folders") or []) else GUARD_FREE

    def set_guard(self, folder_id, level: str, reason: str = "", _save: bool = True) -> dict:
        """设置收藏夹保护等级。locked/soft 会同步进 protected_folders 保持旧逻辑兼容。"""
        fid = str(folder_id or "")
        if not fid:
            raise ValueError("缺少收藏夹 id")
        if level not in GUARD_LEVELS:
            raise ValueError(f"保护等级必须是 {GUARD_LEVELS} 之一")
        if level == GUARD_FREE:
            self.state["folder_guard"].pop(fid, None)
        else:
            self.state["folder_guard"][fid] = {
                "level": level, "reason": reason or "", "at": now_str()
            }
        prot = {str(x) for x in (self.state.get("protected_folders") or [])}
        if level == GUARD_LOCKED:
            prot.add(fid)
        else:
            prot.discard(fid)
        self.state["protected_folders"] = sorted(prot)
        if _save:
            self.save()
        return {"folder_id": fid, "level": level}

    def guard_snapshot(self) -> dict:
        """保护名单概览（含夹名，便于界面展示）。"""
        titles = self.state.get("folder_titles") or {}
        counts: dict = {}
        for it in (self.state.get("items") or []) + (self.state.get("eval_items") or []):
            sid = str(it.get("src_media_id") or "")
            if sid:
                counts[sid] = counts.get(sid, 0) + 1
        out = []
        for fid, entry in (self.state.get("folder_guard") or {}).items():
            out.append({
                "folder_id": fid,
                "title": titles.get(fid) or fid,
                "level": entry.get("level") or GUARD_FREE,
                "reason": entry.get("reason") or "",
                "at": entry.get("at") or "",
                "items_here": counts.get(fid, 0),
            })
        out.sort(key=lambda x: (GUARD_LEVELS.index(x["level"]), -x["items_here"]))
        return {
            "guards": out,
            "level_counts": {
                lv: sum(1 for x in out if x["level"] == lv) for lv in GUARD_LEVELS
            },
        }

    def seed_move_scope(self, force: bool = False) -> None:
        """给「最小授权」模式填入默认白名单：条目最多的那个来源夹（通常是主夹）。

        只在从未播种过时执行一次；用户显式清空白名单后不会被再次填入。
        """
        scope = self.state.setdefault(
            "move_scope", {"mode": SCOPE_MINIMAL, "allow_sources": []}
        )
        if scope.get("seeded") and not force:
            return
        scope["seeded"] = True
        if scope.get("allow_sources"):
            return
        counts: dict = {}
        for it in self.state.get("items") or []:
            sid = str(it.get("src_media_id") or "")
            if sid:
                counts[sid] = counts.get(sid, 0) + 1
        if counts:
            scope["allow_sources"] = [max(counts.items(), key=lambda kv: kv[1])[0]]

    def set_move_scope(self, mode: str, allow_sources: list) -> dict:
        if mode not in (SCOPE_MINIMAL, SCOPE_ALL_UNLOCKED):
            raise ValueError(f"移动范围模式必须是 {SCOPE_MINIMAL} / {SCOPE_ALL_UNLOCKED}")
        scope = self.state.setdefault("move_scope", {})
        scope["mode"] = mode
        scope["allow_sources"] = [str(x) for x in (allow_sources or [])]
        self.save()
        return {"mode": mode, "allow_sources": scope["allow_sources"]}

    def source_allowed(self, folder_id) -> bool:
        """该夹是否允许作为「移动源」（视频从它搬出去）。锁定夹永远不允许。"""
        fid = str(folder_id or "")
        if not fid:
            return False
        if self.guard_level(fid) == GUARD_LOCKED:
            return False
        scope = self.state.get("move_scope") or {}
        if scope.get("mode") == SCOPE_ALL_UNLOCKED:
            return True
        return fid in {str(x) for x in (scope.get("allow_sources") or [])}

    def set_write_limits(self, per_run=None, per_day=None) -> dict:
        lim = self.state.setdefault("write_limits", dict(DEFAULT_WRITE_LIMITS))
        if per_run is not None:
            lim["per_run"] = max(1, int(per_run))
        if per_day is not None:
            lim["per_day"] = max(1, int(per_day))
        self.save()
        return dict(lim)

    def _moved_today(self) -> int:
        today = _dt.date.today().isoformat()
        return sum(
            int(e.get("moved") or 0)
            for e in (self.state.get("write_log") or [])
            if str(e.get("at") or "").startswith(today)
        )

    def write_headroom(self) -> dict:
        """当前还剩多少写回额度。"""
        lim = self.state.get("write_limits") or DEFAULT_WRITE_LIMITS
        per_run, per_day = int(lim.get("per_run") or 200), int(lim.get("per_day") or 1000)
        used = self._moved_today()
        return {
            "per_run": per_run, "per_day": per_day,
            "moved_today": used,
            "run_remaining": per_run,
            "day_remaining": max(0, per_day - used),
            "today": _dt.date.today().isoformat(),
        }

    def record_write(self, moved: int, targets=None, sources=None, note: str = "") -> None:
        self.state.setdefault("write_log", []).append({
            "at": now_str(), "moved": int(moved or 0),
            "targets": [str(x) for x in (targets or [])],
            "sources": [str(x) for x in (sources or [])],
            "note": note,
        })
        self.state["write_log"] = self.state["write_log"][-200:]  # 只留最近 200 次
        self.save()

    def subjective_hint(self, title: str, n: int) -> bool:
        """粗判断疑似情绪化/个人化夹：无信息量短名，或盲测中一致率极低。"""
        stripped = re.sub(r"[\s\u3000]+", "", title or "")
        if len(stripped) <= 2 and not stripped.isalnum():
            return True
        if stripped in {"？", "。", "唉", "梦", "等待", "待处理", "过往未来", "追寻", "文字"}:
            return True
        rep = self.state.get("eval_report") or {}
        for row in rep.get("per_folder") or []:
            if row.get("folder") == title and row.get("n", 0) >= 30:
                if row.get("accuracy") is not None and row["accuracy"] < 0.2:
                    return True
                if row.get("covered", 0) == 0:
                    return True
        return False

    def learn_hotwords2(self, min_n: int = 3, p_th: float = 0.6, cap_per_key: int = 2) -> dict:
        """池2小学习：只学"排他性个人化特征"——该键在池1客观语料中从未出现，
        避免泛用词污染；命中一律归【个人化】，绝不映射回原情绪夹（原夹受保护）。"""
        corpus2 = self._corpus_items(pool=2)
        if not corpus2:
            raise ValueError("池2为空：先在语料面板把情绪化/个人化夹选入池2")
        self.ensure_leaf(self.PERSONAL_CATEGORY)
        pool1_keys = set()
        for it in self._corpus_items(pool=1):
            for key, _f in self.extract_keys(it):
                pool1_keys.add(key)
        counts = self._count_keys(corpus2)
        hot2: dict = {}
        excluded = 0
        for key, bucket in counts.items():
            if key in pool1_keys:
                excluded += 1
                continue
            n_total = sum(bucket.values())
            if n_total >= min_n:
                hot2[key] = {"cats": [[self.PERSONAL_CATEGORY, 1.0, n_total]]}
        self.state["hotwords2"] = hot2
        self.save()
        by_field: dict = {}
        for key in hot2:
            f = key.split(":", 1)[0]
            by_field[f] = by_field.get(f, 0) + 1
        return {"keys": len(hot2), "excluded_shared": excluded,
                "by_field": by_field, "corpus_items": len(corpus2)}

    def _hot_predict2(self, item: dict):
        """池2特征检查（最优先）。返回 (score, fields_n) 或 None。"""
        hot2 = self.state.get("hotwords2") or {}
        if not hot2:
            return None
        weights = {"title": 1.0, "tag": 0.6, "up": 2.0}
        score = 0.0
        fields = set()
        for key, field in self.extract_keys(item):
            if key in hot2:
                score += float(weights.get(field, 1.0))
                fields.add(field)
        if not fields:
            return None
        return (round(score, 3), len(fields))

    def _classify_item(self, item: dict) -> tuple:
        """统一判定（优先级：池2个人化 > 规则 > 池1热词 > 低置信）。
        返回 (status, category)；仅用于无人工/AI标注的条目。"""
        # 0) 池2：个人化特征最优先
        p2 = self._hot_predict2(item)
        if p2 and p2[0] >= self.HOT2_MIN_SCORE and p2[1] >= 1:
            return "hot2", self.PERSONAL_CATEGORY
        # 1) 规则（多信号门槛 / 强规则）
        result = self.score_item(item)
        if result["category"] and self._is_auto(result):
            return "auto", result["category"]
        # 2) 池1热词
        hotwords = self.state.get("hotwords") or {}
        if hotwords:
            weights = self.state.get("learned_weights") or {"title": 1.0, "tag": 0.6, "up": 2.0}
            cat, score, margin, _fields = self._hot_predict(item, hotwords, weights)
            if cat and score >= 0.8 and margin >= 0.3:
                return "hot", cat
        return "low", ""

    def _count_keys(self, corpus: list) -> dict:
        counts: dict = {}
        for it in corpus:
            cat = it.get("truth") or ""
            if not cat:
                continue
            for key, _field in self.extract_keys(it):
                counts.setdefault(key, {}).setdefault(cat, 0)
                counts[key][cat] += 1
        return counts

    def set_corpus_folders(self, folders: list) -> None:
        self.state["corpus_folders"] = [str(f) for f in folders]
        self.save()

    def learn_hotwords(self, min_n: int = 5, p_th: float = 0.6, cap_per_key: int = 3) -> dict:
        """从勾选语料学个人热词表：key -> [(分类, p, n)]，并把语料夹登记为分类叶。"""
        corpus = self._corpus_items()
        if not corpus:
            raise ValueError("语料为空：先在「手动分类对比」页勾选参与学习的收藏夹")
        title_to_id: dict = {}
        for it in corpus:
            title_to_id.setdefault(it.get("truth") or "", str(it.get("src_media_id") or ""))
        for title, fid in title_to_id.items():
            if title and fid:
                self.ensure_leaf(title)
                leaf = self.state["taxonomy"]["leaves"].get(title) or {}
                if not leaf.get("folder"):
                    self.set_folder("leaf", title, fid)

        counts = self._count_keys(corpus)
        hotwords: dict = {}
        for key, bucket in counts.items():
            total = sum(bucket.values())
            ranked = sorted(bucket.items(), key=lambda kv: -kv[1])
            kept = []
            for cat, n in ranked[:cap_per_key + 2]:
                p = n / total if total else 0
                if n >= min_n and p >= p_th:
                    kept.append([cat, round(p, 3), n])
                if len(kept) >= cap_per_key:
                    break
            if kept:
                hotwords[key] = {"cats": kept}
        self.state["hotwords"] = hotwords
        self.save()
        by_field: dict = {}
        for key in hotwords:
            f = key.split(":", 1)[0]
            by_field[f] = by_field.get(f, 0) + 1
        return {"keys": len(hotwords), "by_field": by_field, "corpus_items": len(corpus),
                "corpus_folders": sorted(title_to_id.keys())}

    # ---------- 权重学习 + 切分回验（思路3） ----------

    def _hot_predict(self, item: dict, hotwords: dict, weights: dict):
        """用热词表+字段权重预测单条。返回 (cat, score, margin, matched_fields)"""
        w = weights or {"title": 1.0, "tag": 0.6, "up": 2.0}
        scores: dict = {}
        fields_hit: dict = {}
        for key, field in self.extract_keys(item):
            entry = hotwords.get(key)
            if not entry:
                continue
            for cat, p, _n in entry["cats"]:
                fw = float(w.get(field, 1.0))
                scores[cat] = scores.get(cat, 0.0) + p * fw
                fields_hit.setdefault(cat, set()).add(field)
        if not scores:
            return "", 0.0, 0.0, []
        ranked = sorted(scores.items(), key=lambda kv: -kv[1])
        cat, best = ranked[0]
        margin = best - (ranked[1][1] if len(ranked) > 1 else 0.0)
        return cat, round(best, 3), round(margin, 3), sorted(fields_hit.get(cat) or [])

    def learn_weights(self, split: float = 0.8, seed: int = 42) -> dict:
        """切分回验学权重：语料按夹分层 80/20 切分，网格搜索字段权重，
        用留出集准确率选最优，并输出"重分类已分类条目"的一致率对比。"""
        import random as _random

        corpus = self._corpus_items()
        if len(corpus) < 50:
            raise ValueError(f"语料太少（{len(corpus)}条），先补拉 tags 并勾选足够收藏夹")

        by_cat: dict = {}
        for it in corpus:
            by_cat.setdefault(it["truth"], []).append(it)
        rng = _random.Random(seed)
        train, test = [], []
        for cat, items in sorted(by_cat.items()):
            items = sorted(items, key=lambda x: x["aid"])
            rng.shuffle(items)
            k = max(1, int(len(items) * split))
            train.extend(items[:k])
            test.extend(items[k:])
        if not test:
            raise ValueError("留出集为空：某些夹子条目过少")

        # 只用训练集学热词表（防自证）
        counts = self._count_keys(train)
        total_train = sum(sum(b.values()) for b in counts.values())
        hot_train: dict = {}
        for key, bucket in counts.items():
            total = sum(bucket.values())
            kept = [[c, round(n / total, 3), n] for c, n in
                    sorted(bucket.items(), key=lambda kv: -kv[1])[:3]
                    if n >= 5 and n / total >= 0.6]
            if kept:
                hot_train[key] = {"cats": kept}

        grid_title = [0.5, 1.0, 1.5]
        grid_tag = [1.0, 1.5, 2.0]
        grid_up = [2.0, 3.0, 4.0]
        trials = []
        for wt in grid_title:
            for wg in grid_tag:
                for wu in grid_up:
                    w = {"title": wt, "tag": wg, "up": wu}
                    correct = sum(
                        1 for it in test
                        if self._hot_predict(it, hot_train, w)[0] == it["truth"]
                    )
                    trials.append({"w": w, "acc": round(correct / len(test), 4)})
        trials.sort(key=lambda x: -x["acc"])
        best = trials[0]["w"]

        # 最优权重的完整回验：留出准确率 + 全语料重分类一致率
        heldout_correct = sum(
            1 for it in test if self._hot_predict(it, hot_train, best)[0] == it["truth"]
        )
        agree = disagree = 0
        changed_examples = []
        for it in corpus:
            pred = self._hot_predict(it, hot_train, best)[0]
            if pred == it["truth"]:
                agree += 1
            else:
                disagree += 1
                if len(changed_examples) < 30:
                    changed_examples.append(
                        {"title": it["title"][:36], "truth": it["truth"],
                         "pred": pred or "（未预测）"}
                    )
        report = {
            "at": now_str(),
            "corpus": len(corpus), "train": len(train), "test": len(test),
            "keys_train": len(hot_train),
            "best_weights": best,
            "heldout_accuracy": round(heldout_correct / len(test), 4),
            "reclass_agree": agree, "reclass_disagree": disagree,
            "changed_examples": changed_examples,
            "top_trials": trials[:5],
        }
        self.state["learned_weights"] = best
        self.state["weight_report"] = report
        # 全量热词表（训练+验证全部语料）供流水线使用
        self.learn_hotwords()
        self.save()
        return report

    # ---------- 规则包导出/导入（思路2） ----------

    def export_rules_md(self) -> str:
        st = self.state
        lines = [f"# bili-favlist 个人分类规则包（导出于 {now_str()}）", ""]
        w = st.get("learned_weights") or {"title": 1.0, "tag": 0.6, "up": 2.0}
        lines += [f"## 字段权重（学习结果）", "",
                  f"- title(标题): {w.get('title')}", f"- tag(标签): {w.get('tag')}",
                  f"- up(UP主): {w.get('up')}", ""]
        lines += ["## 手写/初筛/强化规则", "",
                  "| 块 | 字段 | 关键词/正则 | 分类 | 权重 | 启用 |",
                  "|---|---|---|---|---|---|"]
        for block, rules in st["rules"].items():
            for r in rules:
                kws = "，".join(r.get("keywords") or [])
                if r.get("regex"):
                    kws += (kws and "；" or "") + f"正则:{r['regex']}"
                lines.append(
                    f"| {block} | {r.get('field') or 'up'} | {kws} | {r.get('category')} "
                    f"| {r.get('weight')} | {'是' if r.get('enabled', True) else '否'} |"
                )
        lines += ["", "## 个人热词表（共现学习，p=概率 n=样本）", "",
                  "| 分类 | 字段 | 关键词 | p | n |", "|---|---|---|---|---|"]
        for key, entry in sorted((st.get("hotwords") or {}).items()):
            field = {"b": "title", "g": "tag", "u": "up"}.get(key.split(":", 1)[0], key.split(":", 1)[0])
            kw = key.split(":", 1)[1]
            for cat, p, n in entry["cats"]:
                lines.append(f"| {cat} | {field} | {kw} | {p} | {n} |")
        lines += ["", "## 个人化热词表（池2，命中归【个人化】）", "",
                  "| 分类 | 字段 | 关键词 | p | n |", "|---|---|---|---|---|"]
        for key, entry in sorted((st.get("hotwords2") or {}).items()):
            field = {"b": "title", "g": "tag", "u": "up"}.get(key.split(":", 1)[0], key.split(":", 1)[0])
            kw = key.split(":", 1)[1]
            for cat, p, n in entry["cats"]:
                lines.append(f"| {cat} | {field} | {kw} | {p} | {n} |")
        return "\n".join(lines)

    def export_rules_yaml(self) -> dict:
        st = self.state
        return {
            "exported_at": now_str(),
            "learned_weights": st.get("learned_weights"),
            "rules": st["rules"],
            "hotwords": st.get("hotwords") or {},
            "hotwords2": st.get("hotwords2") or {},
            "corpus_folders": st.get("corpus_folders") or [],
            "corpus2_folders": st.get("corpus2_folders") or [],
        }

    def import_rules_md(self, path: Path) -> int:
        """回导规则包 md 中的两张热词表与规则行（容错解析，按章节路由）。"""
        text = Path(path).read_text(encoding="utf-8")
        n = 0
        section = ""
        for raw in text.splitlines():
            line = raw.strip()
            if line.startswith("## "):
                section = line[3:].strip()
                continue
            if not line.startswith("|") or line.startswith("|---") or line.startswith("| 分类") \
                    or line.startswith("| 块"):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if "热词表" in section and len(cells) >= 5:
                target = (self.state.get("hotwords2") if "池2" in section
                          else self.state.get("hotwords"))
                cat, field, kw, p, n_ = cells[0], cells[1], cells[2], cells[3], cells[4]
                ns = {"title": "b", "tag": "g", "up": "u"}.get(field, field)
                try:
                    pf, nf = float(p), int(float(n_))
                except ValueError:
                    continue
                entry = target.setdefault(f"{ns}:{kw}", {"cats": []})
                entry["cats"] = [c for c in entry["cats"] if c[0] != cat]
                entry["cats"].append([cat, pf, nf])
                entry["cats"].sort(key=lambda c: -c[1])
                self.ensure_leaf(cat)
                n += 1
        self.save()
        return n

    # ---------- 概览 ----------

    def overview_category_count(self, name: str) -> int:
        return sum(1 for it in self.state["items"] if it.get("category") == name)

    def overview(self) -> dict:
        counts: dict = {}
        by_cat: dict = {}
        for item in self.state["items"]:
            counts[item["status"]] = counts.get(item["status"], 0) + 1
            cat = item.get("category") or "（未分类）"
            by_cat[cat] = by_cat.get(cat, 0) + 1
        rule_stats = []
        for key, bucket in self.state["stats"].items():
            total = sum(bucket.values())
            best_cat, best_n = max(bucket.items(), key=lambda kv: kv[1])
            rule_stats.append(
                {"key": key, "category": best_cat, "p": round(best_n / total, 3) if total else 0,
                 "n": total}
            )
        rule_stats.sort(key=lambda x: -x["n"])
        return {
            "imported_at": self.state["imported_at"],
            "counts": counts,
            "by_category": sorted(by_cat.items(), key=lambda kv: -kv[1]),
            "total": len(self.state["items"]),
            "rules": {
                name: len(rules) for name, rules in self.state["rules"].items()
            },
            "passes": self.state["passes"][-5:],
            "top_stats": rule_stats[:100],
        }
