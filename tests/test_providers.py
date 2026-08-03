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
