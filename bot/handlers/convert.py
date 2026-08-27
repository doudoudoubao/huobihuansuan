"""自由文本换算 + 结果卡片上的按钮回调。"""

from __future__ import annotations

import logging
import re
from decimal import Decimal

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from .. import formatting as fmt
from .. import keyboards as kb
from ..config import Config
from ..db import Database, UserPrefs
from ..i18n import t
from ..rates.service import RateService, RateUnavailable
from .core import build_conversion, respond_to_text
from .utils import command_args, parse_decimal, safe_edit

log = logging.getLogger(__name__)

router = Router(name="convert")

# 群里只在这些情况下接话：@bot、回复 bot、或用 /c 命令
_MENTION_RE = re.compile(r"@([A-Za-z0-9_]{4,})")


@router.message(Command("convert", "c", "conv"))
async def cmd_convert(
    message: Message, prefs: UserPrefs, rates: RateService, db: Database, config: Config
) -> None:
    args = command_args(message)
    if not args:
        await message.answer(t(prefs.lang, "no_match"))
        return
    rendered = await respond_to_text(
        args, prefs, rates, db, target_count=config.multi_target_count
    )
    if rendered:
        await message.answer(rendered.text, reply_markup=rendered.keyboard, disable_web_page_preview=True)


@router.message(F.chat.type == ChatType.PRIVATE, F.text & ~F.text.startswith("/"))
async def on_private_text(
    message: Message, prefs: UserPrefs, rates: RateService, db: Database, config: Config
) -> None:
    rendered = await respond_to_text(
        message.text or "", prefs, rates, db, target_count=config.multi_target_count
    )
    if rendered is None:
        return
    await message.answer(rendered.text, reply_markup=rendered.keyboard, disable_web_page_preview=True)


@router.message(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}), F.text & ~F.text.startswith("/"))
async def on_group_text(
    message: Message, prefs: UserPrefs, rates: RateService, db: Database, config: Config
) -> None:
    """群聊里保持克制。

    @bot 或回复 bot 时按私聊规则处理；否则只回应「写明了源币种和目标币种」的
    换算式，别的消息一律沉默。
    """
    text = message.text or ""
    bot_user = await message.bot.me()
    mentioned = bool(bot_user.username and f"@{bot_user.username}".lower() in text.lower())
    replied_to_bot = bool(
        message.reply_to_message
        and message.reply_to_message.from_user
        and message.reply_to_message.from_user.id == bot_user.id
    )
    if mentioned:
        text = re.sub(rf"@{re.escape(bot_user.username or '')}", " ", text, flags=re.IGNORECASE)

    addressed = mentioned or replied_to_bot
    rendered = await respond_to_text(
        text,
        prefs,
        rates,
        db,
        quiet=not addressed,
        require_currency=True,
        require_target=not addressed,
        target_count=config.multi_target_count,
    )
    if rendered is None or not rendered.ok:
        return
    await message.reply(rendered.text, reply_markup=rendered.keyboard, disable_web_page_preview=True)


# --- 按钮回调 ---------------------------------------------------------------


@router.callback_query(F.data == "close")
async def cb_close(query: CallbackQuery) -> None:
    if query.message:
        try:
            await query.message.delete()
        except Exception:  # noqa: BLE001 - 超过 48 小时的消息删不掉
            await safe_edit(query.message, "✔️")  # type: ignore[arg-type]
    await query.answer()


@router.callback_query(F.data.startswith("cv|"))
async def cb_convert(query: CallbackQuery, prefs: UserPrefs, rates: RateService) -> None:
    _, parts = kb.unpack(query.data or "")
    if len(parts) < 2:
        await query.answer()
        return
    base, quote = parts[0], parts[1]
    amount = parse_decimal(parts[2]) if len(parts) > 2 else Decimal(1)
    rendered = await build_conversion(amount, base, [quote], prefs, rates)
    if query.message:
        await safe_edit(query.message, rendered.text, rendered.keyboard)  # type: ignore[arg-type]
    await query.answer()


