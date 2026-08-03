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
