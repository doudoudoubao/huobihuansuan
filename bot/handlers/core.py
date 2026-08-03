"""换算流程的公共实现，被消息、按钮回调和 inline 模式共用。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from aiogram.types import InlineKeyboardMarkup

from .. import currencies as cur_mod
from .. import formatting as fmt
from .. import keyboards as kb
from ..db import Database, UserPrefs
from ..i18n import t
from ..parser import ParseResult, parse
from ..rates.service import Conversion, RateService, RateUnavailable

log = logging.getLogger(__name__)


@dataclass(slots=True)
class Rendered:
    text: str
    keyboard: InlineKeyboardMarkup | None = None
    single: Conversion | None = None
    ok: bool = True


def resolve_targets(result: ParseResult, prefs: UserPrefs, source: str) -> list[str]:
    targets = [code for code in result.targets if code != source]
    if targets:
        return targets
    return prefs.targets_for(source)


async def build_conversion(
    amount: Decimal,
    source: str,
    targets: Sequence[str],
    prefs: UserPrefs,
    rates: RateService,
    *,
    fee_percent: Decimal | None = None,
    expression: str | None = None,
    with_keyboard: bool = True,
) -> Rendered:
    """核心渲染：一个目标走详情卡片，多个目标走列表。"""
    source = source.upper()
    targets = [code.upper() for code in dict.fromkeys(targets) if code.upper() != source]

    if not targets:
        return Rendered(t(prefs.lang, "same_currency", code=source), ok=False)

    if len(targets) == 1:
        quote = targets[0]
        try:
            conv = rates.convert(amount, source, quote, fee_percent=fee_percent)
        except RateUnavailable as exc:
            return Rendered(t(prefs.lang, "unavailable", code=exc.code), ok=False)
        change = rates.change_percent(source, quote) if prefs.show_change else None
        text = fmt.render_conversion(conv, prefs, change_24h=change, expression=expression)
        keyboard = (
            kb.conversion_keyboard(source, quote, amount, prefs) if with_keyboard else None
        )
        return Rendered(text, keyboard, single=conv)

    conversions, missing = rates.convert_many(amount, source, targets, fee_percent=fee_percent)
    if not conversions:
        return Rendered(t(prefs.lang, "unavailable", code=missing[0] if missing else source), ok=False)
    text = fmt.render_multi(
        amount, source, conversions, prefs, missing=missing, fee_percent=fee_percent, expression=expression
    )
    keyboard = kb.multi_keyboard(source, amount, prefs) if with_keyboard else None
    return Rendered(text, keyboard)


async def respond_to_text(
    text: str,
    prefs: UserPrefs,
    rates: RateService,
    db: Database | None = None,
    *,
    quiet: bool = False,
    with_keyboard: bool = True,
    require_currency: bool = False,
    require_target: bool = False,
) -> Rendered | None:
    """解析一段自由文本并生成回复；`quiet=True`（群聊）时看不懂就返回 None。

    群聊里用两个开关把噪音挡在外面：
    `require_currency` 要求消息里出现货币，`require_target` 进一步要求写出了
    目标货币（也就是「100 美元 人民币」这种明确的换算意图），
    这样「我昨天花了 100 块」之类的闲聊就不会被接话。
    """
    result = parse(text, context_currency=prefs.base)

    if require_currency and result.source is None:
        return None
    if require_target and not [code for code in result.targets if code != result.source]:
        return None

    if result.error or not result.is_actionable:
        if quiet:
            return None
        if result.unknown_tokens:
            tokens = fmt.esc(", ".join(result.unknown_tokens[:3]))
            return Rendered(
                t(prefs.lang, "unknown_currency", tokens=tokens, first=fmt.esc(result.unknown_tokens[0])),
                ok=False,
            )
        return Rendered(t(prefs.lang, "no_match"), ok=False)

    source = result.source or prefs.base
    if not cur_mod.is_known(source):
        return Rendered(t(prefs.lang, "unavailable", code=source), ok=False)

    targets = resolve_targets(result, prefs, source)
    fee = result.fee_percent if result.fee_percent is not None else prefs.fee_percent

    if db is not None:
        await db.note_usage(prefs.user_id, [source, *targets])
    rates.note_usage([source, *targets])

    return await build_conversion(
        result.amount,
        source,
        targets,
        prefs,
        rates,
        fee_percent=fee,
        expression=result.expression,
        with_keyboard=with_keyboard,
    )
