# -*- coding: utf-8 -*-
"""阶段3 CLI：按最终分类表把视频批量移动到目标收藏夹（只移动，不删除）。

- 输入：data/classified.xlsx（读取 final_category 列）或 --input 指定的 CSV
  （CSV 需含列：aid, src_media_id, final_category，可选 bvid/title/dead/type）
- 默认 dry-run：只生成 data/plan.json 并打印摘要，不写B站。
- --apply：真实执行（每批 batch_size 条、随机间隔、断点续跑、连续风控熔断）。

用法：
  python src/writeback.py                                    # dry-run 预览
  python src/writeback.py --apply --category 编程开发 --limit 20   # 小批量试运行
  python src/writeback.py --apply                            # 全量
  python src/writeback.py --apply --resume                   # 中断后从 state.json 续跑

计划生成见 wb_plan.py，批量执行见 wb_exec.py。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from bili_api import BiliApi, BiliApiError, DEFAULT_UA
from wb_exec import apply_plan, verify_and_report
from wb_plan import build_plan, load_final_rows, print_plan_summary


def load_config(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(
            f"缺少配置文件 {path}（复制 config.example.yaml 为 config.yaml 并填写 Cookie）"
        )
    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    cookie = cfg.get("cookie") or {}
    for key in ("sessdata", "bili_jct", "dede_user_id"):
        val = str(cookie.get(key) or "").strip()
        if not val or "粘贴" in val:
            raise SystemExit(f"config.yaml 中 cookie.{key} 尚未填写。")
    return cfg


def build_api(cfg: dict) -> BiliApi:
    s = cfg.get("settings") or {}
    cookie = cfg["cookie"]
    return BiliApi(
        sessdata=str(cookie["sessdata"]),
        bili_jct=str(cookie["bili_jct"]),
        dede_user_id=str(cookie["dede_user_id"]),
        user_agent=s.get("user_agent") or DEFAULT_UA,
        read_rate=(s.get("read_rate_min", 0.8), s.get("read_rate_max", 1.6)),
        write_rate=(s.get("write_rate_min", 0.5), s.get("write_rate_max", 2.0)),
        timeout=int(s.get("timeout", 20)),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="按最终分类表批量移动收藏（默认 dry-run）")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--input", default="data/classified.xlsx")
    parser.add_argument("--apply", action="store_true", help="真实执行移动；不加则只生成计划预览")
    parser.add_argument("--resume", action="store_true", help="从 state.json 断点续跑")
    parser.add_argument("--category", action="append", help="只处理指定分类（可重复）")
    parser.add_argument("--limit", type=int, help="只处理前 N 条（小批量试运行）")
    parser.add_argument("--plan-out", default="data/plan.json")
    parser.add_argument("--state", default="data/state.json")
    parser.add_argument("--report", default="data/report.md")
    args = parser.parse_args()

    cfg = load_config(Path(args.config))
    api = build_api(cfg)
    try:
        me = api.whoami()
    except BiliApiError as exc:
        raise SystemExit(f"登录校验失败：{exc}\nCookie 可能无效或已过期，请重新获取。")
    if not me.get("isLogin"):
        raise SystemExit("Cookie 无效或已过期（nav 接口返回未登录），请重新获取。")
    print(f"登录态 OK：{me.get('uname')} (mid={me.get('mid')})")

    rows = load_final_rows(Path(args.input))
    if args.category:
        wanted = set(args.category)
        rows = [r for r in rows if r["category"] in wanted]
    if args.limit:
        rows = rows[: args.limit]
    print(f"待处理 {len(rows)} 条")

    try:
        plan = build_plan(api, cfg, rows, apply_mode=args.apply)
    except BiliApiError as exc:
        raise SystemExit(f"生成计划失败（读取/新建收藏夹时）：{exc}")

    out = Path(args.plan_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    print_plan_summary(plan)
    print(f"计划 => {out}")

    report_path = Path(args.report)
    if args.apply:
        s = cfg.get("settings") or {}
        state = apply_plan(
            api, plan, Path(args.state), args.resume, int(s.get("batch_size", 10))
        )
        verify_and_report(api, plan, state, report_path)
    else:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        gen_at = plan["generated_at"]
        report_path.write_text(
            f"# 收藏夹写回预览（{gen_at}）\n\n未执行（dry-run）。"
            "确认 plan.json 无误后加 --apply 执行；建议先用 --category 某分类 --limit 20 小批量试。\n",
            encoding="utf-8",
        )
        print("这是 dry-run 预览。确认后加 --apply 执行；建议先用 --category 某分类 --limit 20 小批量试。")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
