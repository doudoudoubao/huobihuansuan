"""行情类命令：/rate /chart /hist /search /list /refresh /status。"""

from __future__ import annotations

import logging
import re
from datetime import date
from decimal import Decimal

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from .. import chart as chart_mod
from .. import currencies as cur_mod
from .. import formatting as fmt
from .. import keyboards as kb
from ..db import Database, UserPrefs
from ..i18n import t
from ..parser import parse_pair
from ..rates.base import ProviderError
from ..rates.service import RateService, RateUnavailable
from .utils import command_args, safe_edit

log = logging.getLogger(__name__)

router = Router(name="market")

_DATE_RE = re.compile(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})")


async def _send_rate(target: Message | CallbackQuery, base: str, quote: str, prefs: UserPrefs, rates: RateService) -> None:
    try:
        rate = rates.get_rate(base, quote)
    except RateUnavailable as exc:
        text = t(prefs.lang, "unavailable", code=exc.code)
        if isinstance(target, CallbackQuery):
            await target.answer(text.replace("<b>", "").replace("</b>", ""), show_alert=True)
        else:
            await target.answer(text)
        return
    rates.note_usage([base, quote])
    text = fmt.render_rate(
        rate,
        prefs,
        change_24h=rates.change_percent(base, quote, 86400),
        change_1h=rates.change_percent(base, quote, 3600),
    )
    keyboard = kb.rate_keyboard(base, quote, prefs)
    if isinstance(target, CallbackQuery):
        if target.message:
            await safe_edit(target.message, text, keyboard)  # type: ignore[arg-type]
        await target.answer()
    else:
        await target.answer(text, reply_markup=keyboard, disable_web_page_preview=True)


@router.message(Command("rate", "r", "hl"))
async def cmd_rate(message: Message, prefs: UserPrefs, rates: RateService) -> None:
    args = command_args(message)
    base, quote = parse_pair(
        args,
        default_source=prefs.favorites[0] if prefs.favorites else "USD",
        default_target=prefs.base,
    )
    await _send_rate(message, base, quote, prefs, rates)


@router.callback_query(F.data.startswith("rate|"))
async def cb_rate(query: CallbackQuery, prefs: UserPrefs, rates: RateService) -> None:
    _, parts = kb.unpack(query.data or "")
    if len(parts) < 2:
        await query.answer()
        return
    await _send_rate(query, parts[0], parts[1], prefs, rates)


# --- 走势图 -----------------------------------------------------------------


def _extract_days(text: str, default: int = 30) -> int:
    numbers = [int(m) for m in re.findall(r"\b(\d{1,4})\b", text)]
    for number in numbers:
        if 2 <= number <= 1825:
            return number
    return default


async def _send_chart(message: Message, base: str, quote: str, days: int, prefs: UserPrefs, rates: RateService) -> None:
    placeholder = await message.answer("📈 …")
    try:
        series = await rates.history(base, quote, days)
    except (ProviderError, RateUnavailable) as exc:
        await safe_edit(placeholder, t(prefs.lang, "chart_failed", base=base, quote=quote, reason=fmt.esc(exc)))
        return
    if len(series) > days + 5:
        series = series[-(days + 1):]

    high, low, change = chart_mod.summarize(series)
    caption_lines = [
        t(prefs.lang, "chart_title", base=base, quote=quote, days=days),
        t(
            prefs.lang,
            "chart_stats",
            high=fmt.fmt_rate(high, prefs),
            low=fmt.fmt_rate(low, prefs),
            change=fmt.fmt_number(change, decimals=2, group=False, min_decimals=2),
        ),
        f"<b>1 {base} = {fmt.fmt_rate(series[-1][1], prefs)} {quote}</b>　({series[-1][0].isoformat()})",
    ]
    caption = "\n".join(caption_lines)
    png = chart_mod.render_series(series, base, quote, days)
    keyboard = kb.chart_keyboard(base, quote, days, prefs)

    if png:
        await message.answer_photo(
            BufferedInputFile(png, filename=f"{base}{quote}_{days}d.png"),
            caption=caption,
            reply_markup=keyboard,
        )
        try:
            await placeholder.delete()
        except Exception:  # noqa: BLE001
            pass
    else:
        # 没装 matplotlib 时退化成文字版迷你走势
        spark = _sparkline([value for _, value in series])
        await safe_edit(placeholder, f"{caption}\n<code>{spark}</code>", keyboard)


_SPARK_CHARS = "▁▂▃▄▅▆▇█"


def _sparkline(values: list[Decimal], width: int = 40) -> str:
    if len(values) < 2:
        return ""
    if len(values) > width:
        step = len(values) / width
        values = [values[int(i * step)] for i in range(width)]
    low, high = min(values), max(values)
    span = high - low
    if span == 0:
        return _SPARK_CHARS[0] * len(values)
    return "".join(
        _SPARK_CHARS[min(len(_SPARK_CHARS) - 1, int((v - low) / span * (len(_SPARK_CHARS) - 1)))]
        for v in values
    )


@router.message(Command("chart", "k", "trend"))
async def cmd_chart(message: Message, prefs: UserPrefs, rates: RateService) -> None:
    args = command_args(message)
    if not args:
        await message.answer(t(prefs.lang, "usage_chart"))
        return
    base, quote = parse_pair(
        args, default_source=prefs.favorites[0] if prefs.favorites else "USD", default_target=prefs.base
    )
    await _send_chart(message, base, quote, _extract_days(args), prefs, rates)