@router.callback_query(F.data.startswith("rev|"))
async def cb_reverse(query: CallbackQuery, prefs: UserPrefs, rates: RateService) -> None:
    _, parts = kb.unpack(query.data or "")
    if len(parts) < 2:
        await query.answer()
        return
    base, quote = parts[1], parts[0]  # 交换
    amount = parse_decimal(parts[2]) if len(parts) > 2 else Decimal(1)
    rendered = await build_conversion(amount, base, [quote], prefs, rates)
    if query.message:
        await safe_edit(query.message, rendered.text, rendered.keyboard)  # type: ignore[arg-type]
    await query.answer("⇄")


@router.callback_query(F.data.startswith("ref|"))
async def cb_refresh(query: CallbackQuery, prefs: UserPrefs, rates: RateService) -> None:
    _, parts = kb.unpack(query.data or "")
    if len(parts) < 2:
        await query.answer()
        return
    base, quote = parts[0], parts[1]
    amount = parse_decimal(parts[2]) if len(parts) > 2 else Decimal(1)
    rates.note_usage([base, quote])
    count = await rates.force_refresh()
    rendered = await build_conversion(amount, base, [quote], prefs, rates)
    if query.message:
        await safe_edit(query.message, rendered.text, rendered.keyboard)  # type: ignore[arg-type]
    await query.answer(
        t(prefs.lang, "refreshed", n=count) if count else t(prefs.lang, "refresh_failed")
    )


@router.callback_query(F.data.startswith("multi|") | F.data.startswith("mref|"))
async def cb_multi(
    query: CallbackQuery, prefs: UserPrefs, rates: RateService, db: Database, config: Config
) -> None:
    """多币种速览：`multi` 展开更多币种，`mref` 强制刷新后重绘。"""
    action, parts = kb.unpack(query.data or "")
    if not parts:
        await query.answer()
        return
    base = parts[0]
    amount = parse_decimal(parts[1]) if len(parts) > 1 else Decimal(1)
    count = config.multi_target_count

    if action == "mref":
        targets = prefs.targets_for(base, limit=count)
    else:
        # 「更多币种」把最近用过的也并进来，铺得更满一些
        recent = await db.top_codes(prefs.user_id, limit=10) or []
        targets = [
            code
            for code in dict.fromkeys(prefs.targets_for(base, limit=count) + recent)
            if code != base
        ][: count + 5]

    rates.note_usage([base, *targets])
    refreshed = await rates.force_refresh() if action == "mref" else 0
    rendered = await build_conversion(amount, base, targets, prefs, rates)
    if query.message:
        await safe_edit(query.message, rendered.text, rendered.keyboard)  # type: ignore[arg-type]
    await query.answer(t(prefs.lang, "refreshed", n=refreshed) if action == "mref" else None)


@router.callback_query(F.data.startswith("al|"))
async def cb_alert_hint(query: CallbackQuery, prefs: UserPrefs, rates: RateService) -> None:
    """结果卡上的「提醒」按钮：给出可直接复制的命令。"""
    _, parts = kb.unpack(query.data or "")
    if len(parts) < 2:
        await query.answer()
        return
    base, quote = parts[0], parts[1]
    try:
        rate = rates.get_rate(base, quote)
    except RateUnavailable as exc:
        await query.answer(t(prefs.lang, "unavailable", code=exc.code), show_alert=True)
        return
    current = fmt.fmt_rate(rate.value, prefs)
    up = fmt.fmt_rate(rate.value * Decimal("1.01"), prefs)
    down = fmt.fmt_rate(rate.value * Decimal("0.99"), prefs)
    if prefs.lang == "zh":
        head = f"🔔 <b>{base}/{quote}</b> 现价 <b>{current}</b>\n\n复制下面任意一条发给我即可设提醒："
        tail = "　(24h 波动 1%)"
    else:
        head = f"🔔 <b>{base}/{quote}</b> is <b>{current}</b>\n\nSend any line below to create an alert:"
        tail = "　(24h move ≥ 1%)"
    text = (
        f"{head}\n"
        f"<code>/alert {base} {quote} &gt; {up}</code>\n"
        f"<code>/alert {base} {quote} &lt; {down}</code>\n"
        f"<code>/alert {base} {quote} %1</code>{tail}"
    )
    if query.message:
        await query.message.answer(text, disable_web_page_preview=True)  # type: ignore[union-attr]
    await query.answer()
