"""终端排版：中英混排的对齐，以及非 tty 下不要吐转义序列。"""

import io

from bot import console


def test_display_width_counts_cjk_as_two_columns():
    assert console.display_width("abc") == 3
    assert console.display_width("汇率源") == 6
    assert console.display_width("Telegram") == 8
    assert console.display_width("") == 0
    # 中英混排是真正会出错的地方
    assert console.display_width("数据源 yahoo") == 6 + 1 + 5


def test_pad_aligns_mixed_scripts():
    """str.ljust 按字符数算，中文会短一半——这正是原来错位的原因。"""
    labels = ["配置", "数据库", "Telegram", "汇率源", "试算"]
    padded = [console.pad(label, 10) for label in labels]
    assert len({console.display_width(p) for p in padded}) == 1
    # 对照：内置的 ljust 在这里是对不齐的
    assert len({console.display_width(label.ljust(10)) for label in labels}) > 1


def test_pad_right_alignment():
    assert console.pad("31", 5, align="right") == "   31"
    assert console.pad("163", 5, align="right") == "  163"


def test_pad_never_truncates():
    assert console.pad("很长很长的一段文字", 3).startswith("很长")


def test_paint_is_a_noop_without_color(monkeypatch):
    monkeypatch.setattr(console, "_COLOR", False)
    assert console.paint("hello", "green") == "hello"


def test_paint_wraps_with_reset(monkeypatch):
    monkeypatch.setattr(console, "_COLOR", True)
    painted = console.paint("hello", "green")
    assert painted.startswith("\033[32m") and painted.endswith(console.RESET)


def test_no_color_env_disables_color(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    assert console.supports_color() is False


def test_non_tty_disables_color(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    assert console.supports_color(io.StringIO()) is False


def test_report_columns_line_up(monkeypatch, capsys):
    monkeypatch.setattr(console, "_COLOR", False)
    report = console.Report("自检")
    report.line("ok", "配置", "正常")
    report.line("ok", "Telegram", "已登录")
    report.line("fail", "汇率源", "全挂了")
    out = capsys.readouterr().out.split("\n")

    detail_starts = [
        console.display_width(line[: line.index(word)])
        for line, word in zip(out[3:6], ("正常", "已登录", "全挂了"))
    ]
    assert len(set(detail_starts)) == 1, out


def test_report_items_and_verdicts(monkeypatch, capsys):
    monkeypatch.setattr(console, "_COLOR", False)
    report = console.Report("自检")
    report.item("ok", "binance", "31 种")
    report.item("warn", "coingecko", "限流")
    report.item("fail", "okx", "挂了")
    report.verdict("ok", "加密 → binance")
    out = capsys.readouterr().out
    assert "● binance" in out
    assert "○ coingecko" in out
    assert "✗ okx" in out          # 失败用叉，和「有备用」的空心圆区分开
    assert "└ 加密 → binance" in out


def test_report_detail_indents_multiline(monkeypatch, capsys):
    monkeypatch.setattr(console, "_COLOR", False)
    report = console.Report("自检")
    report.detail("第一行\n  第二行")
    lines = [line for line in capsys.readouterr().out.split("\n") if "行" in line]
    assert all(line.startswith("      ") for line in lines)
    assert not any(line.strip().startswith(" ") for line in lines)
