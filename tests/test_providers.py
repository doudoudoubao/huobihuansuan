"""用录制的响应体验证各数据源的解析逻辑（不联网）。"""

from decimal import Decimal

import pytest

from bot.rates.base import HttpClient, ProviderError
from bot.rates.providers import (
    BinanceProvider,
    CoinGeckoProvider,
    CurrencyApiProvider,
    FrankfurterProvider,
    OkxProvider,
    OpenErApiProvider,
    YahooFinanceProvider,
)


class StubHttp(HttpClient):
    """按 URL 前缀返回预置 JSON 的假 HTTP 客户端。"""

    def __init__(self, routes: dict[str, object]) -> None:
        super().__init__()
        self.routes = routes
        self.calls: list[str] = []

    async def get_json(self, url, *, params=None, retries=2, headers=None):  # type: ignore[override]
        self.calls.append(url)
        for prefix, payload in self.routes.items():
            if prefix in url:
                if isinstance(payload, Exception):
                    raise payload
                return payload
        raise ProviderError(f"no stub for {url}")


async def test_frankfurter_parses_ecb_payload():
    http = StubHttp(
        {"frankfurter": {"amount": 1.0, "base": "USD", "date": "2026-08-03",
                         "rates": {"CNY": 7.21, "EUR": 0.92, "JPY": 150.5, "GBP": 0.78, "AUD": 1.5}}}
    )
    result = await FrankfurterProvider(http).fetch()
    assert result.quotes["CNY"] == Decimal("7.21")
    assert result.quotes["USD"] == Decimal(1)  # 基准货币要自己补上


async def test_frankfurter_falls_back_to_second_host():
    http = StubHttp(
        {
            "api.frankfurter.app": ProviderError("down"),
            "api.frankfurter.dev": {"date": "2026-08-03", "rates": {"CNY": 7.2, "EUR": 0.9, "JPY": 150, "GBP": 0.8, "AUD": 1.5}},
        }
    )
    result = await FrankfurterProvider(http).fetch()
    assert result.quotes["CNY"] == Decimal("7.2")
    assert len(http.calls) == 2


async def test_frankfurter_history():
    http = StubHttp(
        {"frankfurter": {"rates": {"2026-08-01": {"CNY": 7.20}, "2026-08-02": {"CNY": 7.22}}}}
    )
    series = await FrankfurterProvider(http).history("USD", "CNY", 7)
    assert [v for _, v in series] == [Decimal("7.2"), Decimal("7.22")]
    assert series[0][0].isoformat() == "2026-08-01"


async def test_open_er_api():
    http = StubHttp(
        {
            "open.er-api.com": {
                "result": "success",
                "time_last_update_unix": 1_700_000_000,
                "rates": {f"C{i:02d}": 1.0 + i for i in range(25)} | {"CNY": 7.19},
            }
        }
    )
    result = await OpenErApiProvider(http).fetch()
    assert result.quotes["CNY"] == Decimal("7.19")
    assert result.as_of == 1_700_000_000


async def test_open_er_api_reports_error_result():
    http = StubHttp({"open.er-api.com": {"result": "error", "error-type": "invalid-key"}})
    with pytest.raises(ProviderError, match="invalid-key"):
        await OpenErApiProvider(http).fetch()


async def test_currency_api_filters_unknown_codes():
    payload = {"date": "2026-08-03", "usd": {"cny": 7.2, "jpy": 150.0, "btc": 0.000015,
                                             "xau": 0.0004, "madeupcoin": 12.0}}
    payload["usd"].update(
        {code.lower(): 1.5 for code in
         ("EUR", "GBP", "HKD", "KRW", "TWD", "SGD", "AUD", "CAD", "CHF", "NZD",
          "THB", "VND", "MYR", "IDR", "PHP", "INR", "RUB", "BRL", "MXN", "ZAR")}
    )
    http = StubHttp({"currency-api": payload, "currency-api.pages.dev": payload})
    result = await CurrencyApiProvider(http).fetch()
    assert result.quotes["CNY"] == Decimal("7.2")
    assert result.quotes["BTC"] == Decimal("0.000015")
    assert "MADEUPCOIN" not in result.quotes  # 未知代码被丢弃


