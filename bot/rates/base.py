"""汇率数据源的公共类型与 HTTP 工具。"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Iterable

import aiohttp

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


@dataclass(slots=True)
class Quote:
    """单个货币相对 USD 的报价：1 USD = `value` 单位的该货币。"""

    code: str
    value: Decimal
    provider: str
    fetched_at: float = field(default_factory=time.time)

    @property
    def age(self) -> float:
        return max(0.0, time.time() - self.fetched_at)


@dataclass(slots=True)
class ProviderResult:
    provider: str
    quotes: dict[str, Decimal]
    as_of: float = field(default_factory=time.time)
    note: str = ""

    def __bool__(self) -> bool:
        return bool(self.quotes)


class ProviderError(Exception):
    """数据源不可用（网络、限流、格式变化等）。"""


class RateProvider:
    """所有数据源的基类。

    约定：`fetch()` 返回「1 USD 等于多少单位的目标货币」的映射表。
    这样所有源都能落到同一张 USD 基准表上，交叉汇率由服务层统一计算。
    """

    name: str = "base"
    kind: str = "fiat"  # fiat | crypto | metal | mixed
    priority: int = 100  # 越小越优先
    supports_history: bool = False
    #: 该源在一次 fetch 中能覆盖的货币；为空表示"未知/全量"
    covers: frozenset[str] = frozenset()

    def __init__(self, http: "HttpClient") -> None:
        self.http = http
        self.consecutive_failures = 0
        self.last_success: float | None = None
        self.last_error: str = ""

    async def fetch(self, wanted: Iterable[str] | None = None) -> ProviderResult:
        raise NotImplementedError

    async def history(self, base: str, quote: str, days: int) -> list[tuple[date, Decimal]]:
        raise NotImplementedError

    # --- 健康度 ---

    def mark_success(self) -> None:
        self.consecutive_failures = 0
        self.last_success = time.time()
        self.last_error = ""

    def mark_failure(self, error: BaseException | str) -> None:
        self.consecutive_failures += 1
        self.last_error = str(error)[:200]

    @property
    def healthy(self) -> bool:
        return self.consecutive_failures < 3

    @property
    def backoff_seconds(self) -> float:
        """连续失败后的退避时长，封顶 10 分钟。"""
        if self.consecutive_failures == 0:
            return 0.0
        return min(600.0, 15.0 * (2 ** min(self.consecutive_failures - 1, 6)))


class HttpClient:
    """带超时、重试与统一 UA 的极简 HTTP 客户端。"""

    def __init__(self, timeout: float = 8.0) -> None:
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: aiohttp.ClientSession | None = None
        self._lock = asyncio.Lock()

    async def session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            async with self._lock:
                if self._session is None or self._session.closed:
                    self._session = aiohttp.ClientSession(
                        timeout=self._timeout,
                        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                    )
        return self._session

    async def get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        retries: int = 2,
        headers: dict[str, str] | None = None,
    ) -> Any:
        last_exc: BaseException | None = None
        for attempt in range(retries + 1):
            try:
                session = await self.session()
                async with session.get(url, params=params, headers=headers) as resp:
                    if resp.status == 429:
                        raise ProviderError(f"{url} 被限流 (429)")
                    if resp.status >= 400:
                        raise ProviderError(f"{url} 返回 HTTP {resp.status}")
                    # 某些 CDN 会用 text/plain 返回 JSON
                    return await resp.json(content_type=None)
            except (aiohttp.ClientError, asyncio.TimeoutError, ProviderError, ValueError) as exc:
                last_exc = exc
                if attempt < retries:
                    await asyncio.sleep(0.4 * (attempt + 1))
        raise ProviderError(str(last_exc) if last_exc else f"{url} 请求失败")

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()


def to_decimal(value: Any) -> Decimal | None:
    """把 API 返回的数字安全地转成 Decimal，异常值直接丢弃。"""
    try:
        dec = Decimal(str(value))
    except (ArithmeticError, ValueError, TypeError):
        return None
    if not dec.is_finite() or dec <= 0:
        return None
    return dec
