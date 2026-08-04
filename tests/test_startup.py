"""启动期的配置校验与错误提示。"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from bot.config import Config, StartupError
from bot.main import build_bot

GOOD_TOKEN = "123456789:AAEhBOweik6ad9r_wAbCdEfGhIjKlMnOpQr"
REPO_ROOT = Path(__file__).resolve().parent.parent


def test_missing_token_is_explained(tmp_path):
    cfg = Config(bot_token="", db_path=str(tmp_path / "b.db"))
    with pytest.raises(StartupError) as excinfo:
        cfg.validate()
    assert "BotFather" in str(excinfo.value)


@pytest.mark.parametrize(
    "bad",
    ["notarealtoken", "123456789", ":AAEhBOweik", "123:short", '"123456789:AAEhBOweik6ad9r_wAbCdEfGhIjKlM"'],
)
def test_malformed_token_is_rejected(tmp_path, bad):
    cfg = Config(bot_token=bad, db_path=str(tmp_path / "b.db"))
    with pytest.raises(StartupError, match="格式"):
        cfg.validate()


def test_valid_token_creates_data_dir(tmp_path):
    target = tmp_path / "nested" / "deeper" / "bot.db"
    cfg = Config(bot_token=GOOD_TOKEN, db_path=str(target))
    cfg.validate()
    assert target.parent.is_dir()


def test_build_bot_without_proxy(tmp_path):
    cfg = Config(bot_token=GOOD_TOKEN, db_path=str(tmp_path / "b.db"), telegram_proxy="")
    bot = build_bot(cfg)
    assert bot.token == GOOD_TOKEN


def test_cli_reports_missing_token_and_exits_nonzero(tmp_path):
    """最容易踩的第一步：没填 token 时必须给出人话，而不是静默退出。"""
    env = dict(os.environ)
    env.pop("BOT_TOKEN", None)
    env["DB_PATH"] = str(tmp_path / "bot.db")
    proc = subprocess.run(
        [sys.executable, "run.py"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 1
    assert "BOT_TOKEN" in proc.stderr
    assert "BotFather" in proc.stderr


# --- 数据源诊断 ---------------------------------------------------------------


def _row(name, kind, priority, currencies, error=""):
    return {
        "name": name, "kind": kind, "priority": priority,
        "currencies": currencies, "error": error, "healthy": bool(currencies), "age": 0,
    }


def _all_up():
    return [
        _row("yahoo", "mixed", 10, 22),
        _row("binance", "crypto", 10, 31),
        _row("okx", "crypto", 20, 28),
        _row("frankfurter", "fiat", 30, 31),
        _row("open-er-api", "fiat", 40, 163),
        _row("coingecko", "crypto", 40, 30),
        _row("currency-api", "mixed", 50, 140),
    ]


def _kill(rows, *names, error="连接超时"):
    return [
        _row(r["name"], r["kind"], r["priority"], 0, error) if r["name"] in names else r
        for r in rows
    ]


def test_everything_healthy():
    from bot.main import diagnose_providers

    lines, all_ok, degraded = diagnose_providers(_all_up())
    assert all_ok and not degraded
    assert any("法币主力 yahoo，准实时" in line for line in lines)
    assert any("加密主力 binance，准实时" in line for line in lines)


def test_rate_limited_backup_is_only_a_warning():
    """coingecko 是加密的第 3 备胎，被限流不该让自检失败。"""
    from bot.main import diagnose_providers

    rows = _kill(_all_up(), "coingecko", error="api.coingecko.com 请求过频被限流 (429)")
    lines, all_ok, degraded = diagnose_providers(rows)
    assert all_ok and not degraded
    assert any("🟡 coingecko" in line and "有其他源顶着" in line for line in lines)
    assert any("加密主力 binance" in line for line in lines)


def test_promotes_next_provider_when_primary_dies():
    from bot.main import diagnose_providers

    lines, all_ok, degraded = diagnose_providers(_kill(_all_up(), "binance"))
    assert all_ok and not degraded
    # yahoo 也是 mixed，会接手加密
    assert any("加密主力 yahoo" in line for line in lines)


def test_only_daily_sources_left_is_degraded():
    """还能跑，但「实时」没了——必须说出来，不能报「全部通过」。"""
    from bot.main import diagnose_providers

    rows = _kill(_all_up(), "yahoo", "binance", "okx", "coingecko")
    lines, all_ok, degraded = diagnose_providers(rows)
    assert all_ok is True      # 两类都还有源
    assert degraded is True    # 但只剩每日更新的
    assert any("法币只剩每日更新的 frankfurter" in line for line in lines)
    assert any("加密只剩每日更新的 currency-api" in line for line in lines)


def test_whole_category_down_is_fatal():
    from bot.main import diagnose_providers

    rows = _kill(_all_up(), "yahoo", "binance", "okx", "coingecko", "currency-api")
    lines, all_ok, degraded = diagnose_providers(rows)
    assert all_ok is False and degraded is True
    assert any("加密报价无源可用" in line for line in lines)
    # 法币还活着，所以法币那几个不该被标成「没有源能接替」
    assert any("🟢 frankfurter" in line for line in lines)
    assert any("🔴 binance" in line and "没有源能接替" in line for line in lines)


def test_error_text_is_shortened():
    from bot.main import _short_error

    long_url = "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/x.json 超时"
    assert len(_short_error(long_url)) <= 53
    assert not _short_error(long_url).startswith("https://")
    assert _short_error("") == "无数据"
