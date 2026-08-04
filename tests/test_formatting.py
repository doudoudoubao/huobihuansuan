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
    assert fmt.fmt_rate(Decimal("157321.5"), prefs) == "157,321.50"


def test_tiny_rates_keep_four_significant_digits(prefs):
    """0.00000208474 全写出来反而看不清，收敛到 ~4 位有效数字。"""
    assert fmt.fmt_rate(Decimal("0.0000208474"), prefs) == "0.00002085"
    assert fmt.fmt_rate(Decimal("0.00000208474"), prefs) == "0.000002085"
    assert fmt.fmt_rate(Decimal("0.1380623"), prefs) == "0.1381"


def test_input_amount_drops_trailing_zeros(prefs):
    """回显用户输入的金额时，100 就是 100，不该显示成 100.00。"""
    assert fmt.fmt_input_amount(Decimal(100), "CNY", prefs) == "100"
    assert fmt.fmt_input_amount(Decimal("100.5"), "CNY", prefs) == "100.5"
    assert fmt.fmt_input_amount(Decimal("35000"), "USD", prefs) == "35,000"
    assert fmt.fmt_input_amount(Decimal("0.5"), "BTC", prefs) == "0.5"


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


# --- 页脚：区分「每日源」和「真的卡住了」 -----------------------------------


def _rate(**kwargs):
    from bot.rates.service import RateInfo
    import time as _t

    defaults = dict(
        base="EUR", quote="CNY", value=Decimal("8.98"),
        as_of=_t.time(), sources=("yahoo",), fetched_at=_t.time(),
        cadence="realtime", stale=False,
    )
    return RateInfo(**{**defaults, **kwargs})


def test_daily_source_footer_is_informative_not_alarming(prefs):
    """欧洲央行一天一更，报价是昨天的属于正常，不该挂警告。"""
    import time as _t

    footer = fmt._footer(
        _rate(sources=("frankfurter",), cadence="daily", as_of=_t.time() - 86_400), prefs
    )
    assert "⚠️" not in footer
    assert "每日更新" in footer and "昨日" in footer
    assert "frankfurter" in footer


def test_realtime_source_footer_shows_age(prefs):
    footer = fmt._footer(_rate(), prefs)
    assert "📡" in footer and "yahoo" in footer
    assert "⚠️" not in footer


def test_stale_footer_reports_fetch_gap(prefs):
    """真出问题时才警告，且说的是「多久没刷新成功」而不是「报价多老」。"""
    import time as _t

    footer = fmt._footer(_rate(stale=True, fetched_at=_t.time() - 4 * 3600), prefs)
    assert "⚠️" in footer
    assert "4 小时" in footer
    assert footer.count("⚠️") == 1     # 以前模板和页脚各加一个，出现过双警告


def test_footer_respects_show_source_toggle(prefs):
    prefs.show_source = False
    assert "yahoo" not in fmt._footer(_rate(), prefs)
    assert "frankfurter" not in fmt._footer(_rate(sources=("frankfurter",), cadence="daily"), prefs)


def test_duration_has_no_ago_suffix():
    assert fmt.fmt_duration(4 * 3600, "zh") == "4 小时"
    assert fmt.fmt_duration(2 * 86400, "zh") == "2 天"
    assert "前" not in fmt.fmt_duration(90, "zh")
    assert fmt.fmt_duration(4 * 3600, "en") == "4h"


def test_quote_day_wording():
    import time as _t

    assert fmt.fmt_quote_day(_t.time(), "zh") == "今日"
    assert fmt.fmt_quote_day(_t.time() - 86_400, "zh") == "昨日"
    assert "月" in fmt.fmt_quote_day(_t.time() - 5 * 86_400, "zh")
    assert fmt.fmt_quote_day(_t.time() - 86_400, "en") == "yesterday"