async def test_binance_inverts_prices():
    http = StubHttp(
        {
            "binance": [
                {"symbol": "BTCUSDT", "price": "50000.00"},
                {"symbol": "ETHUSDT", "price": "2500.00"},
                {"symbol": "SOLUSDT", "price": "100.00"},
                {"symbol": "FOOBARUSDT", "price": "1.00"},
                {"symbol": "ETHBTC", "price": "0.05"},
            ]
        }
    )
    result = await BinanceProvider(http).fetch()
    # 表里存的是「1 USD 能买多少个币」
    assert result.quotes["BTC"] == Decimal(1) / Decimal("50000.00")
    assert result.quotes["ETH"] == Decimal(1) / Decimal("2500.00")
    assert "FOOBAR" not in result.quotes
    assert result.quotes["USDT"] == Decimal(1)


async def test_binance_history_inverts_for_usd_base():
    http = StubHttp({"klines": [[1_700_000_000_000, "1", "2", "3", "50000", "0"]]})
    series = await BinanceProvider(http).history("USD", "BTC", 30)
    assert series[0][1] == Decimal(1) / Decimal("50000")


async def test_okx():
    http = StubHttp(
        {
            "okx.com": {
                "code": "0",
                "data": [
                    {"instId": "BTC-USDT", "last": "50000"},
                    {"instId": "ETH-USDT", "last": "2500"},
                    {"instId": "SOL-USDT", "last": "100"},
                    {"instId": "BTC-USDC", "last": "50001"},
                ],
            }
        }
    )
    result = await OkxProvider(http).fetch()
    assert result.quotes["BTC"] == Decimal(1) / Decimal("50000")
    assert len(result.quotes) == 5  # BTC/ETH/SOL + USD + USDT


async def test_coingecko_maps_ids():
    http = StubHttp({"coingecko": {"bitcoin": {"usd": 50000}, "ethereum": {"usd": 2500}}})
    result = await CoinGeckoProvider(http).fetch()
    assert result.quotes["BTC"] == Decimal(1) / Decimal("50000")
    assert result.quotes["ETH"] == Decimal(1) / Decimal("2500")


async def test_yahoo_symbol_mapping():
    assert YahooFinanceProvider.symbol_for("CNY") == "CNY=X"
    assert YahooFinanceProvider.symbol_for("BTC") == "BTC-USD"
    assert YahooFinanceProvider.symbol_for("USD") == ""


async def test_yahoo_fetch_inverts_crypto():
    http = StubHttp(
        {
            "CNY=X": {"chart": {"result": [{"meta": {"regularMarketPrice": 7.23}}]}},
            "BTC-USD": {"chart": {"result": [{"meta": {"regularMarketPrice": 50000}}]}},
            "JPY=X": {"chart": {"result": [{"meta": {"regularMarketPrice": 151.2}}]}},
        }
    )
    provider = YahooFinanceProvider(http, hot_set=["CNY", "BTC", "JPY"])
    result = await provider.fetch()
    assert result.quotes["CNY"] == Decimal("7.23")
    assert result.quotes["JPY"] == Decimal("151.2")
    assert result.quotes["BTC"] == Decimal(1) / Decimal("50000")


async def test_yahoo_history_dedupes_by_day():
    http = StubHttp(
        {
            "CNY=X": {
                "chart": {
                    "result": [
                        {
                            "timestamp": [1_700_000_000, 1_700_003_600, 1_700_090_000],
                            "indicators": {"quote": [{"close": [7.1, 7.15, 7.2]}]},
                        }
                    ]
                }
            }
        }
    )
    series = await YahooFinanceProvider(http).history("USD", "CNY", 5)
    assert len(series) == 2  # 同一天只保留最后一个点
    assert series[-1][1] == Decimal("7.2")


async def test_provider_backoff_grows():
    provider = FrankfurterProvider(StubHttp({}))
    assert provider.backoff_seconds == 0
    provider.mark_failure("boom")
    first = provider.backoff_seconds
    provider.mark_failure("boom")
    assert provider.backoff_seconds > first
    assert provider.healthy is True
    provider.mark_failure("boom")
    assert provider.healthy is False
    provider.mark_success()
    assert provider.healthy is True and provider.backoff_seconds == 0


# --- Yahoo 的限速策略 ---------------------------------------------------------
#
# 线上实测：单发一次稳定 200，紧接着连发就吃 429。原来的实现 8 并发一次性
# 拉 24 个符号、失败还换个 host 再打一遍，等于自己把自己打成限流，
# 结果整个 provider 常年「无可用报价」。下面这组用例盯住修好的节奏。


