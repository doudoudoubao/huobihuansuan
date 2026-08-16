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


# --- 算式 ---------------------------------------------------------------
# 这一组盯的都是「静默算错」：解析不报错，但金额是错的。
# 比报错危险得多 —— 用户看到一张正常的卡片，不会怀疑数字有问题。


@pytest.mark.parametrize(
    ("text", "amount"),
    [
        ("18*12 欧元 人民币", 216),
        ("18x12 欧元 人民币", 216),      # 键盘上的 x 当乘号
        ("18X12 eur cny", 216),
        ("18 x 12 eur cny", 216),       # 两边带空格
        ("18×12 欧元 人民币", 216),      # 真正的乘号
        ("100÷4 usd cny", 25),
        ("（10+2）×5 usd cny", 60),      # 全角括号
        ("(3+4)*2 usd cny", 14),
        ("12.5×3 美元 日元", "37.5"),
        ("2^10 usd cny", 1024),
    ],
)
def test_arithmetic_forms(text, amount):
    assert p(text).amount == Decimal(str(amount))


def test_x_is_only_a_times_sign_between_digits():
    """x 也是货币代码里的常用字母，不能见到就当乘号。"""
    assert p("1000 mxn cny").source == "MXN"
    assert p("5 xau usd").source == "XAU"
    # 只有一边是数字的残句，宁可当噪声忽略，也不能凭空多出一个乘号
    assert p("100 x usd cny").amount == Decimal(100)


@pytest.mark.parametrize(
    ("text", "amount"),
    [
        ("1万 usd cny", 10000),
        ("1万5 日元 人民币", 15000),      # 尾数落在次一级单位，不是 10005
        ("2万3 usd cny", 23000),
        ("2万3千 usd cny", 23000),
        ("1万2500 usd cny", 12500),      # 写全了的尾数就是它本身
        ("1亿2千万 日元 人民币", 120000000),  # 相邻量级段相加
        ("1百5 usd cny", 150),
        ("2.5万 usd cny", 25000),
        ("3千 usd cny", 3000),
        ("2万*3 usd cny", 60000),        # 量级和运算符混用
        ("1万5+500 usd cny", 15500),
    ],
)
def test_chinese_magnitudes(text, amount):
    assert p(text).amount == Decimal(str(amount))


def test_expression_is_echoed_only_when_something_was_computed():
    from bot.formatting import expression_hint

    assert expression_hint(p("18x12 eur cny").expression) == "  <i>(18*12)</i>"
    assert expression_hint(p("100 usd cny").expression) == ""


@pytest.mark.parametrize(
    ("text", "amount"),
    [
        ("100➗4 usd cny", 25),
        ("100除以4 usd cny", 25),
        ("100 除以 4 usd cny", 25),
        ("100除4 usd cny", 25),
        ("18乘以12 eur cny", 216),
        ("18乘12 eur cny", 216),
        ("100加50 usd cny", 150),
        ("100加上50 usd cny", 150),
        ("100减去20 usd cny", 80),
        ("100➕50 usd cny", 150),
        ("100➖20 usd cny", 80),
        ("18❌12 eur cny", 216),
        ("18✖️12 eur cny", 216),   # 表情后面跟着变体选择符 U+FE0F
        ("2万3加500 usd cny", 23500),  # 中文量级 + 中文运算词
    ],
)
def test_spoken_and_emoji_operators(text, amount):
    assert p(text).amount == Decimal(str(amount))


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("100加币", "CAD"),
        ("100 加元 人民币", "CAD"),
        ("100加拿大元 人民币", "CAD"),
        ("100新加坡元 人民币", "SGD"),
        ("1000新加坡币 cny", "SGD"),
    ],
)
def test_operator_words_never_split_a_currency_name(text, code):
    """「加」既是加号也是加元/新加坡元的一部分，货币名必须先赢。"""
    assert p(text).source == code
    assert p(text).amount in (Decimal(100), Decimal(1000))


def test_operator_word_needs_digits_on_both_sides():
    assert p("100加 usd cny").amount == Decimal(100)
