"""中间件：用户偏好注入 + 轻量限流。"""

from __future__ import annotations

import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, InlineQuery, Message, TelegramObject, User

from .db import Database
from .i18n import normalize_lang


class PrefsMiddleware(BaseMiddleware):
    """把 UserPrefs 放进 handler 的 data 里，顺便按 Telegram 语言初始化。"""

    def __init__(self, db: Database) -> None:
        self.db = db

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        if user is not None and not user.is_bot:
            data["prefs"] = await self.db.get_prefs(
                user.id, lang_hint=normalize_lang(user.language_code)
            )
        return await handler(event, data)


class ThrottleMiddleware(BaseMiddleware):
    """同一用户的连续请求做最小间隔限制，避免长按刷新把数据源打爆。"""

    def __init__(self, interval: float = 0.4) -> None:
        self.interval = interval
        self._last: dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        now = time.monotonic()
        last = self._last.get(user.id, 0.0)
        if now - last < self.interval:
            if isinstance(event, CallbackQuery):
                await event.answer()
                return None
            if isinstance(event, (Message, InlineQuery)):
                return None
        self._last[user.id] = now

        if len(self._last) > 10000:
            cutoff = now - 300
            self._last = {uid: ts for uid, ts in self._last.items() if ts > cutoff}
        return await handler(event, data)
