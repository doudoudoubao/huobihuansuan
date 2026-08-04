#!/usr/bin/env python3
"""探测各个候选汇率源在这台服务器上到底通不通、返回什么。

开发环境的网络策略挡掉了所有外部 API，没法在那边验证接口契约，
所以把探测放到真正能出网的机器上跑，拿真实响应回来再写代码。

    python3 scripts/probe_sources.py              # 全部探一遍
    python3 scripts/probe_sources.py stooq sina   # 只探指定的几个

只用标准库，不需要装任何东西。Docker 部署的话建议在容器里跑，
这样测到的才是 bot 实际所处的网络环境：

    docker compose run --rm bot python scripts/probe_sources.py
"""

from __future__ import annotations

import json
import ssl
import sys
import time
import urllib.error
import urllib.request

TIMEOUT = 12
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

#: (分组, 名称, URL, 额外请求头, 说明)
CANDIDATES: list[tuple[str, str, str, dict[str, str], str]] = [
    # Stooq 已确认整站上了 JS 反爬、CSV 端点 404，不再探测

    # --- 新浪财经：国内服务器上通常最快最稳，需要 Referer ---
    ("sina", "sina-fx", "https://hq.sinajs.cn/list=fx_susdcny",
     {"Referer": "https://finance.sina.com.cn"}, "外汇实时"),
    ("sina", "sina-multi", "https://hq.sinajs.cn/list=fx_susdcny,fx_susdjpy,fx_seurusd",
     {"Referer": "https://finance.sina.com.cn"}, "一次多个"),

    # --- 腾讯财经 ---
    ("tencent", "tencent-fx", "https://qt.gtimg.cn/q=fx_usdcny", {}, "外汇实时"),
    ("tencent", "tencent-multi", "https://qt.gtimg.cn/q=fx_usdcny,fx_usdjpy", {}, "一次多个"),

    # --- Yahoo：确认凭证流程在这台机器上是否管用 ---
    ("yahoo", "yahoo-crumb", "https://query1.finance.yahoo.com/v1/test/getcrumb", {}, "取访问凭证"),
    ("yahoo", "yahoo-chart", "https://query1.finance.yahoo.com/v8/finance/chart/CNY=X?range=1d&interval=5m",
     {}, "行情（不带凭证）"),

    # --- 其它免费免鉴权的候选 ---
    ("misc", "exchangerate-api", "https://api.exchangerate-api.com/v4/latest/USD", {}, "每日"),
    ("misc", "fxratesapi", "https://api.fxratesapi.com/latest?base=USD", {}, "号称实时"),
    ("misc", "floatrates", "https://www.floatrates.com/daily/usd.json", {}, "每日"),
    ("misc", "cbr-xml", "https://www.cbr-xml-daily.ru/latest.js", {}, "俄央行，每日"),

    # --- 已在用的源，作为对照基准 ---
    ("baseline", "frankfurter", "https://api.frankfurter.app/latest?from=USD", {}, "当前法币主力"),
    ("baseline", "binance", "https://data-api.binance.vision/api/v3/ticker/price?symbol=BTCUSDT", {}, "当前加密主力"),
]


def probe(url: str, headers: dict[str, str]) -> tuple[str, str]:
    """返回 (状态描述, 响应正文片段)。"""
    request = urllib.request.Request(url, headers={"User-Agent": UA, **headers})
    context = ssl.create_default_context()
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT, context=context) as response:
            body = response.read(4000)
            elapsed = (time.monotonic() - started) * 1000
            return f"HTTP {response.status} · {elapsed:.0f}ms", _preview(body)
    except urllib.error.HTTPError as exc:
        body = b""
        try:
            body = exc.read(1000)
        except Exception:  # noqa: BLE001
            pass
        return f"HTTP {exc.code}", _preview(body)
    except Exception as exc:  # noqa: BLE001
        return f"失败 {type(exc).__name__}", str(exc)[:160]


def _preview(body: bytes) -> str:
    """把响应压成一行，方便贴回聊天里。"""
    for encoding in ("utf-8", "gbk", "latin-1"):
        try:
            text = body.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        return f"<{len(body)} 字节二进制>"
    # JSON 太长就只留结构，其余原样截断
    text = " ".join(text.split())
    if text.startswith("{") and len(text) > 400:
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                keys = ", ".join(list(data)[:12])
                return f"JSON 顶层字段：{keys}  ……（共 {len(text)} 字符）"
        except ValueError:
            pass
    return text[:400] + ("…" if len(text) > 400 else "")


def main(argv: list[str]) -> int:
    wanted = {a.lower() for a in argv}
    rows = [c for c in CANDIDATES if not wanted or c[0] in wanted or c[1] in wanted]
    if not rows:
        print(f"没有匹配的候选。可用分组：{sorted({c[0] for c in CANDIDATES})}")
        return 1

    print("汇率源探测 · 把下面整段原样发回给我")
    print("=" * 68)
    group = ""
    for candidate_group, name, url, headers, note in rows:
        if candidate_group != group:
            group = candidate_group
            print(f"\n── {group} ──")
        status, preview = probe(url, headers)
        print(f"\n[{name}] {note}")
        print(f"  {url}")
        print(f"  → {status}")
        print(f"  {preview}")
        time.sleep(0.3)  # 别把人家也打限流了
    print("\n" + "=" * 68)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
