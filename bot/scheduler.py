"""后台任务：到价提醒巡检 + 每日定时播报。"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter

from . import currencies as cur_mod
from . import formatting as fmt
from .config import Config
from .db import Alert, Database, Subscription
from .i18n import t
from .rates.service import RateService, RateUnavailable

log = logging.getLogger(__name__)

ALERT_COOLDOWN = 3600.0  # 同一条重复提醒之间的最小间隔
DIGEST_CATCHUP_MINUTES = 15  # 服务重启后允许补发的时间窗


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


class Scheduler:
    def __init__(self, bot: Bot, db: Database, rates: RateService, config: Config) -> None:
        self.bot = bot
        self.db = db
        self.rates = rates
        self.config = config
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        self._tasks = [
            asyncio.create_task(self._alert_loop(), name="alerts"),
            asyncio.create_task(self._digest_loop(), name="digests"),
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

    # --- 发送 ---------------------------------------------------------------

    async def _send(self, chat_id: int, text: str) -> bool:
        try:
            await self.bot.send_message(chat_id, text, disable_web_page_preview=True)
            return True
        except TelegramForbiddenError:
            log.info("chat %s 已屏蔽 bot，停用其推送", chat_id)
            await self.db.deactivate_for_chat(chat_id)
            return False
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after + 1)
            return False
        except Exception:  # noqa: BLE001
            log.exception("向 chat %s 推送失败", chat_id)
            return False

    # --- 到价提醒 -----------------------------------------------------------

    async def _alert_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(max(15, self.config.alert_check_seconds))
                await self.check_alerts()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("提醒巡检出错")

    async def check_alerts(self) -> int:
        alerts = await self.db.list_alerts(only_active=True)
        fired = 0
        for alert in alerts:
            try:
                if await self._evaluate(alert):
                    fired += 1
            except Exception:  # noqa: BLE001
                log.exception("处理提醒 #%s 失败", alert.id)
        return fired

    async def _evaluate(self, alert: Alert) -> bool:
        try:
            rate = self.rates.get_rate(alert.base, alert.quote)
        except RateUnavailable:
            return False

        prefs = await self.db.get_prefs(alert.user_id)
        current_text = f"1 {alert.base} = {fmt.fmt_rate(rate.value, prefs)} {alert.quote}"

        if alert.op == "pct":
            baseline = alert.baseline or rate.value
            if baseline == 0:
                return False
            change = (rate.value - baseline) / baseline * Decimal(100)
            if abs(change) < alert.threshold:
                return False
            if time.time() - alert.last_fired_at < ALERT_COOLDOWN:
                return False
            text = t(
                prefs.lang,
                "alert_fired_pct",
                pair=f"{alert.base}/{alert.quote}",
                change=("+" if change >= 0 else "") + fmt.fmt_number(change, decimals=2, group=False, min_decimals=2),
                current=current_text,
            )
            if await self._send(alert.chat_id, text):
                await self.db.mark_alert_fired(alert, deactivate=False, baseline=rate.value)
                return True
            return False

        hit = (alert.op == ">" and rate.value >= alert.threshold) or (
            alert.op == "<" and rate.value <= alert.threshold
        )
        if not hit:
            return False
        if alert.repeat and time.time() - alert.last_fired_at < ALERT_COOLDOWN:
            return False

        text = t(prefs.lang, "alert_fired", desc=fmt.esc(alert.describe()), current=current_text)
        if await self._send(alert.chat_id, text):
            await self.db.mark_alert_fired(alert, deactivate=not alert.repeat)
            return True
        return False

    # --- 每日播报 -----------------------------------------------------------

    async def _digest_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(45)
                await self.check_digests()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("定时播报巡检出错")

    async def check_digests(self) -> int:
        subs = await self.db.list_subscriptions(only_active=True)
        sent = 0
        for sub in subs:
            try:
                if await self._maybe_send_digest(sub):
                    sent += 1
            except Exception:  # noqa: BLE001
                log.exception("处理订阅 #%s 失败", sub.id)
        return sent

    async def _maybe_send_digest(self, sub: Subscription) -> bool:
        now = datetime.now(_zone(sub.tz))
        today = now.date().isoformat()
        if sub.last_sent == today:
            return False
        try:
            hour, minute = (int(x) for x in sub.at_time.split(":"))
        except ValueError:
            return False
        due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        elapsed = (now - due).total_seconds()
        if elapsed < 0 or elapsed > DIGEST_CATCHUP_MINUTES * 60:
            return False

        prefs = await self.db.get_prefs(sub.user_id)
        conversions, missing = self.rates.convert_many(Decimal(1), sub.base, sub.quotes)
        if not conversions:
            return False

        base_meta = cur_mod.get(sub.base)
        lines = [
            t(prefs.lang, "daily_title"),
            f"{now.strftime('%Y-%m-%d %H:%M')} ({fmt.esc(sub.tz)})",
            "",
            f"{base_meta.flag} <b>1 {fmt.esc(sub.base)}</b> =",
        ]
        for conv in conversions:
            quote_meta = cur_mod.get(conv.quote)
            change = self.rates.change_percent(sub.base, conv.quote)
            change_text = f"　{fmt.fmt_change(change, prefs.lang)}" if change is not None else ""
            lines.append(
                f"{quote_meta.flag} <code>{fmt.esc(conv.quote)}</code>  "
                f"<b>{fmt.esc(fmt.fmt_rate(conv.rate.value, prefs))}</b>{fmt.esc(change_text)}"
            )
        if missing:
            lines.append(f"<i>⚠️ {fmt.esc('/'.join(missing))}</i>")
        lines.append("")
        lines.append(f"<i>{fmt.esc(fmt.fmt_ago(conversions[0].rate.age, prefs.lang))}</i>")

        if await self._send(sub.chat_id, "\n".join(lines)):
            await self.db.mark_sub_sent(sub.id, today)
            return True
        return False
