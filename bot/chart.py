"""走势图渲染（matplotlib 可选依赖）。

图内文字一律用英文/数字，避免容器里缺中文字体导致豆腐块。
"""

from __future__ import annotations

import io
import logging
from datetime import date
from decimal import Decimal
from typing import Sequence

log = logging.getLogger(__name__)

try:  # pragma: no cover - 取决于运行环境
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    AVAILABLE = True
except Exception:  # noqa: BLE001
    AVAILABLE = False


UP = "#16a34a"
DOWN = "#dc2626"
GRID = "#e5e7eb"
FG = "#111827"
MUTED = "#6b7280"


def render_series(series: Sequence[tuple[date, Decimal]], base: str, quote: str, days: int) -> bytes | None:
    """把 (日期, 汇率) 序列画成 PNG；未安装 matplotlib 或数据不足时返回 None。"""
    if not AVAILABLE or len(series) < 2:
        return None
    try:
        xs = [item[0] for item in series]
        ys = [float(item[1]) for item in series]
        rising = ys[-1] >= ys[0]
        color = UP if rising else DOWN

        fig, ax = plt.subplots(figsize=(8, 4), dpi=160)
        fig.patch.set_facecolor("white")
        ax.set_facecolor("white")

        ax.plot(xs, ys, color=color, linewidth=2.0, solid_capstyle="round")
        ax.fill_between(xs, ys, min(ys) - (max(ys) - min(ys) or 1) * 0.08, color=color, alpha=0.10)

        high, low = max(ys), min(ys)
        ax.axhline(high, color=MUTED, linewidth=0.6, linestyle=":", alpha=0.7)
        ax.axhline(low, color=MUTED, linewidth=0.6, linestyle=":", alpha=0.7)

        change = (ys[-1] - ys[0]) / ys[0] * 100 if ys[0] else 0.0
        ax.set_title(
            f"{base}/{quote}   {ys[-1]:,.6g}   ({change:+.2f}% / {days}d)",
            fontsize=13,
            color=FG,
            pad=12,
            loc="left",
        )

        ax.grid(True, color=GRID, linewidth=0.7)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_color(GRID)
        ax.spines["bottom"].set_color(GRID)
        ax.tick_params(colors=MUTED, labelsize=9)

        locator = mdates.AutoDateLocator(maxticks=7)
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))

        margin = (high - low) * 0.12 or (high * 0.01 or 1)
        ax.set_ylim(low - margin, high + margin)

        ax.annotate(
            f"{ys[-1]:,.6g}",
            xy=(xs[-1], ys[-1]),
            xytext=(-4, 8),
            textcoords="offset points",
            fontsize=10,
            color=color,
            ha="right",
            weight="bold",
        )

        buffer = io.BytesIO()
        fig.tight_layout()
        fig.savefig(buffer, format="png", facecolor=fig.get_facecolor())
        plt.close(fig)
        return buffer.getvalue()
    except Exception:  # noqa: BLE001 - 画图失败不该影响主流程
        log.exception("渲染走势图失败")
        return None


def summarize(series: Sequence[tuple[date, Decimal]]) -> tuple[Decimal, Decimal, Decimal]:
    """返回 (最高, 最低, 区间涨跌百分比)。"""
    values = [item[1] for item in series]
    high, low = max(values), min(values)
    first, last = values[0], values[-1]
    change = (last - first) / first * Decimal(100) if first else Decimal(0)
    return high, low, change
