# -*- coding: utf-8 -*-
"""写回阶段·执行与核验：按计划分批移动，断点续跑，风控熔断，生成报告。

安全边界：
- 只有 move（移动），没有任何删除类调用；
- 认证类错误立即终止；连续 3 次失败视为风控，全部停止。
"""
from __future__ import annotations

import json
from pathlib import Path

from bili_api import AUTH_CODES, SKIP_CODES, BiliApi, BiliApiError


def _load_state(path: Path, resume: bool) -> dict:
    state = {"done": [], "results": [], "moved_per_tar": {}, "aborted": False}
    if resume and path.exists():
        state.update(json.loads(path.read_text(encoding="utf-8")))
        print(f"断点续跑：已完成 {len(state['done'])} 个批次")
    return state


def apply_plan(api: BiliApi, plan: dict, state_path: Path, resume: bool, batch_size: int) -> dict:
    state = _load_state(state_path, resume)

    def save():
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")

    consecutive_fails = 0
    for gi, group in enumerate(plan["groups"], start=1):
        cat = group["category"]
        src_id = group["src_media_id"]
        tar_id = group["tar_media_id"]
        src_title = group["src_title"]
        tar_title = group["tar_title"]
        if not tar_id:
            print(f"[{gi}/{len(plan['groups'])}] 跳过：分类「{cat}」目标夹未创建")
            continue
        batches = [group["items"][i:i + batch_size] for i in range(0, len(group["items"]), batch_size)]
        for bi, batch in enumerate(batches):
            key = f"{src_id}->{tar_id}#{bi}"
            if key in state["done"]:
                continue
            aids = [it["aid"] for it in batch]
            try:
                api.move_resources(src_id, tar_id, aids)
            except BiliApiError as exc:
                if exc.code in SKIP_CODES:
                    print(f"  [降级] {key} 整批失败[{exc.code}]，逐条重试")
                    ok_cnt = 0
                    for it in batch:
                        one_aid = it["aid"]
                        one_title = it["title"][:40]
                        try:
                            api.move_resources(src_id, tar_id, [one_aid], retries=1)
                            ok_cnt += 1
                        except BiliApiError as e2:
                            code2 = e2.code
                            msg2 = e2.message
                            print(f"    失败 aid={one_aid}: [{code2}] {msg2}")
                            state["results"].append(
                                {"key": key, "status": "item_fail", "aid": one_aid,
                                 "title": one_title, "code": code2, "msg": msg2}
                            )
                    state["done"].append(key)
                    tar_key = str(tar_id)
                    prev = state["moved_per_tar"].get(tar_key, 0)
                    state["moved_per_tar"][tar_key] = prev + ok_cnt
                    save()
                    consecutive_fails = 0
                    continue
                if exc.code in AUTH_CODES:
                    state["aborted"] = True
                    state["results"].append(
                        {"key": key, "status": "abort", "code": exc.code, "msg": exc.message}
                    )
                    save()
                    raise SystemExit(
                        f"认证失败[{exc.code}] {exc.message}：Cookie 可能已过期，已停止（可加 --resume 续跑）。"
                    )
                consecutive_fails += 1
                state["results"].append(
                    {"key": key, "status": "fail", "code": exc.code, "msg": exc.message, "count": len(batch)}
                )
                save()
                print(f"  [失败] {key}: [{exc.code}] {exc.message}（连续第 {consecutive_fails} 次）")
                if consecutive_fails >= 3:
                    state["aborted"] = True
                    save()
                    raise SystemExit(
                        "连续失败 3 次，疑似触发风控，已全部停止。请等待一段时间后加 --resume 续跑。"
                    )
                continue
            consecutive_fails = 0
            state["done"].append(key)
            tar_key = str(tar_id)
            prev = state["moved_per_tar"].get(tar_key, 0)
            state["moved_per_tar"][tar_key] = prev + len(batch)
            state["results"].append({"key": key, "status": "ok", "count": len(batch)})
            save()
            print(
                f"  [{gi}/{len(plan['groups'])}] {src_title} => {tar_title} "
                f"批{bi + 1}/{len(batches)}：移动 {len(batch)} 条"
            )
    save()
    ok_batches = sum(1 for r in state["results"] if r["status"] == "ok")
    moved_total = sum(state["moved_per_tar"].values())
    print(f"执行结束：成功批次 {ok_batches}，移动总数 {moved_total}")
    return state


def verify_and_report(api: BiliApi, plan: dict, state: dict, report_path: Path) -> None:
    folders = {str(f["id"]): f for f in api.list_created_folders()}
    gen_at = plan["generated_at"]
    lines = [f"# 收藏夹写回报告（{gen_at}）", ""]
    mode = "apply 执行" if plan["apply"] else "dry-run 预览"
    lines.append(f"- 模式：{mode}")
    if plan["apply"]:
        moved = sum(state.get("moved_per_tar", {}).values())
        lines.append(f"- 实际移动：{moved} 条")
    if plan["new_folders"]:
        lines.append("")
        lines.append("## 分类收藏夹")
        for cat, info in plan["new_folders"].items():
            fid = info["media_id"]
            status = f"media_id={fid}" if fid else "未创建（dry-run）"
            lines.append(f"- {cat}：{status}")
    lines.append("")
    lines.append("## 各组明细")
    lines.append("")
    for g in plan["groups"]:
        cat = g["category"]
        src_title = g["src_title"]
        tar_title = g["tar_title"]
        count = len(g["items"])
        before = g["tar_count_before"]
        if plan["apply"] and g["tar_media_id"]:
            info = folders.get(str(g["tar_media_id"]), {})
            after = info.get("media_count", "?")
        else:
            after = "-"
        lines.append(
            f"- 分类「{cat}」：{src_title} => {tar_title}，"
            f"计划 {count} 条（目标夹数量 {before} => {after}）"
        )
    if plan["skipped"]:
        lines.append("")
        lines.append("## 跳过清单")
        lines.append("")
        for s in plan["skipped"]:
            reason = s["reason"]
            title = s["title"]
            bvid = s["bvid"]
            lines.append(f"- {reason}：{title}（{bvid}）")
    if plan["apply"]:
        fails = [
            r for r in (state.get("results") or [])
            if r.get("status") in ("fail", "item_fail", "abort")
        ]
        if fails:
            lines.append("")
            lines.append("## 失败记录")
            lines.append("")
            for item in fails:
                code = item.get("code")
                msg = item.get("msg")
                label = item.get("title") or item.get("key")
                lines.append(f"- [{code}] {msg}：{label}")
        lines.append("")
        lines.append("> 建议到B站网页端抽查几个目标收藏夹，确认数量与内容后再继续全量。")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"报告 => {report_path}")
