from decimal import Decimal

import pytest

from bot import currencies as cur_mod
from bot import formatting as fmt
from bot.db import UserPrefs


@pytest.fixture()
def prefs():
    return UserPrefs(user_id=1, lang="zh", base="CNY", favorites=["USD", "EUR", "JPY"], decimals=2)


def test_group_separator_and_decimals(prefs):
    assert fmt.fmt_money(Decimal("1234567.891"), "CNY", prefs) == "1,234,567.89"
    prefs.group_sep = False
    assert fmt.fmt_money(Decimal("1234567.891"), "CNY", prefs) == "1234567.89"


def test_zero_decimal_currencies(prefs):
    assert fmt.fmt_money(Decimal("15000.4"), "JPY", prefs) == "15,000"
    assert fmt.fmt_money(Decimal("15000.6"), "KRW", prefs) == "15,001"


def test_small_amounts_get_more_precision(prefs):
    assert fmt.fmt_money(Decimal("0.00001473"), "BTC", prefs) == "0.00001473"
    assert fmt.fmt_money(Decimal("0.5"), "BTC", prefs) == "0.50"


def test_rate_precision(prefs):
    assert fmt.fmt_rate(Decimal("7.24315"), prefs) == "7.2432"
    assert fmt.fmt_rate(Decimal("0.0000208474"), prefs) == "0.0000208474"
    assert fmt.fmt_rate(Decimal("157321.5"), prefs) == "157,321.50"


def test_expression_hint_only_for_real_math():
    assert fmt.expression_hint("100") == ""
    assert fmt.expression_hint("1,234.56") == ""
    assert fmt.expression_hint(None) == ""
    assert "(23.5+40)*3" in fmt.expression_hint("(23.5+40)*3")


def test_ago_wording():
    assert fmt.fmt_ago(3, "zh") == "刚刚"
    assert fmt.fmt_ago(90, "zh") == "1 分钟前"
    assert fmt.fmt_ago(7200, "en") == "2h ago"


def test_html_escaping():
    assert fmt.esc("<script>") == "&lt;script&gt;"


def test_change_arrow():
    assert "▲" in fmt.fmt_change(Decimal("1.5"), "zh")
    assert "▼" in fmt.fmt_change(Decimal("-1.5"), "zh")
    assert fmt.fmt_change(None, "zh") == ""


def test_targets_for_excludes_source(prefs):
    targets = prefs.targets_for("USD")
    assert "USD" not in targets
    assert targets[0] == "CNY"  # 默认币种排最前


def test_currency_resolution():
    assert cur_mod.resolve_code("美元") == "USD"
    assert cur_mod.resolve_code("软妹币") == "CNY"
    assert cur_mod.resolve_code("USDT") == "USDT"
    assert cur_mod.resolve_code("u") == "USDT"
    assert cur_mod.resolve_code("quid") == "GBP"
    assert cur_mod.resolve_code("nonexistent") is None
    assert cur_mod.get("ZZZ").code == "ZZZ"  # 未知代码不抛异常


def test_search_ranking():
    codes = [c.code for c in cur_mod.search("韩")]
    assert "KRW" in codes
    assert [c.code for c in cur_mod.search("usd")][0] == "USD"