class CountingHttp(HttpClient):
    """记录每次请求，可指定第 N 次之后开始返回 429。"""

    def __init__(self, price: float = 7.2, fail_after: int | None = None) -> None:
        super().__init__()
        self.calls: list[str] = []
        self.price = price
        self.fail_after = fail_after

    async def get_json(self, url, *, params=None, retries=2, headers=None):  # type: ignore[override]
        self.calls.append(url)
        if self.fail_after is not None and len(self.calls) > self.fail_after:
            raise ProviderError("query1.finance.yahoo.com 请求过频被限流 (429)")
        return {"chart": {"result": [{"meta": {"regularMarketPrice": self.price}}]}}


def _many_codes(n: int = 20) -> list[str]:
    from bot import currencies as cur_mod

    return [c for c in cur_mod.FILLER if c != "USD"][:n]


async def test_only_a_batch_is_refreshed_per_cycle():
    """一轮不该把所有符号都打一遍——那正是招来 429 的原因。"""
    http = CountingHttp()
    provider = YahooFinanceProvider(http, hot_set=_many_codes(20))
    await provider.fetch()
    assert len(http.calls) == YahooFinanceProvider.BATCH


async def test_rotation_eventually_covers_everything():
    http = CountingHttp()
    codes = _many_codes(12)
    provider = YahooFinanceProvider(http, hot_set=codes)
    for _ in range(len(codes) // YahooFinanceProvider.BATCH + 1):
        result = await provider.fetch()
    assert set(codes) <= set(result.quotes)


async def test_cache_keeps_partial_results_alive():
    """第二轮只刷新另一批，上一批的报价必须还在结果里。"""
    http = CountingHttp()
    codes = _many_codes(12)
    provider = YahooFinanceProvider(http, hot_set=codes)
    first = await provider.fetch()
    second = await provider.fetch()
    assert set(first.quotes) - {"USD"} <= set(second.quotes)
    assert len(second.quotes) > len(first.quotes)


async def test_rate_limit_triggers_cooldown_and_stops_requesting():
    http = CountingHttp(fail_after=0)          # 第一发就 429
    provider = YahooFinanceProvider(http, hot_set=_many_codes(8))
    with pytest.raises(ProviderError, match="429"):
        await provider.fetch()                  # 没有缓存 → 如实报错
    assert provider._cooldown_until > 0

    calls_before = len(http.calls)
    with pytest.raises(ProviderError, match="冷却"):
        await provider.fetch()                  # 冷却期内一个请求都不该发
    assert len(http.calls) == calls_before


async def test_cooldown_serves_cache_instead_of_failing():
    http = CountingHttp()
    codes = _many_codes(6)
    provider = YahooFinanceProvider(http, hot_set=codes)
    await provider.fetch()                      # 先攒下缓存

    http.fail_after = 0                         # 之后一律 429
    await provider.fetch()
    assert provider._cooldown_until > 0

    calls_before = len(http.calls)
    result = await provider.fetch()             # 冷却期：吃缓存，不发请求
    assert len(http.calls) == calls_before
    assert result.note == "cached"
    assert set(codes) <= set(result.quotes)


async def test_one_request_per_symbol_no_host_retry():
    """失败不该立刻换 host 再打一遍——那会把请求量翻倍。"""
    http = CountingHttp(fail_after=0)
    provider = YahooFinanceProvider(http, hot_set=["CNY", "JPY"])
    with pytest.raises(ProviderError):
        await provider.fetch()
    assert len(http.calls) == 2                 # 2 个符号 = 2 次请求，不是 4 次


async def test_stale_cache_entries_are_dropped():
    import time as _t

    http = CountingHttp()
    provider = YahooFinanceProvider(http, hot_set=["CNY"])
    await provider.fetch()
    provider._cache["CNY"] = (Decimal("7.2"), _t.time() - YahooFinanceProvider.CACHE_TTL - 10)
    quotes, _ = provider._from_cache(["CNY"])
    assert "CNY" not in quotes                  # 过期就别再拿出来充数


# --- Stooq：一次请求拿一批，天然不撞限流 --------------------------------------


class TextHttp(HttpClient):
    """返回预置文本的假客户端，记录每次请求的参数。"""

    def __init__(self, body: str = "") -> None:
        super().__init__()
        self.body = body
        self.calls: list[dict] = []

    async def get_text(self, url, *, params=None, retries=1, headers=None, tolerate_error=False):  # type: ignore[override]
        self.calls.append({"url": url, "params": params or {}})
        return self.body


STOOQ_CSV = """Symbol,Date,Time,Open,High,Low,Close,Volume
USDCNY,2026-08-04,15:30:00,7.2400,7.2450,7.2380,7.2431,0
USDJPY,2026-08-04,15:30:00,157.10,157.40,157.00,157.3200,0
EURUSD,2026-08-04,15:30:00,1.0890,1.0902,1.0880,1.0851,0
USDXXX,N/D,N/D,N/D,N/D,N/D,N/D,N/D
"""


async def test_stooq_parses_close_column():
    from bot.rates.providers import StooqProvider

    http = TextHttp(STOOQ_CSV)
    result = await StooqProvider(http).fetch(wanted=["CNY", "JPY", "EUR"])
    assert result.quotes["CNY"] == Decimal("7.2431")
    assert result.quotes["JPY"] == Decimal("157.3200")
    assert result.quotes["USD"] == Decimal(1)


async def test_stooq_inverts_majors_quoted_against_usd():
    """EURUSD 报的是 1 EUR = N USD，要倒过来才是「1 USD 换多少欧元」。"""
    from bot.rates.providers import StooqProvider

    http = TextHttp(STOOQ_CSV)
    result = await StooqProvider(http).fetch(wanted=["EUR"])
    assert result.quotes["EUR"] == Decimal(1) / Decimal("1.0851")
    assert StooqProvider.symbol_for("EUR") == ("eurusd", True)
    assert StooqProvider.symbol_for("CNY") == ("usdcny", False)


async def test_stooq_skips_unavailable_rows():
    from bot.rates.providers import StooqProvider

    http = TextHttp(STOOQ_CSV)
    result = await StooqProvider(http).fetch(wanted=["CNY"])
    assert "XXX" not in result.quotes     # N/D 的行直接跳过


async def test_stooq_batches_many_pairs_into_few_requests():
    """一次请求拿一批，正是它比 Yahoo 抗限流的原因。"""
    from bot.rates.providers import StooqProvider

    http = TextHttp(STOOQ_CSV)
    await StooqProvider(http).fetch()
    # 二十多个货币，请求数应该是个位数，而不是每个符号一次
    assert len(http.calls) <= 3
    assert "+" in http.calls[0]["params"]["s"]


async def test_stooq_raises_when_nothing_parses():
    from bot.rates.providers import StooqProvider

    with pytest.raises(ProviderError, match="stooq"):
        await StooqProvider(TextHttp("Symbol,Date,Time,Open,High,Low,Close,Volume\n")).fetch()


# --- Yahoo 的访问凭证 ---------------------------------------------------------


class CrumbHttp(CountingHttp):
    """在 CountingHttp 基础上支持 get_text，用来发 cookie 和 crumb。"""

    def __init__(self, crumb: str = "AbCd1234", **kwargs) -> None:
        super().__init__(**kwargs)
        self.crumb = crumb
        self.text_calls: list[str] = []

    async def get_text(self, url, *, params=None, retries=1, headers=None, tolerate_error=False):  # type: ignore[override]
        self.text_calls.append(url)
        return "" if "fc.yahoo.com" in url else self.crumb


async def test_yahoo_fetches_and_uses_a_crumb():
    """Yahoo 对没有会话凭证的请求一律回 429，跟频率无关，所以必须先拿 crumb。"""
    http = CrumbHttp()
    provider = YahooFinanceProvider(http, hot_set=["CNY"])
    await provider.fetch()
    assert any("fc.yahoo.com" in url for url in http.text_calls)
    assert any("getcrumb" in url for url in http.text_calls)
    assert provider._crumb == "AbCd1234"


async def test_yahoo_reuses_the_crumb_across_cycles():
    http = CrumbHttp()
    provider = YahooFinanceProvider(http, hot_set=["CNY", "JPY"])
    await provider.fetch()
    calls_after_first = len(http.text_calls)
    await provider.fetch()
    assert len(http.text_calls) == calls_after_first   # 没有重复申请


async def test_yahoo_drops_the_crumb_after_a_rate_limit():
    """被限流多半是凭证失效，下一轮要重新申请而不是继续用旧的。"""
    http = CrumbHttp()
    provider = YahooFinanceProvider(http, hot_set=["CNY"])
    await provider.fetch()
    assert provider._crumb

    http.fail_after = 0
    await provider.fetch()
    assert provider._crumb == ""


async def test_yahoo_survives_a_failed_crumb_fetch():
    """拿不到凭证也别拖垮整个源——裸奔请求，成不成看运气。"""
    class NoCrumbHttp(CrumbHttp):
        async def get_text(self, url, **kwargs):  # type: ignore[override]
            raise ProviderError("getcrumb 挂了")

    provider = YahooFinanceProvider(NoCrumbHttp(), hot_set=["CNY"])
    result = await provider.fetch()
    assert result.quotes["CNY"] == Decimal("7.2")
    assert provider._crumb == ""
