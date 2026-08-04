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
