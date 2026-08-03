"""SQLite 持久化：用户偏好、汇率提醒、定时播报、使用记录。"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Any, Iterable, Sequence

import aiosqlite

from .config import Config
from .currencies import FILLER

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id      INTEGER PRIMARY KEY,
    lang         TEXT    NOT NULL DEFAULT 'zh',
    base         TEXT    NOT NULL DEFAULT 'CNY',
    favorites    TEXT    NOT NULL DEFAULT 'USD,HKD,EUR,JPY,GBP,KRW,TWD,SGD,AUD,THB',
    decimals     INTEGER NOT NULL DEFAULT 2,
    group_sep    INTEGER NOT NULL DEFAULT 1,
    show_source  INTEGER NOT NULL DEFAULT 1,
    show_change  INTEGER NOT NULL DEFAULT 1,
    tz           TEXT    NOT NULL DEFAULT 'Asia/Shanghai',
    fee_percent  TEXT    NOT NULL DEFAULT '',
    created_at   REAL    NOT NULL DEFAULT 0,
    updated_at   REAL    NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS alerts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL,
    chat_id       INTEGER NOT NULL,
    base          TEXT    NOT NULL,
    quote         TEXT    NOT NULL,
    op            TEXT    NOT NULL,           -- '>' | '<' | 'pct'
    threshold     TEXT    NOT NULL,
    repeat        INTEGER NOT NULL DEFAULT 0, -- 0=触发后停用, 1=持续提醒
    active        INTEGER NOT NULL DEFAULT 1,
    baseline      TEXT    NOT NULL DEFAULT '',-- pct 类型的参考价
    created_at    REAL    NOT NULL DEFAULT 0,
    last_fired_at REAL    NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_alerts_active ON alerts(active);

CREATE TABLE IF NOT EXISTS subscriptions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    chat_id     INTEGER NOT NULL,
    base        TEXT    NOT NULL,
    quotes      TEXT    NOT NULL,
    at_time     TEXT    NOT NULL,             -- HH:MM
    tz          TEXT    NOT NULL DEFAULT 'Asia/Shanghai',
    active      INTEGER NOT NULL DEFAULT 1,
    last_sent   TEXT    NOT NULL DEFAULT '',  -- YYYY-MM-DD
    created_at  REAL    NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_subs_active ON subscriptions(active);

CREATE TABLE IF NOT EXISTS usage (
    user_id     INTEGER NOT NULL,
    code        TEXT    NOT NULL,
    hits        INTEGER NOT NULL DEFAULT 0,
    last_used   REAL    NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, code)
);
"""


@dataclass(slots=True)
class UserPrefs:
    user_id: int
    lang: str = "zh"
    base: str = "CNY"
    favorites: list[str] = field(default_factory=list)
    decimals: int = 2
    group_sep: bool = True
    show_source: bool = True
    show_change: bool = True
    tz: str = "Asia/Shanghai"
    fee_percent: Decimal | None = None

    def targets_for(self, source: str, limit: int = 10) -> list[str]:
        """给定源币种，返回默认要展示的目标币种列表。

        顺序为：默认币种 → 常用币种 → 主流货币补齐，
        保证「只发一个金额」也能一次看到 limit 行，不用再手打目标货币。
        """
        source = source.upper()
        out: list[str] = []
        seen = {source}

        home = self.base.upper()
        if home != source:
            out.append(home)
            seen.add(home)

        for code in self.favorites:
            code = code.upper()
            if code not in seen:
                out.append(code)
                seen.add(code)

        for code in FILLER:
            if len(out) >= limit:
                break
            if code not in seen:
                out.append(code)
                seen.add(code)

        return out[:limit]


@dataclass(slots=True)
class Alert:
    id: int
    user_id: int
    chat_id: int
    base: str
    quote: str
    op: str
    threshold: Decimal
    repeat: bool = False
    active: bool = True
    baseline: Decimal | None = None
    created_at: float = 0.0
    last_fired_at: float = 0.0

    def describe(self) -> str:
        if self.op == "pct":
            return f"{self.base}/{self.quote} 波动 ≥ {self.threshold}%"
        symbol = "≥" if self.op == ">" else "≤"
        return f"{self.base}/{self.quote} {symbol} {self.threshold}"


@dataclass(slots=True)
class Subscription:
    id: int
    user_id: int
    chat_id: int
    base: str
    quotes: list[str]
    at_time: str
    tz: str = "Asia/Shanghai"
    active: bool = True
    last_sent: str = ""
    created_at: float = 0.0

    def describe(self) -> str:
        return f"每天 {self.at_time} 播报 {self.base} → {'/'.join(self.quotes)}"


