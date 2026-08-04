"""终端输出的排版与着色。

两件事容易做错，这里统一处理掉：

1. **对齐**：中文一个字占两列，`str.ljust()` 按字符数算，中英混排必然错位。
   这里按「显示宽度」补空格。
2. **颜色**：只在真正的 tty 上着色；重定向到文件、CI 日志或设了 NO_COLOR
   时自动退化成纯文本，不留一堆转义序列。
"""

from __future__ import annotations

import os
import sys
import unicodedata

RESET = "\033[0m"
CODES = {
    "green": "\033[32m",
    "yellow": "\033[33m",
    "red": "\033[31m",
    "cyan": "\033[36m",
    "dim": "\033[2m",
    "bold": "\033[1m",
}


def supports_color(stream: object = None) -> bool:
    if os.getenv("NO_COLOR") is not None:
        return False
    if os.getenv("FORCE_COLOR"):
        return True
    stream = stream or sys.stdout
    try:
        return bool(stream.isatty())  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        return False


_COLOR = supports_color()


def paint(text: str, *styles: str) -> str:
    """给文本加颜色；终端不支持时原样返回。"""
    if not _COLOR or not styles:
        return text
    prefix = "".join(CODES[s] for s in styles if s in CODES)
    return f"{prefix}{text}{RESET}" if prefix else text


def display_width(text: str) -> int:
    """字符串在等宽终端里占几列。全角/宽字符算 2 列。"""
    width = 0
    for char in text:
        if unicodedata.combining(char):
            continue
        width += 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
    return width


def pad(text: str, width: int, *, align: str = "left") -> str:
    """按显示宽度补空格，中英混排也能对齐。"""
    filler = " " * max(0, width - display_width(text))
    if align == "right":
        return filler + text
    return text + filler


def rule(width: int = 44, char: str = "─") -> str:
    return paint(char * width, "dim")


class Report:
    """自检报告的输出器：状态列固定宽度，标签按显示宽度对齐。"""

    MARKS = {
        "ok": ("✓", "green"),
        "warn": ("!", "yellow"),
        "fail": ("✗", "red"),
    }

    def __init__(self, title: str, label_width: int = 10) -> None:
        self.label_width = label_width
        print()
        print("  " + paint(title, "bold"))
        print("  " + rule())

    def line(self, status: str, label: str, detail: str = "") -> None:
        mark, color = self.MARKS.get(status, ("·", "dim"))
        print(f"  {paint(mark, color)}  {pad(label, self.label_width)}{detail}")

    def detail(self, text: str, *, indent: int = 6, style: str = "dim") -> None:
        """挂在某一项下面的补充行，例如失败原因。"""
        for row in str(text).split("\n"):
            print(" " * indent + paint(row.strip(), style))

    def item(self, status: str, name: str, detail: str = "", name_width: int = 14) -> None:
        """列表项，例如逐个数据源。圆点用同宽字符，任何终端下都对得齐。"""
        bullet, color = {"ok": ("●", "green"), "warn": ("○", "yellow"), "fail": ("✗", "red")}.get(
            status, ("·", "dim")
        )
        print(f"      {paint(bullet, color)} {pad(name, name_width)}{detail}")

    def verdict(self, status: str, text: str) -> None:
        """小结行：跟在一串列表项后面，用连接线和上面的清单区分开。"""
        color = {"ok": "green", "warn": "yellow", "fail": "red"}.get(status, "dim")
        print(f"      {paint('└', 'dim')} {paint(text, color)}")

    def close(self, status: str, message: str) -> None:
        color = {"ok": "green", "warn": "yellow", "fail": "red"}.get(status, "dim")
        print("  " + rule())
        print("  " + paint(message, color, "bold"))
        print()
