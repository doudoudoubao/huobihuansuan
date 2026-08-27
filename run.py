#!/usr/bin/env python3
"""启动入口。

    python run.py           正式启动
    python run.py --check   部署自检：配置 / 数据库 / Telegram / 汇率源

会自动读取同目录下的 .env。
"""

from __future__ import annotations

import os
from pathlib import Path


def load_dotenv(path: Path) -> None:
    """极简 .env 加载器，避免为一个文件多引一个依赖。"""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


if __name__ == "__main__":
    load_dotenv(Path(__file__).with_name(".env"))
    from bot.main import main

    main()