@router.callback_query(F.data.startswith("ch|"))
async def cb_chart(query: CallbackQuery, prefs: UserPrefs, rates: RateService) -> None:
    _, parts = kb.unpack(query.data or "")
    if len(parts) < 2 or not query.message:
        await query.answer()
        return
    days = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 30
    await query.answer("📈 …")
    await _send_chart(query.message, parts[0], parts[1], days, prefs, rates)  # type: ignore[arg-type]


# --- 历史某天 ---------------------------------------------------------------


@router.message(Command("hist", "history", "h"))
async def cmd_hist(message: Message, prefs: UserPrefs, rates: RateService) -> None:
    args = command_args(message)
    match = _DATE_RE.search(args)
    if not args or not match:
        await message.answer(t(prefs.lang, "usage_hist"))
        return
    try:
        day = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        await message.answer(t(prefs.lang, "usage_hist"))
        return
    if day > date.today():
        day = date.today()

    remainder = _DATE_RE.sub(" ", args)
    base, quote = parse_pair(
        remainder, default_source=prefs.favorites[0] if prefs.favorites else "USD", default_target=prefs.base
    )
    try:
        found_day, value = await rates.rate_on(base, quote, day)
        today_rate = rates.get_rate(base, quote)
    except (ProviderError, RateUnavailable) as exc:
        await message.answer(t(prefs.lang, "chart_failed", base=base, quote=quote, reason=fmt.esc(exc)))
        return

    change = (today_rate.value - value) / value * Decimal(100) if value else Decimal(0)
    await message.answer(
        t(
            prefs.lang,
            "hist_result",
            day=found_day.isoformat(),
            base=base,
            quote=quote,
            rate=fmt.fmt_rate(value, prefs),
            today=fmt.fmt_rate(today_rate.value, prefs),
            change=("+" if change >= 0 else "") + fmt.fmt_number(change, decimals=2, group=False, min_decimals=2),
        ),
        reply_markup=kb.rate_keyboard(base, quote, prefs),
    )


# --- 货币检索 ---------------------------------------------------------------


@router.message(Command("search", "find", "s"))
async def cmd_search(message: Message, prefs: UserPrefs) -> None:
    query = command_args(message)
    items = cur_mod.search(query, limit=25)
    if not items:
        await message.answer(t(prefs.lang, "search_none", q=fmt.esc(query)))
        return
    await message.answer(
        fmt.render_currency_list(items, prefs.lang, title=t(prefs.lang, "search_title", q=fmt.esc(query))),
        disable_web_page_preview=True,
    )


@router.message(Command("list", "currencies"))
async def cmd_list(message: Message, prefs: UserPrefs, rates: RateService) -> None:
    available = rates.available_codes()
    fiat = [cur_mod.get(c) for c in sorted(cur_mod.FIAT_CODES & available)]
    crypto = [cur_mod.get(c) for c in sorted(cur_mod.CRYPTO_CODES & available)]
    metal = [cur_mod.get(c) for c in sorted(cur_mod.METAL_CODES & available)]
    total = len(fiat) + len(crypto) + len(metal)

    chunks: list[str] = [t(prefs.lang, "list_title", n=total), ""]
    chunks.append("💵 " + " ".join(f"{c.flag}{c.code}" for c in fiat))
    if crypto:
        chunks.append("")
        chunks.append("🪙 " + " ".join(c.code for c in crypto))
    if metal:
        chunks.append("")
        chunks.append("🥇 " + " ".join(c.code for c in metal))
    chunks.append("")
    chunks.append("<i>/search 关键词　查具体货币</i>" if prefs.lang == "zh" else "<i>/search &lt;keyword&gt;</i>")

    text = "\n".join(chunks)
    for part in _split_message(text):
        await message.answer(part, disable_web_page_preview=True)


def _split_message(text: str, limit: int = 3900) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    buffer = ""
    for line in text.split("\n"):
        if len(buffer) + len(line) + 1 > limit:
            parts.append(buffer)
            buffer = ""
        buffer += line + "\n"
    if buffer.strip():
        parts.append(buffer)
    return parts


# --- 运维 -------------------------------------------------------------------


@router.message(Command("refresh", "sync"))
async def cmd_refresh(message: Message, prefs: UserPrefs, rates: RateService) -> None:
    count = await rates.force_refresh()
    await message.answer(
        t(prefs.lang, "refreshed", n=count) if count else t(prefs.lang, "refresh_failed")
    )


@router.message(Command("status", "health"))
async def cmd_status(message: Message, prefs: UserPrefs, rates: RateService, db: Database) -> None:
    lines = [t(prefs.lang, "status_title"), ""]
    for row in rates.status():
        mark = "🟢" if row["healthy"] and row["currencies"] else "🔴"
        age = f"{row['age']:.0f}s" if row["age"] is not None else "—"
        lines.append(
            f"{mark} <code>{row['name']:<13}</code> {row['kind']:<6} "
            f"{row['currencies']:>3} 项 · {age}"
        )
        if row["error"]:
            lines.append(f"　　<i>{fmt.esc(row['error'][:80])}</i>")
    stats = await db.stats()
    lines.append("")
    lines.append(
        f"👤 {stats['users']} · 🔔 {stats['alerts']} · 📅 {stats['subscriptions']}"
    )
    await message.answer("\n".join(lines), disable_web_page_preview=True)
