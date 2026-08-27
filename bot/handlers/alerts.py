"""到价提醒与每日播报的命令处理。"""

from __future__ import annotations

import logging
import re
from decimal import Decimal, InvalidOperation

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from .. import formatting as fmt
from .. import keyboards as kb
from ..config import Config
from ..db import Database, UserPrefs
from ..i18n import t
from ..parser import parse_currency_list
from ..rates.service import RateService, RateUnavailable
from .utils import command_args

log = logging.getLogger(__name__)

router = Router(name="alerts")

_OP_RE = re.compile(r"(?P<op>>=|<=|>|<|≥|≤|%|％)\s*(?P<value>\d+(?:\.\d+)?)")
_BARE_NUM_RE = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)(?![\d.]*\s*[%％])")
_TIME_RE = re.compile(r"\b([01]?\d|2[0-3])\s*[:：.]\s*([0-5]\d)\b")


def _parse_alert(args: str) -> tuple[str | None, Decimal | None, str]:
    """返回 (操作符, 阈值, 去掉条件后的剩余文本)。"""
    match = _OP_RE.search(args)
    if match:
        raw_op = match.group("op")
        op = "pct" if raw_op in ("%", "％") else (">" if raw_op in (">", "≥", ">=") else "<")
        try:
            value = Decimal(match.group("value"))
        except InvalidOperation:
            return None, None, args
        return op, value, (args[: match.start()] + " " + args[match.end() :])

    bare = _BARE_NUM_RE.search(args)
    if bare:
        try:
            value = Decimal(bare.group(1))
        except InvalidOperation:
            return None, None, args
        return "auto", value, (args[: bare.start()] + " " + args[bare.end() :])
    return None, None, args


@router.message(Command("alert", "notify", "tx"))
async def cmd_alert(
    message: Message, prefs: UserPrefs, rates: RateService, db: Database, config: Config
) -> None:
    args = command_args(message)
    if not args:
        await message.answer(t(prefs.lang, "usage_alert"))
        return

    op, threshold, remainder = _parse_alert(args)
    codes = parse_currency_list(remainder, limit=2)
    if op is None or threshold is None or not codes:
        await message.answer(t(prefs.lang, "usage_alert"))
        return

    base = codes[0]
    quote = codes[1] if len(codes) > 1 else prefs.base
    if base == quote:
        await message.answer(t(prefs.lang, "same_currency", code=base))
        return

    if await db.count_alerts(prefs.user_id) >= config.max_alerts_per_user:
        await message.answer(t(prefs.lang, "alert_limit", n=config.max_alerts_per_user))
        return

    try:
        rate = rates.get_rate(base, quote)
    except RateUnavailable as exc:
        await message.answer(t(prefs.lang, "unavailable", code=exc.code))
        return

    if op == "auto":
        op = ">" if threshold > rate.value else "<"
    baseline = rate.value if op == "pct" else None

    alert_id = await db.add_alert(
        prefs.user_id,
        message.chat.id,
        base,
        quote,
        op,
        threshold,
        repeat=(op == "pct"),
        baseline=baseline,
    )
    alerts = await db.list_alerts(prefs.user_id)
    created = next((a for a in alerts if a.id == alert_id), None)
    desc = created.describe() if created else f"{base}/{quote}"
    await message.answer(
        t(
            prefs.lang,
            "alert_added",
            id=alert_id,
            desc=fmt.esc(desc),
            current=f"1 {base} = {fmt.fmt_rate(rate.value, prefs)} {quote}",
        )
    )


@router.message(Command("alerts", "myalerts"))
async def cmd_alerts(message: Message, prefs: UserPrefs, db: Database) -> None:
    alerts = await db.list_alerts(prefs.user_id)
    if not alerts:
        await message.answer(t(prefs.lang, "alert_none"))
        return
    lines = [t(prefs.lang, "alert_list_title"), ""]
    for alert in alerts:
        repeat = "🔁" if alert.repeat else "1️⃣"
        lines.append(f"<code>#{alert.id}</code> {repeat} {fmt.esc(alert.describe())}")
    await message.answer(
        "\n".join(lines), reply_markup=kb.alerts_keyboard([a.id for a in alerts], prefs.lang)
    )


@router.message(Command("delalert", "rmalert"))
async def cmd_delalert(message: Message, prefs: UserPrefs, db: Database) -> None:
    args = command_args(message).strip()
    if args.lower() in ("all", "全部", "*"):
        count = await db.clear_alerts(prefs.user_id)
        await message.answer(t(prefs.lang, "alert_cleared", n=count))
        return
    ids = [int(x) for x in re.findall(r"\d+", args)]
    if not ids:
        await message.answer(t(prefs.lang, "usage_alert"))
        return
    for alert_id in ids:
        ok = await db.delete_alert(prefs.user_id, alert_id)
        await message.answer(
            t(prefs.lang, "alert_deleted" if ok else "alert_not_found", id=alert_id)
        )


