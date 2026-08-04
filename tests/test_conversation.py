"""端到端地跑一遍换算流程（不经过 Telegram，只验渲染与静默策略）。"""

from decimal import Decimal

import pytest

from bot.config import Config
from bot.db import UserPrefs
from bot.handlers.core import build_conversion, respond_to_text
from bot.rates.service import RateService

TABLE = {
    "USD": Decimal(1),
    "CNY": Decimal("7.24"),
    "JPY": Decimal(157),
    "EUR": Decimal("0.92"),
    "HKD": Decimal("7.81"),
    "GBP": Decimal("0.78"),
    "KRW": Decimal(1380),
    "BTC": Decimal("0.000015"),
}


@pytest.fixture()
def rates(tmp_path):
    service = RateService(Config(db_path=str(tmp_path / "t.db")))
    service.inject("stub", TABLE)
    return service


@pytest.fixture()
def prefs():
    return UserPrefs(user_id=1, lang="zh", base="CNY", favorites=["USD", "EUR", "JPY"], decimals=2)


async def test_single_pair_card(prefs, rates):
    rendered = await respond_to_text("100 usd cny", prefs, rates)
    assert rendered.ok
    assert "724.00" in rendered.text
    assert "1 USD = 7.24 CNY" in rendered.text
    assert rendered.keyboard is not None


async def test_bare_amount_uses_defaults(prefs, rates):
    rendered = await respond_to_text("100", prefs, rates)
    assert rendered.ok
    # 默认币种 CNY 换成收藏的 USD/EUR/JPY
    for code in ("USD", "EUR", "JPY"):
        assert code in rendered.text


async def test_fee_reduces_result(prefs, rates):
    plain = await respond_to_text("100 usd cny", prefs, rates)
    with_fee = await respond_to_text("100 usd cny +2%", prefs, rates)
    assert "724.00" in plain.text
    assert "709.52" in with_fee.text
    assert "手续费" in with_fee.text


async def test_same_currency_is_rejected(prefs, rates):
    rendered = await build_conversion(Decimal(1), "USD", ["USD"], prefs, rates)
    assert rendered.ok is False
    assert "USD" in rendered.text


async def test_unknown_input_gets_a_hint_in_private(prefs, rates):
    rendered = await respond_to_text("blahblah", prefs, rates)
    assert rendered is not None
    assert rendered.ok is False


async def test_group_stays_silent_without_a_target(prefs, rates):
    """群里的闲聊不该被接话。"""
    for chatter in ("我昨天花了100块", "100", "谁有usd", "hello"):
        assert (
            await respond_to_text(
                chatter, prefs, rates, quiet=True, require_currency=True, require_target=True
            )
            is None
        )


async def test_group_answers_explicit_conversion(prefs, rates):
    rendered = await respond_to_text(
        "100 美元 人民币", prefs, rates, quiet=True, require_currency=True, require_target=True
    )
    assert rendered is not None and rendered.ok
    assert "724.00" in rendered.text


async def test_missing_quote_is_reported(prefs, rates):
    rendered = await build_conversion(Decimal(1), "USD", ["ZZZ"], prefs, rates)
    assert rendered.ok is False
    assert "ZZZ" in rendered.text


async def test_partial_missing_quotes_still_render(prefs, rates):
    rendered = await build_conversion(Decimal(100), "USD", ["CNY", "ZZZ", "JPY"], prefs, rates)
    assert rendered.ok
    assert "CNY" in rendered.text and "JPY" in rendered.text
    assert "ZZZ" in rendered.text  # 缺的那个会单独提示


async def test_crypto_precision(prefs, rates):
    rendered = await respond_to_text("1000 cny btc", prefs, rates)
    assert rendered.ok
    assert "0.00207" in rendered.text  # 1000 / 7.24 * 0.000015


async def test_zero_decimal_currency(prefs, rates):
    rendered = await respond_to_text("100 usd jpy", prefs, rates)
    assert "15,700" in rendered.text


