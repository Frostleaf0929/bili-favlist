# -*- coding: utf-8 -*-
"""阶段1：导出收藏夹原始数据 → data/export.json + data/export.csv

用法：
  python src/export_fav.py --list                # 仅列出全部自建收藏夹
  python src/export_fav.py --all                 # 导出全部自建收藏夹
  python src/export_fav.py --media-id 123456     # 导出指定收藏夹（可重复）
  python src/export_fav.py                       # 使用 config.yaml export.media_ids
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import json
import sys
from pathlib import Path

import yaml

from bili_api import BiliApi, BiliApiError, DEFAULT_UA

CSV_COLUMNS = [
    "bvid", "aid", "title", "type", "up_mid", "up_name", "desc",
    "duration", "pubtime", "fav_time", "attr", "dead",
    "src_media_id", "src_folder_title",
]

DEAD_ATTRS = {1, 9}  # 1=其他原因删除 9=UP主删除


def load_config(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(
            f"缺少配置文件 {path}。请复制 config.example.yaml 为 config.yaml 并填写 Cookie。"
        )
    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    cookie = cfg.get("cookie") or {}
    for key in ("sessdata", "bili_jct", "dede_user_id"):
        val = str(cookie.get(key) or "").strip()
        if not val or "粘贴" in val:
            raise SystemExit(f"config.yaml 中 cookie.{key} 尚未填写（获取方式见 README）。")
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


def to_iso(ts) -> str:
    try:
        ts = int(ts)
    except (TypeError, ValueError):
        return ""
    if ts <= 0:
        return ""
    return _dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def collect_folder_rows(api: BiliApi, folder: dict, ps: int, on_progress=None) -> list:
    rows = []
    for pn, info, medias in api.iter_folder_resources(folder["id"], ps=ps):
        print(f"    第 {pn} 页，累计 {len(rows)} 条", flush=True)
        for m in medias:
            attr = int(m.get("attr") or 0)
            bvid = m.get("bv_id") or ""
            title = m.get("title") or ""
            dead = attr in DEAD_ATTRS or not bvid or title == "已失效视频"
            upper = m.get("upper") or {}
            rows.append(
                {
                    "bvid": bvid,
                    "aid": m.get("id"),
                    "title": title,
                    "type": m.get("type"),
                    "up_mid": upper.get("mid"),
                    "up_name": upper.get("name"),
                    "desc": (m.get("intro") or "").replace("\r", " ").replace("\n", " ").strip(),
                    "duration": m.get("duration"),
                    "pubtime": to_iso(m.get("pubtime")),
                    "fav_time": to_iso(m.get("fav_time")),
                    "attr": attr,
                    "dead": "是" if dead else "",
                    "src_media_id": folder["id"],
                    "src_folder_title": folder.get("title") or info.get("title") or "",
                }
            )
        if on_progress is not None:
            on_progress(rows)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="导出B站收藏夹原始数据")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--list", action="store_true", help="仅列出全部自建收藏夹后退出")
    parser.add_argument("--media-id", action="append", help="要导出的收藏夹 media_id，可重复")
    parser.add_argument("--all", action="store_true", help="导出全部自建收藏夹")
    parser.add_argument("--exclude", action="append", default=[], help="配合 --all：排除指定 media_id，可重复")
    parser.add_argument("--out-dir", default="data")
    args = parser.parse_args()

    cfg = load_config(Path(args.config))
    api = build_api(cfg)
    ps = int((cfg.get("settings") or {}).get("ps", 20))

    try:
        me = api.whoami()
    except BiliApiError as exc:
        raise SystemExit(f"登录校验失败：{exc}\nCookie 可能无效或已过期，请重新获取。")
    if not me.get("isLogin"):
        raise SystemExit("Cookie 无效或已过期（nav 接口返回未登录），请重新获取。")
    print(f"登录态 OK：{me.get('uname')} (mid={me.get('mid')})")

    folders = api.list_created_folders()
    print(f"共 {len(folders)} 个自建收藏夹：")
    for f in folders:
        print(f"  media_id={f['id']:>15}  {f.get('media_count', 0):>5} 条  {f.get('title')}")

    if args.list:
        return

    wanted: list = []
    if args.all:
        excluded = {str(x) for x in (args.exclude or [])}
        wanted = [f for f in folders if str(f["id"]) not in excluded]
    elif args.media_id:
        id2folder = {str(f["id"]): f for f in folders}
        for mid in args.media_id:
            if str(mid) not in id2folder:
                print(f"警告：media_id {mid} 不在自建收藏夹列表中，仍会尝试导出")
                wanted.append({"id": mid, "title": str(mid)})
            else:
                wanted.append(id2folder[str(mid)])
    else:
        configured = (cfg.get("export") or {}).get("media_ids") or []
        if not configured:
            raise SystemExit(
                "未指定收藏夹：用 --all / --media-id，或在 config.yaml export.media_ids 里配置。"
            )
        id2folder = {str(f["id"]): f for f in folders}
        wanted = [id2folder.get(str(x), {"id": x, "title": str(x)}) for x in configured]

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "export.json"
    csv_path = out_dir / "export.csv"

    completed: list = []
    tick = {"n": 0}

    def write_rows(rows):
        payload = {
            "exported_at": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "mid": api.mid,
            "folders": wanted,
            "items": rows,
        }
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        with csv_path.open("w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)

    def flush(partial):
        tick["n"] += 1
        if tick["n"] % 10:
            return
        write_rows(completed + partial)

    for folder in wanted:
        print(f"导出收藏夹：{folder.get('title')} (media_id={folder['id']})", flush=True)
        rows = collect_folder_rows(api, folder, ps, on_progress=flush)
        dead = sum(1 for r in rows if r["dead"])
        print(f"  完成：{len(rows)} 条（其中失效 {dead} 条）")
        completed.extend(rows)
        write_rows(completed)

    all_rows = completed
    unique = {r["aid"] for r in all_rows if r["aid"]}
    dead_total = sum(1 for r in all_rows if r["dead"])
    print(f"导出完成：共 {len(all_rows)} 行（去重后 {len(unique)} 个视频，失效 {dead_total}）")
    print(f"  {json_path}")
    print(f"  {csv_path}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
