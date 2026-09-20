# -*- coding: utf-8 -*-
"""写回阶段·计划生成：读取最终分类表，解析目标收藏夹，生成移动计划 plan.json。

本模块不执行任何写操作；真实移动见 wb_exec.py / writeback.py --apply。
"""
from __future__ import annotations

import csv
import datetime as _dt
from pathlib import Path

from openpyxl import load_workbook

from bili_api import BiliApi

UNCAT_VALUES = {"", "未分类", "待定", "待ai", "人工", "不移动", "跳过", "skip", "none"}


def load_final_rows(path: Path) -> list:
    """从 classified.xlsx 或 CSV 读取人工确认过的 final_category 行。"""
    rows = []
    if path.suffix.lower() == ".xlsx":
        wb = load_workbook(path, data_only=True)
        ws = wb["classified"] if "classified" in wb.sheetnames else wb.active
        headers = {str(c.value or ""): i for i, c in enumerate(ws[1], start=1)}
        for need in ("aid", "src_media_id", "final_category"):
            if need not in headers:
                raise SystemExit(
                    f"{path} 缺少列 {need}（请先用 classify.py 生成并在 final_category 列确认）"
                )

        for r in ws.iter_rows(min_row=2, values_only=True):

            def cell(name, _r=r, _h=headers):
                i = _h.get(name)
                return _r[i - 1] if i and i <= len(_r) else None

            final = str(cell("final_category") or "").strip()
            if final.lower() in UNCAT_VALUES:
                continue
            aid = str(cell("aid") or "").strip()
            if not aid:
                continue
            rows.append(
                {
                    "aid": aid,
                    "bvid": str(cell("bvid") or ""),
                    "title": str(cell("title") or ""),
                    "type": cell("type"),
                    "dead": str(cell("dead") or "").strip(),
                    "src_media_id": str(cell("src_media_id") or ""),
                    "category": final,
                }
            )
    else:
        with path.open(encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                final = str(r.get("final_category") or "").strip()
                if final.lower() in UNCAT_VALUES:
                    continue
                aid = str(r.get("aid") or "").strip()
                if not aid:
                    continue
                rows.append(
                    {
                        "aid": aid,
                        "bvid": str(r.get("bvid") or ""),
                        "title": str(r.get("title") or ""),
                        "type": r.get("type"),
                        "dead": str(r.get("dead") or "").strip(),
                        "src_media_id": str(r.get("src_media_id") or ""),
                        "category": final,
                    }
                )
    if not rows:
        raise SystemExit("最终表中没有待移动条目（final_category 全为空/未分类）")
    return rows


def _resolve_targets(api: BiliApi, cfg: dict, categories: list, apply_mode: bool):
    """解析每个分类的目标收藏夹：config 映射优先，其次同名复用，缺的按需新建。"""
    wb_cfg = cfg.get("writeback") or {}
    mapping = {str(k): str(v) for k, v in (wb_cfg.get("category_to_folder") or {}).items()}
    privacy = int(wb_cfg.get("new_folder_privacy", 1))

    folders = api.list_created_folders()
    by_id = {str(f["id"]): f for f in folders}
    by_title = {str(f.get("title") or "").strip(): f for f in folders}

    resolve: dict = {}
    new_folders: dict = {}
    for cat in categories:
        mapped_id = mapping.get(cat)
        if mapped_id:
            if mapped_id not in by_id:
                raise SystemExit(
                    f"category_to_folder[{cat}]={mapped_id} 不在你的收藏夹列表中，请修正 config.yaml"
                )
            resolve[cat] = mapped_id
            mapped_title = by_id[mapped_id].get("title")
            print(f"分类「{cat}」→ 映射到已有收藏夹 {mapped_title} ({mapped_id})")
            continue
        same_title = by_title.get(cat)
        if same_title:
            resolve[cat] = str(same_title["id"])
            print(f"分类「{cat}」→ 复用同名收藏夹 {cat} ({resolve[cat]})")
            continue
        if apply_mode:
            info = api.create_folder(cat, intro="由收藏夹分类工具自动创建", privacy=privacy) or {}
            fid = str(info.get("id"))
            by_id[fid] = {"id": fid, "title": cat, "media_count": 0}
            resolve[cat] = fid
            new_folders[cat] = {"title": cat, "media_id": fid}
            vis = "私密" if privacy else "公开"
            print(f"分类「{cat}」→ 已新建{vis}收藏夹 {cat} ({fid})")
        else:
            resolve[cat] = None
            new_folders[cat] = {"title": cat, "media_id": None}
            print(f"分类「{cat}」→ 将新建收藏夹（dry-run，未实际创建）")
    return resolve, new_folders, by_id


def build_plan(api: BiliApi, cfg: dict, rows: list, apply_mode: bool) -> dict:
    """生成移动计划：按（源夹, 目标夹）分组，自动跳过失效/重复/超容量项。"""
    max_items = int((cfg.get("writeback") or {}).get("folder_max_items", 1000))

    categories = sorted(
        {r["category"] for r in rows},
        key=lambda c: (-sum(1 for r in rows if r["category"] == c), c),
    )
    resolve, new_folders, by_id = _resolve_targets(api, cfg, categories, apply_mode)

    tar_ids = {v for v in resolve.values() if v}
    tar_aids: dict = {}
    for tid in sorted(tar_ids):
        title = by_id.get(tid, {}).get("title", tid)
        print(f"读取目标收藏夹「{title}」现状 …")
        tar_aids[tid] = api.list_folder_aids(tid)

    groups: dict = {}
    skipped: list = []
    for r in rows:
        aid = r["aid"]
        bvid = r["bvid"]
        title = r["title"][:40]
        if r["dead"] in ("是", "1", "True", "true"):
            skipped.append({"aid": aid, "bvid": bvid, "title": title, "reason": "失效视频，不可移动"})
            continue
        try:
            if r["type"] not in (None, "") and int(r["type"]) != 2:
                skipped.append(
                    {"aid": aid, "bvid": bvid, "title": title,
                     "reason": f"非视频内容(type={r['type']}），不支持移动"}
                )
                continue
        except (TypeError, ValueError):
            pass
        tar = resolve.get(r["category"])
        if tar and int(aid) in tar_aids.get(tar, set()):
            skipped.append({"aid": aid, "bvid": bvid, "title": title, "reason": "已在目标收藏夹"})
            continue
        src = r["src_media_id"]
        if tar and src == tar:
            skipped.append({"aid": aid, "bvid": bvid, "title": title, "reason": "源收藏夹与目标相同"})
            continue
        key = (src, tar if tar else f"NEW::{r['category']}")
        groups.setdefault(key, {"category": r["category"], "items": []})
        groups[key]["items"].append({"aid": int(aid), "bvid": bvid, "title": r["title"]})

    # 目标夹容量校验（B站单夹上限；新建夹容量从 0 起算）
    cap_left = {tid: max_items - len(tar_aids.get(tid, set())) for tid in tar_ids}
    new_cap_left = max_items
    for key in sorted(groups):
        g = groups[key]
        tar = key[1]
        is_new = str(tar).startswith("NEW::")
        left = new_cap_left if is_new else cap_left.get(tar, 0)
        n_items = len(g["items"])
        if n_items > left:
            cap_title = g["category"] if is_new else by_id.get(tar, {}).get("title", tar)
            g_cat = g["category"]
            print(f"警告：分类「{g_cat}」目标夹「{cap_title}」剩余容量 {left}，{n_items} 条截断")
            g["items"] = g["items"][:left]
            if is_new:
                new_cap_left = 0
            else:
                cap_left[tar] = 0
        elif is_new:
            new_cap_left -= n_items
        else:
            cap_left[tar] = left - n_items
    groups = {k: v for k, v in groups.items() if v["items"]}

    plan_groups = []
    for (src, tar), g in sorted(groups.items()):
        is_new = str(tar).startswith("NEW::")
        plan_groups.append(
            {
                "src_media_id": src,
                "src_title": by_id.get(src, {}).get("title", src),
                "tar_media_id": None if is_new else tar,
                "tar_title": g["category"] if is_new else by_id.get(tar, {}).get("title", tar),
                "category": g["category"],
                "tar_count_before": 0 if is_new else len(tar_aids.get(tar, set())),
                "items": g["items"],
            }
        )

    return {
        "generated_at": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "apply": apply_mode,
        "new_folders": new_folders,
        "groups": plan_groups,
        "skipped": skipped,
    }


def print_plan_summary(plan: dict) -> None:
    total = sum(len(g["items"]) for g in plan["groups"])
    mode = "APPLY 执行" if plan["apply"] else "DRY-RUN 预览"
    print(f"\n==== 移动计划（{mode}）：共 {total} 条，{len(plan['groups'])} 组 ====")
    for g in plan["groups"]:
        cat = g["category"]
        src_title = g["src_title"]
        tar_title = g["tar_title"]
        count = len(g["items"])
        sample = "、".join(it["title"][:16] for it in g["items"][:3])
        print(f"  [{cat}] {src_title} => {tar_title}: {count} 条  例: {sample}")
    if plan["new_folders"]:
        pending = []
        created = []
        for cat, info in plan["new_folders"].items():
            fid = info["media_id"]
            if fid:
                created.append(f"{cat}({fid})")
            else:
                pending.append(cat)
        if pending:
            print(f"  将新建收藏夹：{'、'.join(pending)}")
        if created:
            print(f"  已新建收藏夹：{'、'.join(created)}")
    if plan["skipped"]:
        reasons: dict = {}
        for s in plan["skipped"]:
            reason = s["reason"]
            reasons[reason] = reasons.get(reason, 0) + 1
        detail = "；".join(f"{k}×{v}" for k, v in reasons.items())
        print(f"  跳过 {len(plan['skipped'])} 条：{detail}")
    print()
