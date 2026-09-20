# -*- coding: utf-8 -*-
"""统一入口：python src/main.py {export|classify|writeback} [参数...]

打包绿色版：pyinstaller --onefile --name bili-favlist --paths src src/main.py
产物 dist/bili-favlist.exe，config.yaml / rules.yaml / data/ 放在 exe 同目录使用。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import classify  # noqa: E402
import export_fav  # noqa: E402
import writeback  # noqa: E402
import app_server  # noqa: E402

COMMANDS = {
    "export": export_fav.main,
    "classify": classify.main,
    "writeback": writeback.main,
    "app": app_server.main,
}


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        names = " | ".join(COMMANDS)
        raise SystemExit(
            f"用法: python main.py {names} [参数...]\n"
            "  export     导出收藏夹原始数据（--all / --media-id / --list）\n"
            "  classify   规则+AI 分类（--emit-ai / --merge-ai / --fetch-tags）\n"
            "  writeback  按最终分类表批量移动（默认 dry-run，--apply 执行）\n"
            "  app        启动本地交互式分类工作台（http://127.0.0.1:8787）"
        )
    cmd = sys.argv.pop(1)
    COMMANDS[cmd]()


if __name__ == "__main__":
    main()