def _dec(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except ArithmeticError:
        return None


class Database:
    def __init__(self, config: Config) -> None:
        self.config = config
        self._conn: aiosqlite.Connection | None = None
        self._cache: dict[int, UserPrefs] = {}

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self.config.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA busy_timeout=5000")
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("数据库尚未连接")
        return self._conn

    # --- 用户偏好 -----------------------------------------------------------

    def _row_to_prefs(self, row: aiosqlite.Row) -> UserPrefs:
        favorites = [c for c in str(row["favorites"]).split(",") if c]
        return UserPrefs(
            user_id=row["user_id"],
            lang=row["lang"],
            base=row["base"],
            favorites=favorites,
            decimals=row["decimals"],
            group_sep=bool(row["group_sep"]),
            show_source=bool(row["show_source"]),
            show_change=bool(row["show_change"]),
            tz=row["tz"],
            fee_percent=_dec(row["fee_percent"]),
        )

    async def get_prefs(self, user_id: int, *, lang_hint: str | None = None) -> UserPrefs:
        if user_id in self._cache:
            return self._cache[user_id]
        async with self.conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
        if row is None:
            prefs = UserPrefs(
                user_id=user_id,
                lang=(lang_hint or self.config.default_lang),
                base=self.config.default_base,
                favorites=list(self.config.default_favorites),
                decimals=self.config.default_decimals,
                tz=self.config.default_tz,
            )
            await self.save_prefs(prefs)
        else:
            prefs = self._row_to_prefs(row)
        self._cache[user_id] = prefs
        return prefs

    async def save_prefs(self, prefs: UserPrefs) -> None:
        now = time.time()
        await self.conn.execute(
            """
            INSERT INTO users (user_id, lang, base, favorites, decimals, group_sep,
                               show_source, show_change, tz, fee_percent, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET
                lang=excluded.lang, base=excluded.base, favorites=excluded.favorites,
                decimals=excluded.decimals, group_sep=excluded.group_sep,
                show_source=excluded.show_source, show_change=excluded.show_change,
                tz=excluded.tz, fee_percent=excluded.fee_percent, updated_at=excluded.updated_at
            """,
            (
                prefs.user_id, prefs.lang, prefs.base.upper(), ",".join(prefs.favorites),
                prefs.decimals, int(prefs.group_sep), int(prefs.show_source), int(prefs.show_change),
                prefs.tz, str(prefs.fee_percent or ""), now, now,
            ),
        )
        await self.conn.commit()
        self._cache[prefs.user_id] = prefs

    async def update_prefs(self, user_id: int, **changes: Any) -> UserPrefs:
        prefs = await self.get_prefs(user_id)
        updated = replace(prefs, **changes)
        await self.save_prefs(updated)
        return updated

    # --- 使用记录（用于个性化建议） -----------------------------------------

    async def note_usage(self, user_id: int, codes: Iterable[str]) -> None:
        now = time.time()
        rows = [(user_id, code.upper(), now) for code in set(codes)]
        if not rows:
            return
        await self.conn.executemany(
            """
            INSERT INTO usage (user_id, code, hits, last_used) VALUES (?,?,1,?)
            ON CONFLICT(user_id, code) DO UPDATE SET hits = hits + 1, last_used = excluded.last_used
            """,
            rows,
        )
        await self.conn.commit()

    async def top_codes(self, user_id: int, limit: int = 8) -> list[str]:
        async with self.conn.execute(
            "SELECT code FROM usage WHERE user_id = ? ORDER BY hits DESC, last_used DESC LIMIT ?",
            (user_id, limit),
        ) as cursor:
            return [row["code"] for row in await cursor.fetchall()]

    # --- 提醒 ---------------------------------------------------------------

    async def add_alert(
        self,
        user_id: int,
        chat_id: int,
        base: str,
        quote: str,
        op: str,
        threshold: Decimal,
        *,
        repeat: bool = False,
        baseline: Decimal | None = None,
    ) -> int:
        cursor = await self.conn.execute(
            """
            INSERT INTO alerts (user_id, chat_id, base, quote, op, threshold, repeat, active, baseline, created_at)
            VALUES (?,?,?,?,?,?,?,1,?,?)
            """,
            (
                user_id, chat_id, base.upper(), quote.upper(), op, str(threshold),
                int(repeat), str(baseline or ""), time.time(),
            ),
        )
        await self.conn.commit()
        return int(cursor.lastrowid or 0)

    def _row_to_alert(self, row: aiosqlite.Row) -> Alert:
        return Alert(
            id=row["id"], user_id=row["user_id"], chat_id=row["chat_id"],
            base=row["base"], quote=row["quote"], op=row["op"],
            threshold=_dec(row["threshold"]) or Decimal(0), repeat=bool(row["repeat"]),
            active=bool(row["active"]), baseline=_dec(row["baseline"]),
            created_at=row["created_at"], last_fired_at=row["last_fired_at"],
        )

    async def list_alerts(self, user_id: int | None = None, *, only_active: bool = True) -> list[Alert]:
        sql = "SELECT * FROM alerts WHERE 1=1"
        args: list[Any] = []
        if user_id is not None:
            sql += " AND user_id = ?"
            args.append(user_id)
        if only_active:
            sql += " AND active = 1"
        sql += " ORDER BY id"
        async with self.conn.execute(sql, args) as cursor:
            return [self._row_to_alert(row) for row in await cursor.fetchall()]

    async def count_alerts(self, user_id: int) -> int:
        async with self.conn.execute(
            "SELECT COUNT(*) AS n FROM alerts WHERE user_id = ? AND active = 1", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return int(row["n"]) if row else 0

    async def mark_alert_fired(self, alert: Alert, *, deactivate: bool, baseline: Decimal | None = None) -> None:
        await self.conn.execute(
            "UPDATE alerts SET last_fired_at = ?, active = ?, baseline = ? WHERE id = ?",
            (time.time(), 0 if deactivate else 1, str(baseline or alert.baseline or ""), alert.id),
        )
        await self.conn.commit()

    async def delete_alert(self, user_id: int, alert_id: int) -> bool:
        cursor = await self.conn.execute(
            "DELETE FROM alerts WHERE id = ? AND user_id = ?", (alert_id, user_id)
        )
        await self.conn.commit()
        return cursor.rowcount > 0

    async def clear_alerts(self, user_id: int) -> int:
        cursor = await self.conn.execute("DELETE FROM alerts WHERE user_id = ?", (user_id,))
        await self.conn.commit()
        return cursor.rowcount

    # --- 定时播报 -----------------------------------------------------------

    async def add_subscription(
        self, user_id: int, chat_id: int, base: str, quotes: Sequence[str], at_time: str, tz: str
    ) -> int:
        cursor = await self.conn.execute(
            """
            INSERT INTO subscriptions (user_id, chat_id, base, quotes, at_time, tz, active, created_at)
            VALUES (?,?,?,?,?,?,1,?)
            """,
            (user_id, chat_id, base.upper(), ",".join(q.upper() for q in quotes), at_time, tz, time.time()),
        )
        await self.conn.commit()
        return int(cursor.lastrowid or 0)

    def _row_to_sub(self, row: aiosqlite.Row) -> Subscription:
        return Subscription(
            id=row["id"], user_id=row["user_id"], chat_id=row["chat_id"], base=row["base"],
            quotes=[q for q in str(row["quotes"]).split(",") if q], at_time=row["at_time"],
            tz=row["tz"], active=bool(row["active"]), last_sent=row["last_sent"],
            created_at=row["created_at"],
        )

    async def list_subscriptions(self, user_id: int | None = None, *, only_active: bool = True) -> list[Subscription]:
        sql = "SELECT * FROM subscriptions WHERE 1=1"
        args: list[Any] = []
        if user_id is not None:
            sql += " AND user_id = ?"
            args.append(user_id)
        if only_active:
            sql += " AND active = 1"
        sql += " ORDER BY at_time, id"
        async with self.conn.execute(sql, args) as cursor:
            return [self._row_to_sub(row) for row in await cursor.fetchall()]

    async def count_subscriptions(self, user_id: int) -> int:
        async with self.conn.execute(
            "SELECT COUNT(*) AS n FROM subscriptions WHERE user_id = ? AND active = 1", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return int(row["n"]) if row else 0

    async def mark_sub_sent(self, sub_id: int, day: str) -> None:
        await self.conn.execute("UPDATE subscriptions SET last_sent = ? WHERE id = ?", (day, sub_id))
        await self.conn.commit()

    async def delete_subscription(self, user_id: int, sub_id: int) -> bool:
        cursor = await self.conn.execute(
            "DELETE FROM subscriptions WHERE id = ? AND user_id = ?", (sub_id, user_id)
        )
        await self.conn.commit()
        return cursor.rowcount > 0

    async def deactivate_for_chat(self, chat_id: int) -> None:
        """用户把 bot 拉黑或踢出群时，停掉所有推送。"""
        await self.conn.execute("UPDATE alerts SET active = 0 WHERE chat_id = ?", (chat_id,))
        await self.conn.execute("UPDATE subscriptions SET active = 0 WHERE chat_id = ?", (chat_id,))
        await self.conn.commit()

    # --- 统计 ---------------------------------------------------------------

    async def stats(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for key, sql in (
            ("users", "SELECT COUNT(*) AS n FROM users"),
            ("alerts", "SELECT COUNT(*) AS n FROM alerts WHERE active = 1"),
            ("subscriptions", "SELECT COUNT(*) AS n FROM subscriptions WHERE active = 1"),
        ):
            async with self.conn.execute(sql) as cursor:
                row = await cursor.fetchone()
            out[key] = int(row["n"]) if row else 0
        return out


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
