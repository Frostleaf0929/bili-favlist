# -*- coding: utf-8 -*-
"""阶段2：规则打分分类 → data/classified.xlsx；支持 AI 兜底清单导出/合并。

打分逻辑：
- up_rules / title_rules / tag_rules 命中分别按权重累加（默认 up=2.0 > title=1.0 > tag=0.6，
  单条规则可用 weight 覆盖默认值；关键词类规则每命中一个关键词加一次权重）。
- 每个分类求总分：最高分 >= thresholds.min_score 且与第二名差距 >= thresholds.min_margin
  → 规则自动归类（绿色）；否则进入 AI 兜底/人工（黄色；AI 分类不在定义内则红色）。

用法：
  python src/classify.py                                  # 规则打分 → data/classified.xlsx
  python src/classify.py --fetch-tags                     # 为拿不准的条目补拉 tags 后重新打分
  python src/classify.py --emit-ai                        # 导出待AI清单 data/ai_pending.csv
  python src/classify.py --merge-ai data/ai_result.csv    # 把AI结果合并回 xlsx

AI 兜底闭环：ai_pending.csv 交给 AI 分批分析（可用 ZCode 会话），产出 CSV 列：
  aid,category,confidence,note
其中 category 必须取自 rules.yaml categories（实在无法归类填"未分类"）。
重跑本命令不会丢失人工在 final_category 列已填的内容。
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
import time
from pathlib import Path

import yaml
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from bili_api import BiliApiError

COLUMNS = [
    "idx", "bvid", "aid", "type", "dead", "src_media_id", "src_folder_title",
    "title", "up_name", "up_mid", "fav_time", "desc", "tags",
    "recommended", "score", "margin", "source", "reason", "ai_confidence",
    "final_category",
]

FILL_AUTO = PatternFill("solid", fgColor="C6EFCE")  # 绿：规则自动归类
FILL_AI = PatternFill("solid", fgColor="FFEB9C")    # 黄：AI 推荐 / 待AI / 待人工
FILL_BAD = PatternFill("solid", fgColor="FFC7CE")   # 红：冲突/未定/未知分类

WIDTHS = {
    "idx": 6, "bvid": 14, "aid": 12, "type": 6, "dead": 5,
    "src_media_id": 12, "src_folder_title": 18, "title": 50, "up_name": 16,
    "up_mid": 12, "fav_time": 19, "desc": 40, "tags": 22,
    "recommended": 14, "score": 7, "margin": 7, "source": 8, "reason": 42,
    "ai_confidence": 12, "final_category": 14,
}

DEFAULT_WEIGHTS = {"up": 2.0, "title": 1.0, "tag": 0.6}
DEFAULT_THRESHOLDS = {"min_score": 1.0, "min_margin": 0.5}


def load_rules(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"缺少规则文件 {path}")
    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for section in ("up_rules", "title_rules", "tag_rules"):
        for r in cfg.get(section) or []:
            if not r.get("category"):
                raise SystemExit(f"rules.yaml 的 {section} 有条目缺少 category：{r}")
            if r.get("regex"):
                try:
                    re.compile(r["regex"], re.I)
                except re.error as exc:
                    raise SystemExit(f"rules.yaml 正则错误：{r['regex']}（{exc}）")
            has_cond = (
                r.get("keywords") or r.get("match") or r.get("regex")
                or (r.get("mid") is not None)
            )
            if not has_cond:
                raise SystemExit(f"rules.yaml 的 {section} 有条目没有任何匹配条件：{r}")
    return cfg


def load_export(data_dir: Path) -> list:
    json_path = data_dir / "export.json"
    if json_path.exists():
        data = json.loads(json_path.read_text(encoding="utf-8"))
        items = data.get("items") or []
    else:
        csv_path = data_dir / "export.csv"
        if not csv_path.exists():
            raise SystemExit("data/ 下没有 export.json / export.csv，请先运行 export_fav.py。")
        with csv_path.open(encoding="utf-8-sig") as fh:
            items = list(csv.DictReader(fh))
    norm = []
    for it in items:
        it = dict(it)
        it["aid"] = str(it.get("aid") or "")
        it["up_mid"] = str(it.get("up_mid") or "")
        it["src_media_id"] = str(it.get("src_media_id") or "")
        it["dead"] = "是" if str(it.get("dead") or "").strip() in ("是", "1", "True", "true") else ""
        norm.append(it)
    return norm


def load_tags_map(data_dir: Path) -> dict:
    path = data_dir / "tags.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def save_tags_map(data_dir: Path, tags: dict) -> None:
    (data_dir / "tags.json").write_text(
        json.dumps(tags, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def _kw_hits(text, keywords) -> list:
    t = str(text or "").lower()
    return [k for k in keywords if str(k).lower() in t]


def score_item(item: dict, rules: dict, weights: dict):
    scores: dict = {}
    reasons: dict = {}

    def add(cat, weight, why):
        scores[cat] = scores.get(cat, 0.0) + weight
        reasons.setdefault(cat, []).append(why)

    for r in rules.get("up_rules") or []:
        cat = r["category"]
        weight = float(r.get("weight", weights.get("up", DEFAULT_WEIGHTS["up"])))
        if r.get("mid") is not None and str(item.get("up_mid") or "") == str(r["mid"]):
            add(cat, weight, f"UP mid={r['mid']}")
            continue
        kws = r.get("keywords") or ([r["match"]] if r.get("match") else [])
        for k in _kw_hits(item.get("up_name"), kws):
            add(cat, weight, f"UP名含「{k}」")

    for r in rules.get("title_rules") or []:
        cat = r["category"]
        weight = float(r.get("weight", weights.get("title", DEFAULT_WEIGHTS["title"])))
        for k in _kw_hits(item.get("title"), r.get("keywords") or []):
            add(cat, weight, f"标题含「{k}」")
        if r.get("regex") and re.search(r["regex"], str(item.get("title") or ""), re.I):
            add(cat, weight, f"标题正则「{r['regex']}」")

    for r in rules.get("tag_rules") or []:
        cat = r["category"]
        weight = float(r.get("weight", weights.get("tag", DEFAULT_WEIGHTS["tag"])))
        for k in _kw_hits(item.get("tags"), r.get("keywords") or []):
            add(cat, weight, f"tag含「{k}」")

    return scores, reasons


def classify_rows(items, rules, weights, thresholds):
    min_score = float(thresholds.get("min_score", DEFAULT_THRESHOLDS["min_score"]))
    min_margin = float(thresholds.get("min_margin", DEFAULT_THRESHOLDS["min_margin"]))
    rows = []
    for idx_, item in enumerate(items, start=1):
        scores, reasons = score_item(item, rules, weights)
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        if not ranked:
            cat, best, margin, status = "", 0.0, 0.0, "low"
            reason = "无规则命中"
        else:
            cat, best = ranked[0]
            margin = best - (ranked[1][1] if len(ranked) > 1 else 0.0)
            if best >= min_score and margin >= min_margin:
                status = "auto"
                reason = "；".join(reasons.get(cat, []))[:400]
            else:
                status = "low"
                other = (
                    f"（次高 {ranked[1][0]}={ranked[1][1]:g}）" if len(ranked) > 1 else ""
                )
                reason = f"得分/分差不足{other}：" + "；".join(reasons.get(cat, []))[:300]
        rows.append(
            {
                "idx": idx_,
                "item": item,
                "recommended": cat,
                "score": round(best, 2),
                "margin": round(margin, 2),
                "source": "rule" if cat else "",
                "reason": reason,
                "status": status,
                "ai_confidence": "",
            }
        )
    return rows


def fetch_missing_tags(items, tags_map, rules, weights, thresholds, cap, config_path, data_dir):
    """为规则拿不准的条目按需补拉 tags（读接口，限速），缓存到 data/tags.json。"""
    from export_fav import build_api, load_config

    pre_rows = classify_rows(items, rules, weights, thresholds)
    pending = []
    seen = set()
    for row in pre_rows:
        it = row["item"]
        if row["status"] == "auto" or it["dead"] or not it.get("bvid"):
            continue
        if it["aid"] in tags_map or it["aid"] in seen:
            continue
        seen.add(it["aid"])
        pending.append(it)
    pending = pending[:cap]
    if not pending:
        print("没有需要补拉 tags 的条目")
        return items, tags_map

    cfg = load_config(Path(config_path))
    api = build_api(cfg)
    rng = random.SystemRandom()
    print(f"为 {len(pending)} 条待定条目补拉 tags（每条约 1 秒）…")
    for n, it in enumerate(pending, start=1):
        try:
            names = api.fetch_tags(it["bvid"])
        except BiliApiError as exc:
            names = []
            print(f"  [{n}/{len(pending)}] aid={it['aid']} tags 获取失败：{exc}")
        tags_map[it["aid"]] = ",".join(names)
        it["tags"] = ",".join(names)
        time.sleep(rng.uniform(0.6, 1.2))
        if n % 25 == 0:
            save_tags_map(data_dir, tags_map)
            print(f"  进度 {n}/{len(pending)}")
    save_tags_map(data_dir, tags_map)
    return items, tags_map


def load_ai_result(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"AI 结果文件不存在：{path}")
    with path.open(encoding="utf-8-sig") as fh:
        result = {}
        for r in csv.DictReader(fh):
            aid = str(r.get("aid") or "").strip()
            if aid:
                result[aid] = {
                    "category": str(r.get("category") or "").strip(),
                    "confidence": str(r.get("confidence") or "").strip(),
                    "note": str(r.get("note") or "").strip(),
                }
        return result


def merge_ai(rows, ai_result, category_names) -> set:
    """把 AI 结果合并进打分行。规则已自动归类(auto)或人工已填 final 的行不受影响。"""
    unknown = set()
    for row in rows:
        aid = row["item"]["aid"]
        if aid not in ai_result or row["status"] == "auto":
            continue
        ai = ai_result[aid]
        cat = ai["category"]
        row["ai_confidence"] = ai["confidence"]
        note = f"AI建议「{cat}」" + (f"（{ai['note']}）" if ai["note"] else "")
        row["reason"] = (note + "；" + row["reason"])[:400]
        if not cat or cat in ("未分类", "无法判断"):
            row["status"] = "bad"
            continue
        if cat not in category_names:
            unknown.add(cat)
        row["recommended"] = cat
        row["source"] = "ai"
        row["status"] = "ai" if cat in category_names else "bad"
    return unknown


def preserve_final(path: Path) -> dict:
    """读旧 xlsx 里人工填过的 final_category，避免重跑时丢失。"""
    if not path.exists():
        return {}
    try:
        wb = load_workbook(path, data_only=True)
    except Exception:
        return {}
    ws = wb["classified"] if "classified" in wb.sheetnames else wb.active
    headers = {str(c.value or ""): i for i, c in enumerate(ws[1], start=1)}
    if "final_category" not in headers or "aid" not in headers:
        return {}
    out = {}
    for r in ws.iter_rows(min_row=2, values_only=True):
        try:
            aid = str(r[headers["aid"] - 1] or "").strip()
        except Exception:
            continue
        if not aid:
            continue
        src = (
            str(r[headers["src_media_id"] - 1] or "")
            if "src_media_id" in headers else ""
        )
        val = r[headers["final_category"] - 1]
        if val not in (None, ""):
            out[(aid, src)] = str(val).strip()
    return out


def write_xlsx(rows, categories, thresholds, weights, out_path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "classified"
    ws.append(COLUMNS)
    for c in ws[1]:
        c.font = Font(bold=True)

    fill_of = {"auto": FILL_AUTO, "ai": FILL_AI, "low": FILL_AI, "bad": FILL_BAD}
    counts: dict = {}
    for row in rows:
        item = row["item"]
        vals = [
            row["idx"], item.get("bvid"), item.get("aid"), item.get("type"),
            item.get("dead"), item.get("src_media_id"), item.get("src_folder_title"),
            item.get("title"), item.get("up_name"), item.get("up_mid"),
            item.get("fav_time"), item.get("desc"), item.get("tags"),
            row["recommended"], row["score"], row["margin"], row["source"],
            row["reason"], row["ai_confidence"], row["final"],
        ]
        ws.append(vals)
        for c in ws[ws.max_row]:
            c.fill = fill_of.get(row["status"], FILL_AI)
            c.alignment = Alignment(vertical="top")
        counts[row["status"]] = counts.get(row["status"], 0) + 1

    for i, col in enumerate(COLUMNS, start=1):
        ws.column_dimensions[get_column_letter(i)].width = WIDTHS.get(col, 12)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    st = wb.create_sheet("统计")
    st.append(["状态", "数量"])
    for k in ("auto", "ai", "low", "bad"):
        st.append([k, counts.get(k, 0)])
    st.append([])
    by_cat: dict = {}
    for row in rows:
        c = row["final"] or row["recommended"]
        if c:
            by_cat[c] = by_cat.get(c, 0) + 1
    st.append(["分类", "数量"])
    for k, v in sorted(by_cat.items(), key=lambda kv: -kv[1]):
        st.append([k, v])
    for i, w in enumerate([24, 10], start=1):
        st.column_dimensions[get_column_letter(i)].width = w

    rd = wb.create_sheet("说明")
    for line in [
        ["字段/颜色说明"],
        ["绿色行", "规则自动归类（可直接用）"],
        ["黄色行", "AI 推荐 / 待AI / 待人工"],
        ["红色行", "冲突或未知分类，请人工处理"],
        [""],
        ["操作", "在 final_category 列填写确认的分类；留空表示采用 recommended 列"],
        ["写回", "writeback.py 只处理 final_category 非空且不是'未分类'的行"],
        [""],
        ["分类定义（rules.yaml）", "说明"],
    ]:
        rd.append(line)
    for name, meta in (categories or {}).items():
        desc = meta.get("description", "") if isinstance(meta, dict) else str(meta)
        rd.append([name, desc])
    rd.append([])
    rd.append(["权重 weights", json.dumps(weights, ensure_ascii=False)])
    rd.append(["阈值 thresholds", json.dumps(thresholds, ensure_ascii=False)])
    for i, w in enumerate([36, 60], start=1):
        rd.column_dimensions[get_column_letter(i)].width = w

    wb.save(out_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="规则+AI 分类")
    parser.add_argument("--rules", default="rules.yaml")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--config", default="config.yaml", help="--fetch-tags 时使用的配置")
    parser.add_argument("--out", default=None, help="输出 xlsx，默认 data/classified.xlsx")
    parser.add_argument("--fetch-tags", action="store_true", help="为规则拿不准的条目补拉 tags")
    parser.add_argument("--fetch-tags-cap", type=int, default=500)
    parser.add_argument("--emit-ai", action="store_true", help="导出待AI清单 data/ai_pending.csv")
    parser.add_argument("--merge-ai", metavar="CSV", help="合并AI结果 CSV（列：aid,category,confidence,note）")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    rules_cfg = load_rules(Path(args.rules))
    categories = rules_cfg.get("categories") or {}
    weights = rules_cfg.get("weights") or {}
    thresholds = rules_cfg.get("thresholds") or {}
    rules = {k: rules_cfg.get(k) or [] for k in ("up_rules", "title_rules", "tag_rules")}

    items = load_export(data_dir)
    tags_map = load_tags_map(data_dir)
    for it in items:
        t = tags_map.get(it["aid"])
        it["tags"] = t if t is not None else (it.get("tags") or "")
    print(f"载入 {len(items)} 条导出记录")

    if args.fetch_tags:
        items, tags_map = fetch_missing_tags(
            items, tags_map, rules, weights, thresholds,
            args.fetch_tags_cap, args.config, data_dir,
        )

    rows = classify_rows(items, rules, weights, thresholds)

    unknown = set()
    if args.merge_ai:
        ai_result = load_ai_result(Path(args.merge_ai))
        unknown = merge_ai(rows, ai_result, set(categories.keys()))
        if unknown:
            print(f"警告：AI 返回了 rules.yaml 未定义的分类：{sorted(unknown)}（已标红待人工）")

    out_path = Path(args.out) if args.out else data_dir / "classified.xlsx"
    preserved = preserve_final(out_path)
    for row in rows:
        item = row["item"]
        row["final"] = preserved.get((item["aid"], item["src_media_id"]), "")

    write_xlsx(rows, categories, thresholds, weights, out_path)

    n_auto = sum(1 for r in rows if r["status"] == "auto")
    n_final = sum(1 for r in rows if r["final"])
    print(f"规则自动归类 {n_auto} 条，待AI/人工 {len(rows) - n_auto} 条，人工已确认 {n_final} 条")
    print(f"输出 → {out_path}")
    print("下一步：打开 xlsx 人工确认 final_category 列；或 --emit-ai 导出AI兜底清单")

    if args.emit_ai:
        pending_path = data_dir / "ai_pending.csv"
        cols = ["aid", "bvid", "title", "up_name", "desc", "tags", "src_media_id", "recommended"]
        with pending_path.open("w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            for row in rows:
                if row["status"] == "auto" or row["final"]:
                    continue
                it = row["item"]
                w.writerow(
                    {
                        "aid": it.get("aid"), "bvid": it.get("bvid"),
                        "title": it.get("title"), "up_name": it.get("up_name"),
                        "desc": (it.get("desc") or "")[:200], "tags": it.get("tags"),
                        "src_media_id": it.get("src_media_id"),
                        "recommended": row["recommended"],
                    }
                )
        print(f"AI 兜底清单 → {pending_path}")
        print("（AI 返回 CSV 列：aid,category,confidence,note；category 取自 rules.yaml categories）")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
