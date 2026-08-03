from decimal import Decimal

import pytest

from bot.parser import evaluate, parse, parse_currency_list, parse_pair


def p(text: str, context: str | None = "CNY"):
    return parse(text, context_currency=context)


@pytest.mark.parametrize(
    "text,amount,source,targets",
    [
        ("100 usd cny", "100", "USD", ["CNY"]),
        ("100usd cny", "100", "USD", ["CNY"]),
        ("100 美元 人民币", "100", "USD", ["CNY"]),
        ("100美元换人民币", "100", "USD", ["CNY"]),
        ("100刀多少人民币", "100", "USD", ["CNY"]),
        ("1000円是多少钱", "1000", "JPY", []),
        ("100 usd to cny", "100", "USD", ["CNY"]),
        ("帮我算下 300 港币等于多少人民币", "300", "HKD", ["CNY"]),
        ("100 usd cny jpy krw", "100", "USD", ["CNY", "JPY", "KRW"]),
        ("usd cny", "1", "USD", ["CNY"]),
        ("0.5 btc cny", "0.5", "BTC", ["CNY"]),
        ("100块 日元", "100", "CNY", ["JPY"]),
        ("100 usd = ? jpy", "100", "USD", ["JPY"]),
        ("2w u cny", "20000", "USDT", ["CNY"]),
    ],
)
def test_basic_forms(text, amount, source, targets):
    result = p(text)
    assert result.error is None
    assert result.amount == Decimal(amount)
    assert result.source == source
    assert result.targets == targets


def test_symbols_and_flags():
    assert p("$100").source == "USD"
    assert p("￥500 美元").source == "CNY"
    assert p("🇯🇵1000 cny").source == "JPY"
    # ¥ 有歧义：跟着用户默认币种走
    assert p("¥100", context="JPY").source == "JPY"
    assert p("¥100", context="CNY").source == "CNY"


def test_math_expressions():
    assert p("(23.5+40)*3 eur cny").amount == Decimal("190.5")
    assert p("99.9*12 usd").amount == Decimal("1198.8")
    assert p("100-50 usd cny").amount == Decimal(50)
    assert p("1,234.56 eur cny").amount == Decimal("1234.56")
    assert p("1,000,000 jpy cny").amount == Decimal(1000000)


def test_magnitude_suffixes():
    assert p("1.5k usd jpy").amount == Decimal(1500)
    assert p("10万日元 人民币").amount == Decimal(100000)
    assert p("3.5万美元 人民币").amount == Decimal(35000)
    assert p("2亿 越南盾 人民币").amount == Decimal(200000000)


def test_fee_extraction():
    assert p("100 usd cny +2%").fee_percent == Decimal(2)
    assert p("100 usd cny -0.5%").fee_percent == Decimal("-0.5")
    assert p("100 usd cny 手续费1.5%").fee_percent == Decimal("1.5")
    assert p("100 usd cny fee 3%").fee_percent == Decimal(3)
    assert p("100 usd cny").fee_percent is None


def test_amount_only_and_unknown():
    bare = p("100")
    assert bare.source is None
    assert bare.has_explicit_amount
    assert bare.is_actionable

    unknown = p("abcdef")
    assert unknown.error == "no_match"
    assert unknown.unknown_tokens == ["abcdef"]

    assert p("").error == "empty"
    assert p("x" * 600).error == "too_long"


def test_expression_evaluator_is_sandboxed():
    assert evaluate("2+3*4") == Decimal(14)
    assert evaluate("__import__('os').system('ls')") is None
    assert evaluate("open('/etc/passwd')") is None
    assert evaluate("1/0") is None
    assert evaluate("2**999") is None
    assert evaluate("") is None


def test_currency_list_and_pair():
    assert parse_currency_list("usd eur jpy usd") == ["USD", "EUR", "JPY"]
    assert parse_pair("usd cny", default_source="EUR", default_target="GBP") == ("USD", "CNY")
    assert parse_pair("usd", default_source="EUR", default_target="GBP") == ("USD", "GBP")
    assert parse_pair("", default_source="EUR", default_target="GBP") == ("EUR", "GBP")
    # 只给一个币种且它就是默认目标时，回退到默认源币种，避免自己换自己
    assert parse_pair("gbp", default_source="EUR", default_target="GBP") == ("GBP", "EUR")


def test_duplicates_are_collapsed():
    result = p("100 usd cny cny usd")
    assert result.source == "USD"
    assert result.targets == ["CNY"]