@router.callback_query(F.data.startswith("aldel|"))
async def cb_alert_delete(query: CallbackQuery, prefs: UserPrefs, db: Database) -> None:
    _, parts = kb.unpack(query.data or "")
    if not parts or not parts[0].isdigit():
        await query.answer()
        return
    alert_id = int(parts[0])
    ok = await db.delete_alert(prefs.user_id, alert_id)
    alerts = await db.list_alerts(prefs.user_id)
    if query.message:
        if alerts:
            lines = [t(prefs.lang, "alert_list_title"), ""]
            for alert in alerts:
                repeat = "🔁" if alert.repeat else "1️⃣"
                lines.append(f"<code>#{alert.id}</code> {repeat} {fmt.esc(alert.describe())}")
            await query.message.edit_text(  # type: ignore[union-attr]
                "\n".join(lines), reply_markup=kb.alerts_keyboard([a.id for a in alerts], prefs.lang)
            )
        else:
            await query.message.edit_text(t(prefs.lang, "alert_none"))  # type: ignore[union-attr]
    await query.answer(t(prefs.lang, "alert_deleted" if ok else "alert_not_found", id=alert_id))


# --- 每日播报 ---------------------------------------------------------------


@router.message(Command("subscribe", "sub", "daily"))
async def cmd_subscribe(
    message: Message, prefs: UserPrefs, db: Database, config: Config
) -> None:
    args = command_args(message)
    if not args:
        await message.answer(t(prefs.lang, "usage_sub"))
        return
    match = _TIME_RE.search(args)
    if not match:
        await message.answer(t(prefs.lang, "usage_sub"))
        return
    at_time = f"{int(match.group(1)):02d}:{match.group(2)}"
    remainder = _TIME_RE.sub(" ", args)
    codes = parse_currency_list(remainder, limit=8)

    if codes:
        base, quotes = codes[0], codes[1:]
    else:
        base, quotes = prefs.base, []
    if not quotes:
        quotes = prefs.targets_for(base, limit=6)
    if not quotes:
        await message.answer(t(prefs.lang, "usage_sub"))
        return

    if await db.count_subscriptions(prefs.user_id) >= config.max_subs_per_user:
        await message.answer(t(prefs.lang, "sub_limit", n=config.max_subs_per_user))
        return

    sub_id = await db.add_subscription(prefs.user_id, message.chat.id, base, quotes, at_time, prefs.tz)
    desc = f"每天 {at_time} 播报 {base} → {'/'.join(quotes)}" if prefs.lang == "zh" else (
        f"daily at {at_time}: {base} → {'/'.join(quotes)}"
    )
    await message.answer(t(prefs.lang, "sub_added", id=sub_id, desc=fmt.esc(desc)))


@router.message(Command("subs", "mysubs", "subscriptions"))
async def cmd_subs(message: Message, prefs: UserPrefs, db: Database) -> None:
    subs = await db.list_subscriptions(prefs.user_id)
    if not subs:
        await message.answer(t(prefs.lang, "sub_none"))
        return
    lines = [t(prefs.lang, "sub_list_title"), ""]
    for sub in subs:
        lines.append(
            f"<code>#{sub.id}</code> 🕘 {sub.at_time} ({fmt.esc(sub.tz)})　"
            f"{fmt.esc(sub.base)} → {fmt.esc('/'.join(sub.quotes))}"
        )
    await message.answer("\n".join(lines), reply_markup=kb.subs_keyboard([s.id for s in subs], prefs.lang))


@router.message(Command("unsubscribe", "unsub"))
async def cmd_unsub(message: Message, prefs: UserPrefs, db: Database) -> None:
    ids = [int(x) for x in re.findall(r"\d+", command_args(message))]
    if not ids:
        await message.answer(t(prefs.lang, "usage_sub"))
        return
    for sub_id in ids:
        ok = await db.delete_subscription(prefs.user_id, sub_id)
        await message.answer(t(prefs.lang, "sub_deleted" if ok else "sub_not_found", id=sub_id))


@router.callback_query(F.data.startswith("subdel|"))
async def cb_sub_delete(query: CallbackQuery, prefs: UserPrefs, db: Database) -> None:
    _, parts = kb.unpack(query.data or "")
    if not parts or not parts[0].isdigit():
        await query.answer()
        return
    sub_id = int(parts[0])
    ok = await db.delete_subscription(prefs.user_id, sub_id)
    subs = await db.list_subscriptions(prefs.user_id)
    if query.message:
        if subs:
            lines = [t(prefs.lang, "sub_list_title"), ""]
            for sub in subs:
                lines.append(
                    f"<code>#{sub.id}</code> 🕘 {sub.at_time} ({fmt.esc(sub.tz)})　"
                    f"{fmt.esc(sub.base)} → {fmt.esc('/'.join(sub.quotes))}"
                )
            await query.message.edit_text(  # type: ignore[union-attr]
                "\n".join(lines), reply_markup=kb.subs_keyboard([s.id for s in subs], prefs.lang)
            )
        else:
            await query.message.edit_text(t(prefs.lang, "sub_none"))  # type: ignore[union-attr]
    await query.answer(t(prefs.lang, "sub_deleted" if ok else "sub_not_found", id=sub_id))