# --- 排版 ---------------------------------------------------------------------


def _code_cells(text: str) -> list[str]:
    import re

    return re.findall(r"<code>(.*?)</code>", text)


async def test_multi_list_columns_are_aligned(prefs, rates):
    """对齐的前提：代码和数值必须在同一个 <code> 里，且每行等宽。

    以前数值在 <code> 外面用 <b> 渲染（比例字体），列根本对不齐。
    """
    rendered = await respond_to_text("100", prefs, rates)
    cells = _code_cells(rendered.text)
    assert len(cells) >= 3
    assert len({len(cell) for cell in cells}) == 1, cells  # 每行等宽
    for cell in cells:
        assert cell.endswith(cell.strip()[-1])   # 数值右对齐，右边没有多余空格
        assert cell[:3].strip() == cell[:3]      # 代码左对齐


async def test_multi_list_right_aligns_wide_numbers(prefs, rates):
    rendered = await build_conversion(Decimal(35000), "USD", ["CNY", "JPY", "KRW"], prefs, rates)
    cells = _code_cells(rendered.text)
    assert len({len(cell) for cell in cells}) == 1
    # 最长的那个数值应该顶到最右边，短的靠空格补齐
    assert all(not cell.endswith(" ") for cell in cells)


async def test_header_shows_plain_integer(prefs, rates):
    rendered = await respond_to_text("100 usd cny", prefs, rates)
    assert "100 USD" in rendered.text
    assert "100.00 USD" not in rendered.text   # 输入是整数就别加 .00


async def test_only_the_result_is_bold(prefs, rates):
    """单对卡的视觉焦点只有一个：换算结果。"""
    rendered = await respond_to_text("100 usd cny", prefs, rates)
    import re

    bolds = re.findall(r"<b>(.*?)</b>", rendered.text)
    assert bolds == ["724.00 CNY"]


async def test_card_has_a_footer_rule(prefs, rates):
    from bot.formatting import RULE

    rendered = await respond_to_text("100 usd cny", prefs, rates)
    assert RULE in rendered.text
    assert rendered.text.rstrip().endswith("</i>")   # 页脚是最后一行


# --- 货币中文名 ---------------------------------------------------------------


async def test_names_are_shown_by_default(prefs, rates):
    prefs.show_names = True
    rendered = await respond_to_text("100", prefs, rates)
    for name in ("美元", "欧元", "日元"):
        assert name in rendered.text


async def test_names_sit_outside_the_code_block(prefs, rates):
    """中文在等宽字体里的宽度各客户端不一，塞进 <code> 会把数字列顶歪。"""
    prefs.show_names = True
    rendered = await respond_to_text("100", prefs, rates)
    for cell in _code_cells(rendered.text):
        assert not any("一" <= ch <= "鿿" for ch in cell), cell


async def test_names_do_not_break_alignment(prefs, rates):
    prefs.show_names = True
    rendered = await respond_to_text("100", prefs, rates)
    cells = _code_cells(rendered.text)
    assert len({len(cell) for cell in cells}) == 1, cells


async def test_names_can_be_turned_off(prefs, rates):
    prefs.show_names = False
    rendered = await respond_to_text("100", prefs, rates)
    assert "美元" not in rendered.text
    assert "USD" in rendered.text


async def test_single_card_names_both_sides(prefs, rates):
    prefs.show_names = True
    rendered = await respond_to_text("100 usd cny", prefs, rates)
    assert "美元" in rendered.text and "人民币" in rendered.text


async def test_english_locale_uses_english_names(prefs, rates):
    prefs.lang = "en"
    prefs.show_names = True
    rendered = await respond_to_text("100 usd cny", prefs, rates)
    assert "US Dollar" in rendered.text and "Chinese Yuan" in rendered.text
    assert "美元" not in rendered.text
