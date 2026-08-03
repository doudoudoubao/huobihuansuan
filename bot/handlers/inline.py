"""Inline 模式：在任何聊天里 `@bot 100 usd jpy` 直接发结果。"""

from __future__ import annotations

import logging

from aiogram import Router
from aiogram.types import (
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
)

from .. import currencies as cur_mod
from .. import formatting as fmt
from ..db import UserPrefs
from ..i18n import t
from ..parser import parse
from ..rates.service import RateService, RateUnavailable

log = logging.getLogger(__name__)

router = Router(name="inline")

MAX_RESULTS = 12


def _article(
    result_id: str,
    title: str,
    description: str,
    text: str,
    thumb: str | None = None,
) -> InlineQueryResultArticle:
    return InlineQueryResultArticle(
        id=result_id,
        title=title,
        description=description,
        input_message_content=InputTextMessageContent(
            message_text=text, parse_mode="HTML", disable_web_page_preview=True
        ),
    )


@router.inline_query()
async def on_inline(query: InlineQuery, prefs: UserPrefs, rates: RateService) -> None:
    text = (query.query or "").strip()
    lang = prefs.lang

    if not text:
        await query.answer(
            [
                _article(
                    "empty",
                    t(lang, "inline_empty_title"),
                    t(lang, "inline_empty_desc"),
                    "💱 " + t(lang, "inline_empty_title"),
                )
            ],
            cache_time=30,
            is_personal=True,
        )
        return

    parsed = parse(text, context_currency=prefs.base)
    if parsed.error or not parsed.is_actionable:
        await query.answer(
            [_article("nomatch", t(lang, "no_match").split("\n")[0], text, t(lang, "no_match"))],
            cache_time=10,
            is_personal=True,
        )
        return

    source = parsed.source or prefs.base
    targets = [c for c in parsed.targets if c != source] or prefs.targets_for(source, limit=MAX_RESULTS)
    fee = parsed.fee_percent if parsed.fee_percent is not None else prefs.fee_percent
    rates.note_usage([source, *targets])

    articles: list[InlineQueryResultArticle] = []
    for quote in targets[:MAX_RESULTS]:
        try:
            conv = rates.convert(parsed.amount, source, quote, fee_percent=fee)
        except RateUnavailable:
            continue
        quote_meta = cur_mod.get(quote)
        amount_text = fmt.fmt_money(conv.amount, source, prefs)
        result_text = fmt.fmt_money(conv.result, quote, prefs)
        articles.append(
            _article(
                f"{source}-{quote}",
                f"{quote_meta.flag} " + t(lang, "inline_title", amount=amount_text, base=source, result=result_text, quote=quote),
                t(
                    lang,
                    "inline_desc",
                    base=source,
                    rate=fmt.fmt_rate(conv.rate.value, prefs),
                    quote=quote,
                    ago=fmt.fmt_ago(conv.rate.age, lang),
                ),
                fmt.render_conversion(conv, prefs, change_24h=rates.change_percent(source, quote)),
            )
        )

    if not articles:
        await query.answer(
            [_article("unavailable", t(lang, "unavailable", code=source).replace("<b>", "").replace("</b>", ""), "", t(lang, "unavailable", code=source))],
            cache_time=10,
            is_personal=True,
        )
        return

    # 追加一条“全部币种汇总”，方便一次贴出多条结果
    conversions, missing = rates.convert_many(parsed.amount, source, targets[:8], fee_percent=fee)
    if len(conversions) > 1:
        summary = fmt.render_multi(
            parsed.amount, source, conversions, prefs, missing=missing, fee_percent=fee,
            expression=parsed.expression,
        )
        articles.insert(
            0,
            _article(
                "summary",
                f"📋 {fmt.fmt_money(parsed.amount, source, prefs)} {source} → "
                + "/".join(c.quote for c in conversions[:4])
                + ("…" if len(conversions) > 4 else ""),
                t(lang, "inline_desc", base=source, rate=fmt.fmt_rate(conversions[0].rate.value, prefs),
                  quote=conversions[0].quote, ago=fmt.fmt_ago(conversions[0].rate.age, lang)),
                summary,
            ),
        )

    await query.answer(articles[:MAX_RESULTS + 1], cache_time=15, is_personal=True)
