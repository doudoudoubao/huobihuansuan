"""汇率服务：多源聚合、后台刷新、交叉汇率、涨跌幅与历史。

所有数据源统一落到「1 USD = X 单位目标货币」的 USD 基准表上，
任意货币对 A→B 的汇率 = table[B] / table[A]。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Sequence

from .. import currencies as cur_mod
from ..config import Config
from .base import HttpClient, ProviderError, ProviderResult, RateProvider
from .providers import (
    ALL_PROVIDER_CLASSES,
    BinanceProvider,
    CurrencyApiProvider,
    FrankfurterProvider,
    YahooFinanceProvider,
)

log = logging.getLogger(__name__)

SNAPSHOT_INTERVAL = 600  # 每 10 分钟留一个快照，用于算涨跌幅
SNAPSHOT_KEEP = 26 * 60 * 60  # 保留 26 小时


@dataclass(slots=True)
class RateInfo:
    base: str
    quote: str
    value: Decimal
    as_of: float
    sources: tuple[str, ...]
    stale: bool = False

    @property
    def age(self) -> float:
        return max(0.0, time.time() - self.as_of)

    @property
    def inverse(self) -> Decimal:
        return Decimal(1) / self.value if self.value else Decimal(0)


@dataclass(slots=True)
class Conversion:
    amount: Decimal
    base: str
    quote: str
    rate: RateInfo
    fee_percent: Decimal | None = None

    @property
    def gross(self) -> Decimal:
        return self.amount * self.rate.value

    @property
    def result(self) -> Decimal:
        if self.fee_percent:
            return self.gross * (Decimal(1) - self.fee_percent / Decimal(100))
        return self.gross

    @property
    def effective_rate(self) -> Decimal:
        if self.fee_percent:
            return self.rate.value * (Decimal(1) - self.fee_percent / Decimal(100))
        return self.rate.value

    @property
    def fee_amount(self) -> Decimal:
        return self.gross - self.result


class RateUnavailable(Exception):
    """某个货币暂时拿不到报价。"""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class RateService:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.http = HttpClient(timeout=config.http_timeout)
        self._providers: list[RateProvider] = []
        for cls in ALL_PROVIDER_CLASSES:
            if cls.name in config.disabled_providers:
                continue
            self._providers.append(cls(self.http))
        self._results: dict[str, ProviderResult] = {}
        self._next_allowed: dict[str, float] = {}
        self._snapshots: list[tuple[float, dict[str, Decimal]]] = []
        self._hot: set[str] = set(cur_mod.POPULAR) | set(config.default_favorites) | {config.default_base}
        self._tasks: list[asyncio.Task] = []
        self._lock = asyncio.Lock()
        self._ready = asyncio.Event()
        self._cache_file = Path(config.db_path).with_name("rates_cache.json")

    # --- 生命周期 -----------------------------------------------------------

    async def start(self) -> None:
        self._load_cache()
        await self.refresh(kinds=("fiat", "crypto", "mixed"))
        self._tasks = [
            asyncio.create_task(self._loop("fiat", self.config.fiat_refresh_seconds), name="rates-fiat"),
            asyncio.create_task(self._loop("crypto", self.config.crypto_refresh_seconds), name="rates-crypto"),
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._tasks.clear()
        self._save_cache()
        await self.http.close()

    async def wait_ready(self, timeout: float = 10.0) -> bool:
        try:
            await asyncio.wait_for(self._ready.wait(), timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def _loop(self, kind: str, interval: int) -> None:
        while True:
            try:
                await asyncio.sleep(max(5, interval))
                await self.refresh(kinds=(kind, "mixed"))
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("刷新 %s 汇率时出错", kind)

    # --- 刷新 ---------------------------------------------------------------

    async def refresh(self, *, kinds: Sequence[str] = ("fiat", "crypto", "mixed"), force: bool = False) -> int:
        """并发拉取所有匹配的数据源，返回成功的源数量。"""
        now = time.time()
        chosen = [
            provider
            for provider in self._providers
            if provider.kind in kinds and (force or self._next_allowed.get(provider.name, 0) <= now)
        ]
        if not chosen:
            return 0

        for provider in chosen:
            if isinstance(provider, YahooFinanceProvider):
                provider.set_hot(self._hot)

        async def run(provider: RateProvider) -> tuple[RateProvider, ProviderResult | Exception]:
            try:
                return provider, await provider.fetch(wanted=self._hot)
            except Exception as exc:  # noqa: BLE001
                return provider, exc

        outcomes = await asyncio.gather(*(run(p) for p in chosen))

        succeeded = 0
        async with self._lock:
            for provider, outcome in outcomes:
                if isinstance(outcome, Exception):
                    provider.mark_failure(outcome)
                    self._next_allowed[provider.name] = time.time() + provider.backoff_seconds
                    log.warning("数据源 %s 失败: %s", provider.name, outcome)
                    continue
                provider.mark_success()
                self._next_allowed[provider.name] = 0
                self._results[provider.name] = outcome
                succeeded += 1
            if succeeded:
                self._record_snapshot()
                self._ready.set()
        if succeeded:
            self._save_cache()
        return succeeded

    async def force_refresh(self) -> int:
        return await self.refresh(kinds=("fiat", "crypto", "mixed"), force=True)

    def inject(self, provider: str, quotes: dict[str, Decimal], *, as_of: float | None = None) -> None:
        """直接写入一份报价表。

        供测试与离线演示使用，也可用于接入自建行情源。
        """
        self._results[provider] = ProviderResult(provider, dict(quotes), as_of=as_of or time.time())
        self._record_snapshot()
        self._ready.set()

    def note_usage(self, codes: Iterable[str]) -> None:
        """记录被用到的货币，让准实时数据源优先覆盖它们。"""
        for code in codes:
            code = code.upper()
            if cur_mod.is_known(code):
                self._hot.add(code)
        if len(self._hot) > 40:
            # 保底集合永远保留，其余先进先出地裁剪
            keep = set(cur_mod.POPULAR) | set(self.config.default_favorites)
            extra = [c for c in self._hot if c not in keep]
            for code in extra[: len(self._hot) - 40]:
                self._hot.discard(code)

    # --- 查询 ---------------------------------------------------------------

    def _priority(self, name: str) -> int:
        for provider in self._providers:
            if provider.name == name:
                return provider.priority
        return 999

    def _lookup(self, code: str) -> tuple[Decimal, float, str] | None:
        """返回 (1 USD 对应的数量, 数据时间, 数据源)。"""
        code = code.upper()
        if code == "USD":
            return Decimal(1), time.time(), "identity"
        best: tuple[int, float, Decimal, str] | None = None
        for name, result in self._results.items():
            value = result.quotes.get(code)
            if value is None:
                continue
            key = (self._priority(name), -result.as_of)
            if best is None or key < (best[0], -best[1]):
                best = (self._priority(name), result.as_of, value, name)
        if best is None:
            return None
        return best[2], best[1], best[3]

    def has(self, code: str) -> bool:
        return self._lookup(code) is not None

    def available_codes(self) -> set[str]:
        codes = {"USD"}
        for result in self._results.values():
            codes |= set(result.quotes)
        return codes

    def get_rate(self, base: str, quote: str) -> RateInfo:
        base, quote = base.upper(), quote.upper()
        src = self._lookup(base)
        if src is None:
            raise RateUnavailable(base)
        dst = self._lookup(quote)
        if dst is None:
            raise RateUnavailable(quote)
        if src[0] == 0:
            raise RateUnavailable(base)
        value = dst[0] / src[0]
        as_of = min(src[1], dst[1])
        sources = tuple(sorted({src[2], dst[2]} - {"identity"})) or ("identity",)
        return RateInfo(
            base=base,
            quote=quote,
            value=value,
            as_of=as_of,
            sources=sources,
            stale=(time.time() - as_of) > self.config.stale_after_seconds,
        )

    def convert(
        self, amount: Decimal, base: str, quote: str, *, fee_percent: Decimal | None = None
    ) -> Conversion:
        rate = self.get_rate(base, quote)
        self.note_usage((base, quote))
        return Conversion(amount=amount, base=base.upper(), quote=quote.upper(), rate=rate, fee_percent=fee_percent)

    def convert_many(
        self, amount: Decimal, base: str, quotes: Sequence[str], *, fee_percent: Decimal | None = None
    ) -> tuple[list[Conversion], list[str]]:
        """一对多换算，返回 (成功列表, 缺报价的货币列表)。"""
        done: list[Conversion] = []
        missing: list[str] = []
        for quote in quotes:
            try:
                done.append(self.convert(amount, base, quote, fee_percent=fee_percent))
            except RateUnavailable as exc:
                missing.append(exc.code)
        return done, missing

    # --- 涨跌幅 -------------------------------------------------------------

    def _record_snapshot(self) -> None:
        now = time.time()
        if self._snapshots and now - self._snapshots[-1][0] < SNAPSHOT_INTERVAL:
            return
        table: dict[str, Decimal] = {}
        for code in self.available_codes():
            found = self._lookup(code)
            if found:
                table[code] = found[0]
        self._snapshots.append((now, table))
        cutoff = now - SNAPSHOT_KEEP
        self._snapshots = [s for s in self._snapshots if s[0] >= cutoff]

    def change_percent(self, base: str, quote: str, window_seconds: float = 86400) -> Decimal | None:
        """相对 `window_seconds` 之前的涨跌幅（%）。数据不足返回 None。"""
        if not self._snapshots:
            return None
        target = time.time() - window_seconds
        candidates = [s for s in self._snapshots if s[0] <= target]
        snapshot = candidates[-1] if candidates else self._snapshots[0]
        if time.time() - snapshot[0] < window_seconds * 0.4:
            return None  # 采样时间还不够长，给不出有意义的对比
        table = snapshot[1]
        old_base, old_quote = table.get(base.upper()), table.get(quote.upper())
        if base.upper() == "USD":
            old_base = Decimal(1)
        if quote.upper() == "USD":
            old_quote = Decimal(1)
        if not old_base or not old_quote:
            return None
        try:
            old_rate = old_quote / old_base
            current = self.get_rate(base, quote).value
        except (RateUnavailable, ArithmeticError):
            return None
        if old_rate == 0:
            return None
        return (current - old_rate) / old_rate * Decimal(100)

    # --- 历史 ---------------------------------------------------------------

    async def history(self, base: str, quote: str, days: int = 30) -> list[tuple[date, Decimal]]:
        base, quote = base.upper(), quote.upper()
        if base == quote:
            raise ProviderError("同一种货币没有走势可看")
        candidates = [p for p in self._providers if p.supports_history]
        candidates.sort(key=lambda p: p.priority)
        errors: list[str] = []
        for provider in candidates:
            try:
                series = await provider.history(base, quote, days)
                if series:
                    return series
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{provider.name}: {exc}")
        # 直连拿不到时，尝试用 USD 作为中转分别取序列再合成
        try:
            return await self._cross_history(base, quote, days)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"cross: {exc}")
        raise ProviderError("；".join(errors[:3]) or "无历史数据")

    async def _cross_history(self, base: str, quote: str, days: int) -> list[tuple[date, Decimal]]:
        async def leg(code: str) -> dict[date, Decimal]:
            if code == "USD":
                return {}
            for provider in sorted(
                (p for p in self._providers if p.supports_history), key=lambda p: p.priority
            ):
                try:
                    return dict(await provider.history("USD", code, days))
                except Exception:  # noqa: BLE001
                    continue
            raise ProviderError(f"{code} 无历史数据")

        base_series, quote_series = await asyncio.gather(leg(base), leg(quote))
        days_set = set(base_series or quote_series) & set(quote_series or base_series)
        if not days_set:
            days_set = set(base_series) | set(quote_series)
        out: list[tuple[date, Decimal]] = []
        for day in sorted(days_set):
            b = base_series.get(day, Decimal(1)) if base != "USD" else Decimal(1)
            q = quote_series.get(day, Decimal(1)) if quote != "USD" else Decimal(1)
            if b:
                out.append((day, q / b))
        if not out:
            raise ProviderError("交叉历史合成失败")
        return out

    async def rate_on(self, base: str, quote: str, day: date) -> tuple[date, Decimal]:
        """查询某一天的汇率，取不到当天就用最近的一天。"""
        span = max(3, (date.today() - day).days + 3)
        series = await self.history(base, quote, min(span, 400))
        if not series:
            raise ProviderError("无历史数据")
        exact = [item for item in series if item[0] == day]
        if exact:
            return exact[0]
        before = [item for item in series if item[0] <= day]
        return before[-1] if before else series[0]

    # --- 运维 ---------------------------------------------------------------

    def status(self) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for provider in sorted(self._providers, key=lambda p: (p.kind, p.priority)):
            result = self._results.get(provider.name)
            rows.append(
                {
                    "name": provider.name,
                    "kind": provider.kind,
                    "priority": provider.priority,
                    "healthy": provider.healthy,
                    "currencies": len(result.quotes) if result else 0,
                    "age": round(time.time() - result.as_of, 1) if result else None,
                    "failures": provider.consecutive_failures,
                    "error": provider.last_error,
                }
            )
        return rows

    # --- 本地缓存（冷启动兜底） ---------------------------------------------

    def _save_cache(self) -> None:
        try:
            payload = {
                "saved_at": time.time(),
                "results": {
                    name: {
                        "as_of": result.as_of,
                        "note": result.note,
                        "quotes": {k: str(v) for k, v in result.quotes.items()},
                    }
                    for name, result in self._results.items()
                },
            }
            self._cache_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._cache_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            tmp.replace(self._cache_file)
        except OSError as exc:
            log.debug("写汇率缓存失败: %s", exc)

    def _load_cache(self) -> None:
        try:
            payload = json.loads(self._cache_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for name, row in (payload.get("results") or {}).items():
            quotes: dict[str, Decimal] = {}
            for code, value in (row.get("quotes") or {}).items():
                try:
                    quotes[code] = Decimal(value)
                except ArithmeticError:
                    continue
            if quotes:
                self._results[name] = ProviderResult(
                    name, quotes, as_of=float(row.get("as_of") or 0), note=row.get("note", "")
                )
        if self._results:
            self._ready.set()
            log.info("已从本地缓存恢复 %d 个数据源的汇率", len(self._results))


__all__ = [
    "Conversion",
    "RateInfo",
    "RateService",
    "RateUnavailable",
    "BinanceProvider",
    "CurrencyApiProvider",
    "FrankfurterProvider",
    "YahooFinanceProvider",
]
