"""所有发给 Telegram 的文案都用 parse_mode=HTML，裸露的 < > 会导致整条消息发送失败。

这里把文案表和帮助文本里的合法标签剥掉后，断言不再残留尖括号。
"""

import re

import pytest

from bot.handlers.common import HELP_EN, HELP_ZH
from bot.i18n import EN, ZH
from bot.main import GROUP_COMMANDS, PRIVATE_COMMANDS

ALLOWED_TAG = re.compile(r"</?(?:b|strong|i|em|u|s|code|pre|a href=\"[^\"]*\")>")


def unsafe_angle_brackets(text: str) -> str:
    stripped = ALLOWED_TAG.sub("", text)
    # 占位符 {x} 展开后由调用方负责转义，这里只看模板本身
    leftovers = [ch for ch in stripped if ch in "<>"]
    return "".join(leftovers)


@pytest.mark.parametrize("table_name,table", [("ZH", ZH), ("EN", EN)])
def test_i18n_templates_are_html_safe(table_name, table):
    offenders = {key: unsafe_angle_brackets(value) for key, value in table.items()}
    offenders = {k: v for k, v in offenders.items() if v}
    assert not offenders, f"{table_name} 中这些文案有裸尖括号: {offenders}"


@pytest.mark.parametrize("name,text", [("HELP_ZH", HELP_ZH), ("HELP_EN", HELP_EN)])
def test_help_text_is_html_safe(name, text):
    assert not unsafe_angle_brackets(text), f"{name} 里有裸尖括号"


def test_both_language_tables_have_the_same_keys():
    assert set(ZH) == set(EN)


def test_command_menus_are_within_telegram_limits():
    for menu in (PRIVATE_COMMANDS, GROUP_COMMANDS):
        assert len(menu) <= 100
        for command in menu:
            assert re.fullmatch(r"[a-z0-9_]{1,32}", command.command), command.command
            assert 1 <= len(command.description) <= 256
