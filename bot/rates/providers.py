"""具体的汇率数据源实现。

全部统一输出「1 USD = X 单位目标货币」的映射，方便服务层合并。
优先级（priority 越小越先采用）：

    法币  Yahoo(准实时) 10  →  Frankfurter/ECB 30  →  open.er-api 40  →  currency-api 50
    加密  Binance 10       →  OKX 20             →  CoinGecko 40     →  currency-api 50
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterable

from .. import currencies as cur_mod
from .base import ProviderError, ProviderResult, RateProvider, to_decimal

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# 法币
# --------------------------------------------------------------------------- #


class FrankfurterProvider(RateProvider):
    """欧洲央行参考汇率（每工作日 16:00 CET 更新），稳定、无需 key。"""

    name = "frankfurter"
    kind = "fiat"
    priority = 30
    supports_history = True

    HOSTS = ("https://api.frankfurter.app", "https://api.frankfurter.dev/v1")

    async def fetch(self, wanted: Iterable[str] | None = None) -> ProviderResult:
        last: BaseException | None = None
        for host in self.HOSTS:
            try:
                data = await self.http.get_json(f"{host}/latest", params={"from": "USD"})
                rates = data.get("rates") or {}
                quotes = {"USD": Decimal(1)}
                for code, value in rates.items():
                    dec = to_decimal(value)
                    if dec is not None:
                        quotes[code.upper()] = dec
                if len(quotes) < 5:
                    raise ProviderError("frankfurter 返回数据过少")
                as_of = _parse_date_ts(data.get("date"))
                return ProviderResult(self.name, quotes, as_of=as_of, note="ECB")
            except Exception as exc:  # noqa: BLE001 - 逐个 host 兜底
                last = exc
        raise ProviderError(f"frankfurter 全部节点失败: {last}")

    async def history(self, base: str, quote: str, days: int) -> list[tuple[date, Decimal]]:
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=max(days, 2))
        last: BaseException | None = None
        for host in self.HOSTS:
            try:
                data = await self.http.get_json(
                    f"{host}/{start.isoformat()}..{end.isoformat()}",
                    params={"from": base.upper(), "to": quote.upper()},
                )
                series: list[tuple[date, Decimal]] = []
                for day, values in sorted((data.get("rates") or {}).items()):
                    dec = to_decimal((values or {}).get(quote.upper()))
                    if dec is not None:
                        series.append((date.fromisoformat(day), dec))
                if series:
                    return series
                raise ProviderError("frankfurter 无历史数据")
            except Exception as exc:  # noqa: BLE001
                last = exc
        raise ProviderError(f"frankfurter 历史数据失败: {last}")


class OpenErApiProvider(RateProvider):
    """open.er-api.com：免费、无需 key、覆盖 160+ 法币，每日更新。"""

    name = "open-er-api"
    kind = "fiat"
    priority = 40

    async def fetch(self, wanted: Iterable[str] | None = None) -> ProviderResult:
        data = await self.http.get_json("https://open.er-api.com/v6/latest/USD")
        if data.get("result") != "success":
            raise ProviderError(f"open-er-api 返回 {data.get('error-type', 'unknown')}")
        quotes: dict[str, Decimal] = {}
        for code, value in (data.get("rates") or {}).items():
            dec = to_decimal(value)
            if dec is not None:
                quotes[code.upper()] = dec
        if len(quotes) < 20:
            raise ProviderError("open-er-api 返回数据过少")
        as_of = float(data.get("time_last_update_unix") or time.time())
        return ProviderResult(self.name, quotes, as_of=as_of)


class CurrencyApiProvider(RateProvider):
    """fawazahmed0/currency-api：覆盖面最广（法币 + 加密 + 贵金属），CDN 托管。

    作为“永远有数”的兜底源使用。
    """

    name = "currency-api"
    kind = "mixed"
    priority = 50
    supports_history = True

    def _urls(self, tag: str) -> tuple[str, ...]:
        return (
            f"https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@{tag}/v1/currencies/usd.min.json",
            f"https://{tag}.currency-api.pages.dev/v1/currencies/usd.json",
            f"https://raw.githubusercontent.com/fawazahmed0/exchange-api/main/{tag}/v1/currencies/usd.json",
        )

    async def _load(self, tag: str) -> dict[str, Any]:
        last: BaseException | None = None
        for url in self._urls(tag):
            try:
                data = await self.http.get_json(url, retries=1)
                if isinstance(data, dict) and "usd" in data:
                    return data
                last = ProviderError(f"{url} 返回结构异常")
            except Exception as exc:  # noqa: BLE001
                last = exc
        raise ProviderError(f"currency-api 全部节点失败: {last}")

    async def fetch(self, wanted: Iterable[str] | None = None) -> ProviderResult:
        data = await self._load("latest")
        quotes: dict[str, Decimal] = {}
        for code, value in (data.get("usd") or {}).items():
            upper = code.upper()
            if not cur_mod.is_known(upper):
                continue
            dec = to_decimal(value)
            if dec is not None:
                quotes[upper] = dec
        quotes.setdefault("USD", Decimal(1))
        if len(quotes) < 20:
            raise ProviderError("currency-api 返回数据过少")
        return ProviderResult(self.name, quotes, as_of=_parse_date_ts(data.get("date")))

    async def history(self, base: str, quote: str, days: int) -> list[tuple[date, Decimal]]:
        """按天抓取。请求数较多，仅在其它源都不支持该货币对时兜底。"""
        today = datetime.now(timezone.utc).date()
        step = max(1, days // 30)
        wanted_days = [today - timedelta(days=offset) for offset in range(0, days + 1, step)]
        sem = asyncio.Semaphore(5)

        async def one(day: date) -> tuple[date, Decimal] | None:
            async with sem:
                try:
                    data = await self._load(day.isoformat())
                except ProviderError:
                    return None
            table = {k.upper(): v for k, v in (data.get("usd") or {}).items()}
            table["USD"] = 1
            src = to_decimal(table.get(base.upper()))
            dst = to_decimal(table.get(quote.upper()))
            if src is None or dst is None:
                return None
            return day, dst / src

        results = await asyncio.gather(*(one(day) for day in wanted_days))
        series = sorted([r for r in results if r], key=lambda item: item[0])
        if not series:
            raise ProviderError("currency-api 无历史数据")
        return series


class YahooFinanceProvider(RateProvider):
    """Yahoo Finance 图表接口：分钟级的准实时报价，也提供历史序列。

    没有免鉴权的批量接口，只能一个符号一个请求 —— 于是**请求节奏就是成败关键**。
    实测：单发一次稳定 200，紧接着连发就吃 429。所以这里不再「一口气把所有
    符号并发拉完」，而是：

    * 每轮只刷新 `BATCH` 个「最久没更新」的符号，其余沿用缓存 → 轮转覆盖
    * 并发压到 2，且每个请求之间留出间隔 → 平均约 6 次/分钟
    * 撞到 429 就进入冷却，期间直接吃缓存，不再发请求
    * 部分失败不清空成果：缓存里还新鲜的报价照常返回

    这样每个符号大约每 4 分钟刷新一次 —— 比每日源新鲜得多，也不会招来限流。
    """

    name = "yahoo"
    kind = "mixed"
    cadence = "realtime"
    priority = 10
    supports_history = True

    HOSTS = (
        "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
        "https://query2.finance.yahoo.com/v8/finance/chart/{symbol}",
    )
    CHART = HOSTS[0]  # 历史查询用，单发一次不涉及限流

    MAX_SYMBOLS = 24       # 一共盯这么多货币
    BATCH = 6              # 每轮最多刷新几个
    CONCURRENCY = 2        # 同时在飞的请求数
    SPACING = 0.35         # 每个请求起步之间的最小间隔（秒）
    COOLDOWN_ON_429 = 300  # 被限流后歇多久再试
    CACHE_TTL = 900        # 缓存里的报价超过这么久就不再拿出来用

    def __init__(self, http, hot_set: Iterable[str] | None = None) -> None:  # noqa: ANN001
        super().__init__(http)
        self._hot: set[str] = set(hot_set or cur_mod.POPULAR)
        #: code -> (1 USD 对应的数量, 抓到的时间)
        self._cache: dict[str, tuple[Decimal, float]] = {}
        self._cooldown_until = 0.0
        self._rotation = 0

    def set_hot(self, codes: Iterable[str]) -> None:
        """由服务层告知“最近有人用”的货币，动态调整拉取范围。"""
        self._hot = {c.upper() for c in codes if cur_mod.is_known(c)}

    @staticmethod
    def symbol_for(code: str) -> str:
        code = code.upper()
        if code == "USD":
            return ""
        if code in cur_mod.CRYPTO_CODES:
            return f"{code}-USD"
        return f"{code}=X"  # 隐含以 USD 为基准

    async def _quote(self, code: str, host_index: int) -> tuple[str, Decimal] | None:
        """抓一个符号。只发一次请求——失败就等下一轮，别原地重试加剧限流。"""
        symbol = self.symbol_for(code)
        if not symbol:
            return code, Decimal(1)
        url = self.HOSTS[host_index % len(self.HOSTS)].format(symbol=symbol)
        data = await self.http.get_json(url, params={"range": "1d", "interval": "5m"}, retries=0)
        meta = (((data.get("chart") or {}).get("result") or [{}])[0] or {}).get("meta") or {}
        price = to_decimal(meta.get("regularMarketPrice"))
        if price is None:
            return None
        # BTC-USD 报的是 1 BTC = N USD，需要取倒数
        return code, (Decimal(1) / price if code in cur_mod.CRYPTO_CODES else price)

    def _due_for_refresh(self, targets: list[str]) -> list[str]:
        """挑出本轮要刷新的符号：没缓存的优先，其次是最久没更新的。"""
        return sorted(targets, key=lambda code: self._cache.get(code, (None, 0.0))[1])[: self.BATCH]

    def _from_cache(self, targets: list[str]) -> tuple[dict[str, Decimal], float]:
        now = time.time()
        quotes: dict[str, Decimal] = {"USD": Decimal(1)}
        oldest = now
        for code in targets:
            cached = self._cache.get(code)
            if cached and now - cached[1] <= self.CACHE_TTL:
                quotes[code] = cached[0]
                oldest = min(oldest, cached[1])
        return quotes, oldest

    async def fetch(self, wanted: Iterable[str] | None = None) -> ProviderResult:
        codes = {c.upper() for c in (wanted or ())} | self._hot
        targets = sorted(c for c in codes if cur_mod.is_known(c) and c != "USD")[: self.MAX_SYMBOLS]

        now = time.time()
        if now < self._cooldown_until:
            quotes, oldest = self._from_cache(targets)
            if len(quotes) < 2:
                raise ProviderError(
                    f"yahoo 限流冷却中，还剩 {int(self._cooldown_until - now)}s，且无可用缓存"
                )
            return ProviderResult(self.name, quotes, as_of=oldest, note="cached")

        sem = asyncio.Semaphore(self.CONCURRENCY)
        due = self._due_for_refresh(targets)
        throttled = False
        errors: list[str] = []

        async def guarded(index: int, code: str):  # noqa: ANN202
            # 错开起步时间，避免同一瞬间打过去
            await asyncio.sleep(index * self.SPACING)
            async with sem:
                try:
                    return await self._quote(code, self._rotation + index)
                except ProviderError as exc:
                    nonlocal throttled
                    if "429" in str(exc):
                        throttled = True
                    errors.append(str(exc))
                    return None
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{code}: {exc}")
                    return None

        results = await asyncio.gather(*(guarded(i, code) for i, code in enumerate(due)))
        self._rotation += len(due)

        fetched_now = time.time()
        for item in results:
            if item:
                self._cache[item[0]] = (item[1], fetched_now)

        if throttled:
            self._cooldown_until = fetched_now + self.COOLDOWN_ON_429
            log.warning("yahoo 被限流，冷却 %ds 后再试", self.COOLDOWN_ON_429)

        quotes, oldest = self._from_cache(targets)
        if len(quotes) < 2:
            reason = errors[0] if errors else "无可用报价"
            raise ProviderError(f"yahoo {reason}")
        return ProviderResult(self.name, quotes, as_of=oldest, note="realtime")

    async def history(self, base: str, quote: str, days: int) -> list[tuple[date, Decimal]]:
        base, quote = base.upper(), quote.upper()
        symbol = None
        invert = False
        if base == "USD":
            symbol = self.symbol_for(quote)
            invert = quote in cur_mod.CRYPTO_CODES
        elif quote == "USD":
            symbol = self.symbol_for(base)
            invert = base not in cur_mod.CRYPTO_CODES
        elif quote in cur_mod.CRYPTO_CODES or base in cur_mod.CRYPTO_CODES:
            symbol = None
        else:
            symbol = f"{base}{quote}=X"
        if not symbol:
            raise ProviderError("yahoo 不支持该货币对的历史数据")

        rng = "5d" if days <= 5 else "1mo" if days <= 31 else "3mo" if days <= 93 else "1y" if days <= 370 else "5y"
        interval = "1h" if days <= 5 else "1d"
        data = await self.http.get_json(
            self.CHART.format(symbol=symbol), params={"range": rng, "interval": interval}
        )
        result = ((data.get("chart") or {}).get("result") or [None])[0]
        if not result:
            raise ProviderError("yahoo 历史数据为空")
        stamps = result.get("timestamp") or []
        closes = (((result.get("indicators") or {}).get("quote") or [{}])[0] or {}).get("close") or []
        series: list[tuple[date, Decimal]] = []
        for ts, close in zip(stamps, closes):
            dec = to_decimal(close)
            if dec is None:
                continue
            if invert:
                dec = Decimal(1) / dec
            series.append((datetime.fromtimestamp(ts, tz=timezone.utc).date(), dec))
        if not series:
            raise ProviderError("yahoo 历史数据为空")
        # 同一天多个点时保留最后一个
        merged: dict[date, Decimal] = {}
        for day, value in series:
            merged[day] = value
        return sorted(merged.items())


# --------------------------------------------------------------------------- #
# 加密货币
# --------------------------------------------------------------------------- #


class BinanceProvider(RateProvider):
    """币安现货价格：秒级更新，一次请求拿到全量交易对。"""

    name = "binance"
    kind = "crypto"
    cadence = "realtime"
    priority = 10
    supports_history = True

    HOSTS = (
        "https://data-api.binance.vision",
        "https://api.binance.com",
        "https://api1.binance.com",
    )
    STABLE = "USDT"

    async def fetch(self, wanted: Iterable[str] | None = None) -> ProviderResult:
        last: BaseException | None = None
        for host in self.HOSTS:
            try:
                data = await self.http.get_json(f"{host}/api/v3/ticker/price", retries=1)
                if not isinstance(data, list):
                    raise ProviderError("binance 返回结构异常")
                quotes: dict[str, Decimal] = {self.STABLE: Decimal(1), "USD": Decimal(1)}
                for row in data:
                    symbol = str(row.get("symbol", ""))
                    if not symbol.endswith(self.STABLE):
                        continue
                    code = symbol[: -len(self.STABLE)]
                    if code not in cur_mod.CRYPTO_CODES:
                        continue
                    price = to_decimal(row.get("price"))
                    if price is None:
                        continue
                    quotes[code] = Decimal(1) / price  # 1 USD 能买多少个币
                if len(quotes) < 4:
                    raise ProviderError("binance 无匹配交易对")
                return ProviderResult(self.name, quotes, note="realtime")
            except Exception as exc:  # noqa: BLE001
                last = exc
        raise ProviderError(f"binance 全部节点失败: {last}")

    async def history(self, base: str, quote: str, days: int) -> list[tuple[date, Decimal]]:
        base, quote = base.upper(), quote.upper()
        if base in cur_mod.CRYPTO_CODES and quote in ("USD", "USDT"):
            symbol, invert = f"{base}USDT", False
        elif quote in cur_mod.CRYPTO_CODES and base in ("USD", "USDT"):
            symbol, invert = f"{quote}USDT", True
        else:
            raise ProviderError("binance 仅支持币/USDT 历史")
        last: BaseException | None = None
        for host in self.HOSTS:
            try:
                data = await self.http.get_json(
                    f"{host}/api/v3/klines",
                    params={"symbol": symbol, "interval": "1d", "limit": min(days + 1, 1000)},
                    retries=1,
                )
                series: list[tuple[date, Decimal]] = []
                for row in data:
                    close = to_decimal(row[4])
                    if close is None:
                        continue
                    day = datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc).date()
                    series.append((day, Decimal(1) / close if invert else close))
                if series:
                    return series
                raise ProviderError("binance 历史为空")
            except Exception as exc:  # noqa: BLE001
                last = exc
        raise ProviderError(f"binance 历史失败: {last}")


class OkxProvider(RateProvider):
    """OKX 现货行情，作为币安的备份。"""

    name = "okx"
    kind = "crypto"
    cadence = "realtime"
    priority = 20

    async def fetch(self, wanted: Iterable[str] | None = None) -> ProviderResult:
        data = await self.http.get_json(
            "https://www.okx.com/api/v5/market/tickers", params={"instType": "SPOT"}, retries=1
        )
        if str(data.get("code")) != "0":
            raise ProviderError(f"okx 返回 code={data.get('code')}")
        quotes: dict[str, Decimal] = {"USDT": Decimal(1), "USD": Decimal(1)}
        for row in data.get("data") or []:
            inst = str(row.get("instId", ""))
            if not inst.endswith("-USDT"):
                continue
            code = inst[: -len("-USDT")]
            if code not in cur_mod.CRYPTO_CODES:
                continue
            price = to_decimal(row.get("last"))
            if price is not None:
                quotes[code] = Decimal(1) / price
        if len(quotes) < 4:
            raise ProviderError("okx 无匹配交易对")
        return ProviderResult(self.name, quotes, note="realtime")


class CoinGeckoProvider(RateProvider):
    """CoinGecko 免费接口，限流较严，仅作最后兜底。"""

    name = "coingecko"
    kind = "crypto"
    cadence = "realtime"
    priority = 40

    IDS: dict[str, str] = {
        "BTC": "bitcoin", "ETH": "ethereum", "USDT": "tether", "USDC": "usd-coin",
        "BNB": "binancecoin", "SOL": "solana", "XRP": "ripple", "DOGE": "dogecoin",
        "ADA": "cardano", "TRX": "tron", "TON": "the-open-network", "AVAX": "avalanche-2",
        "DOT": "polkadot", "MATIC": "matic-network", "LTC": "litecoin",
        "BCH": "bitcoin-cash", "LINK": "chainlink", "SHIB": "shiba-inu",
        "UNI": "uniswap", "ATOM": "cosmos", "XLM": "stellar",
        "ETC": "ethereum-classic", "FIL": "filecoin", "APT": "aptos",
        "ARB": "arbitrum", "OP": "optimism", "NEAR": "near", "SUI": "sui",
        "PEPE": "pepe", "DAI": "dai",
    }

    async def fetch(self, wanted: Iterable[str] | None = None) -> ProviderResult:
        data = await self.http.get_json(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": ",".join(sorted(set(self.IDS.values()))), "vs_currencies": "usd"},
            retries=1,
        )
        reverse = {v: k for k, v in self.IDS.items()}
        quotes: dict[str, Decimal] = {"USD": Decimal(1)}
        for gecko_id, payload in (data or {}).items():
            code = reverse.get(gecko_id)
            price = to_decimal((payload or {}).get("usd"))
            if code and price is not None:
                quotes[code] = Decimal(1) / price
        if len(quotes) < 3:
            raise ProviderError("coingecko 无有效数据")
        return ProviderResult(self.name, quotes)


# --------------------------------------------------------------------------- #


def _parse_date_ts(value: Any) -> float:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(
                tzinfo=timezone.utc
            ).timestamp()
        except ValueError:
            pass
    return time.time()


ALL_PROVIDER_CLASSES: tuple[type[RateProvider], ...] = (
    YahooFinanceProvider,
    BinanceProvider,
    OkxProvider,
    FrankfurterProvider,
    OpenErApiProvider,
    CoinGeckoProvider,
    CurrencyApiProvider,
)
