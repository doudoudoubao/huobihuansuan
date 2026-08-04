"""数字格式化与消息渲染。"""

from __future__ import annotations

import html
import re
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, Sequence

from . import currencies as cur_mod
from .db import UserPrefs
from .i18n import t
from .rates.service import Conversion, RateInfo

MAX_DECIMALS = 12


def esc(text: object) -> str:
    return html.escape(str(text), quote=False)


def auto_decimals(value: Decimal, prefs_decimals: int, currency: cur_mod.Currency) -> int:
    """按数量级自动决定小数位：大额少给，小额多给（保证 ~4 位有效数字）。"""
    magnitude = abs(value)
    if not magnitude.is_finite():
        return prefs_decimals
    if magnitude == 0:
        return 0 if currency.decimals == 0 else min(prefs_decimals, 2)
    if magnitude >= 1:
        if currency.decimals == 0:
            return 0
        if currency.is_crypto and magnitude >= 1000:
            return 2
        return max(0, min(prefs_decimals if not currency.is_crypto else max(prefs_decimals, 4), 8))
    exponent = magnitude.adjusted()  # 0.0034 → -3
    return min(MAX_DECIMALS, 3 - exponent)


def _strip_zeros(text: str, min_decimals: int) -> str:
    if "." not in text:
        return text
    whole, _, frac = text.partition(".")
    frac = frac.rstrip("0")
    while len(frac) < min_decimals:
        frac += "0"
    return f"{whole}.{frac}" if frac else whole


def fmt_number(
    value: Decimal,
    *,
    decimals: int,
    group: bool = True,
    min_decimals: int = 0,
) -> str:
    quantum = Decimal(1).scaleb(-decimals)
    try:
        quantized = value.quantize(quantum, rounding=ROUND_HALF_UP)
    except ArithmeticError:
        quantized = value
    text = f"{quantized:,.{decimals}f}" if group else f"{quantized:.{decimals}f}"
    return _strip_zeros(text, min_decimals)


def fmt_money(value: Decimal, code: str, prefs: UserPrefs) -> str:
    currency = cur_mod.get(code)
    decimals = auto_decimals(value, prefs.decimals, currency)
    min_decimals = 0 if currency.decimals == 0 else min(prefs.decimals, 2)
    return fmt_number(value, decimals=decimals, group=prefs.group_sep, min_decimals=min_decimals)


def fmt_rate(value: Decimal, prefs: UserPrefs | None = None) -> str:
    """汇率本身需要比金额更高的精度。"""
    magnitude = abs(value)
    group = prefs.group_sep if prefs else True
    if magnitude == 0:
        return "0"
    if magnitude >= 1000:
        decimals = 2
    elif magnitude >= 1:
        decimals = 4
    else:
        # 小数保留约 4 位有效数字：0.00000208474 → 0.000002085
        decimals = min(MAX_DECIMALS, 3 - magnitude.adjusted())
    return fmt_number(value, decimals=decimals, group=group, min_decimals=2)


def fmt_ago(seconds: float, lang: str) -> str:
    seconds = max(0.0, seconds)
    if seconds < 10:
        return t(lang, "just_now")
    if seconds < 60:
        return t(lang, "seconds_ago", n=int(seconds))
    if seconds < 3600:
        return t(lang, "minutes_ago", n=int(seconds // 60))
    if seconds < 86400:
        return t(lang, "hours_ago", n=int(seconds // 3600))
    return t(lang, "days_ago", n=int(seconds // 86400))


def fmt_change(pct: Decimal | None, lang: str) -> str:
    if pct is None:
        return ""
    arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "＝")
    return t(lang, "change_24h", arrow=arrow, pct=fmt_number(abs(pct), decimals=2, group=False, min_decimals=2))


def currency_name(code: str, lang: str) -> str:
    currency = cur_mod.get(code)
    return currency.zh if lang == "zh" else currency.en


_PLAIN_NUMBER_RE = re.compile(r"^[\d.,\s]+$")


def expression_hint(expression: str | None) -> str:
    """只有真正算了点什么（含运算符或万/亿等量级）才回显原始算式。"""
    if not expression:
        return ""
    text = expression.strip()
    if not text or _PLAIN_NUMBER_RE.match(text):
        return ""
    return f"  <i>({esc(text)})</i>"


# --- 消息渲染 ---------------------------------------------------------------


RULE = "───────────────"


def fmt_input_amount(value: Decimal, code: str, prefs: UserPrefs) -> str:
    """回显用户输入的金额：整数就别拖着 `.00` 的尾巴。"""
    currency = cur_mod.get(code)
    decimals = auto_decimals(value, prefs.decimals, currency)
    return fmt_number(value, decimals=decimals, group=prefs.group_sep, min_decimals=0)


def render_conversion(
    conv: Conversion,
    prefs: UserPrefs,
    *,
    change_24h: Decimal | None = None,
    expression: str | None = None,
) -> str:
    """单对详情卡：源金额不加粗、结果加粗，视线一落就看到答案。"""
    lang = prefs.lang
    base = cur_mod.get(conv.base)
    quote = cur_mod.get(conv.quote)

    amount_text = fmt_input_amount(conv.amount, conv.base, prefs)
    result_text = fmt_money(conv.result, conv.quote, prefs)

    base_name = f"  {esc(currency_name(conv.base, lang))}" if prefs.show_names else ""
    quote_name = f"  {esc(currency_name(conv.quote, lang))}" if prefs.show_names else ""

    lines = [
        f"{base.flag} {esc(amount_text)} {esc(conv.base)}{base_name}" + expression_hint(expression),
        f"{quote.flag} <b>{esc(result_text)} {esc(conv.quote)}</b>{quote_name}",
        "",
    ]

    if conv.fee_percent:
        gross = fmt_money(conv.gross, conv.quote, prefs)
        sign = "−" if conv.fee_percent > 0 else "+"
        pct = fmt_number(abs(conv.fee_percent), decimals=2, group=False)
        word = "手续费" if lang == "zh" else "fee"
        lines.append(
            f"<i>{esc(gross)} {esc(conv.quote)} · {esc(word)} {sign}{esc(pct)}% "
            f"= {esc(fmt_money(abs(conv.fee_amount), conv.quote, prefs))}</i>"
        )

    lines.append(esc(f"1 {conv.base} = {fmt_rate(conv.rate.value, prefs)} {conv.quote}"))
    lines.append(
        f"<i>{esc(f'1 {conv.quote} = {fmt_rate(conv.rate.inverse, prefs)} {conv.base}')}</i>"
    )

    if prefs.show_change:
        change = fmt_change(change_24h, lang)
        if change:
            lines.append(esc(change))

    lines.append(RULE)
    lines.append(_footer(conv.rate, prefs))
    return "\n".join(lines)


def render_multi(
    amount: Decimal,
    base: str,
    conversions: Sequence[Conversion],
    prefs: UserPrefs,
    *,
    missing: Iterable[str] = (),
    fee_percent: Decimal | None = None,
    expression: str | None = None,
) -> str:
    """多币种速览。

    对齐的关键：货币代码和数值必须在**同一个** <code> 里，
    Telegram 才会用等宽字体渲染整段、右对齐才立得住。
    国旗 emoji 留在 code 外面，每行都有且只有一个，起点自然齐平。

    货币名（美元 / 港币…）放在 code 块**之后**：中文在等宽字体里的宽度
    各客户端不一致，塞进 code 会把好不容易对齐的数字列顶歪；
    放在定宽 code 块后面，反而每行都从同一列开始。
    """
    lang = prefs.lang
    base_meta = cur_mod.get(base)
    amount_text = fmt_input_amount(amount, base, prefs)

    icon = base_meta.flag or "💱"
    base_name = f"  {esc(currency_name(base, lang))}" if prefs.show_names else ""
    lines = [
        f"{icon} <b>{esc(amount_text)} {esc(base)}</b>{base_name}" + expression_hint(expression),
        "",
    ]

    values = [fmt_money(conv.result, conv.quote, prefs) for conv in conversions]
    value_width = max((len(v) for v in values), default=0)
    code_width = max((len(conv.quote) for conv in conversions), default=3)

    for conv, value in zip(conversions, values):
        quote_meta = cur_mod.get(conv.quote)
        flag = quote_meta.flag or "▫️"
        cell = f"{conv.quote.ljust(code_width)}  {value.rjust(value_width)}"
        name = f"  {esc(currency_name(conv.quote, lang))}" if prefs.show_names else ""
        lines.append(f"{flag} <code>{esc(cell)}</code>{name}")

    missing_list = [code for code in missing]
    if missing_list:
        joiner, suffix = ("、", " 暂无报价") if lang == "zh" else (", ", " unavailable")
        lines.append(f"<i>⚠️ {esc(joiner.join(missing_list))}{esc(suffix)}</i>")

    if fee_percent:
        sign = "−" if fee_percent > 0 else "+"
        pct = fmt_number(abs(fee_percent), decimals=2, group=False)
        word = "已扣手续费" if lang == "zh" else "fee applied"
        lines.append(f"<i>{esc(word)} {sign}{esc(pct)}%</i>")

    if conversions:
        lines.append(RULE)
        lines.append(_footer(conversions[0].rate, prefs))
    return "\n".join(lines)


def render_rate(rate: RateInfo, prefs: UserPrefs, *, change_24h: Decimal | None = None, change_1h: Decimal | None = None) -> str:
    lang = prefs.lang
    base = cur_mod.get(rate.base)
    quote = cur_mod.get(rate.quote)
    lines = [
        t(lang, "rate_title", base=rate.base, quote=rate.quote),
        f"{base.flag} {esc(base.zh if lang == 'zh' else base.en)} → {quote.flag} {esc(quote.zh if lang == 'zh' else quote.en)}",
        "",
        f"<b>1 {esc(rate.base)} = {esc(fmt_rate(rate.value, prefs))} {esc(rate.quote)}</b>",
        f"<i>1 {esc(rate.quote)} = {esc(fmt_rate(rate.inverse, prefs))} {esc(rate.base)}</i>",
    ]
    changes = []
    if change_1h is not None:
        changes.append(f"1h {'▲' if change_1h >= 0 else '▼'} {fmt_number(abs(change_1h), decimals=2, group=False, min_decimals=2)}%")
    if change_24h is not None:
        changes.append(f"24h {'▲' if change_24h >= 0 else '▼'} {fmt_number(abs(change_24h), decimals=2, group=False, min_decimals=2)}%")
    if changes:
        lines.append("")
        lines.append(esc(" · ".join(changes)))
    lines.append(RULE)
    lines.append(_footer(rate, prefs))
    return "\n".join(lines)


def _footer(rate: RateInfo, prefs: UserPrefs) -> str:
    lang = prefs.lang
    ago = fmt_ago(rate.age, lang)
    if rate.stale:
        return f"<i>⚠️ {esc(t(lang, 'stale_warn', ago=ago))}</i>"
    if not prefs.show_source:
        return f"<i>🕒 {esc(ago)}</i>"
    return f"<i>📡 {esc('/'.join(rate.sources))} · {esc(ago)}</i>"


def render_currency_list(items: Sequence[cur_mod.Currency], lang: str, *, title: str) -> str:
    lines = [title, ""]
    for currency in items:
        name = currency.zh if lang == "zh" else currency.en
        lines.append(f"{currency.flag} <code>{esc(currency.code)}</code> {esc(name)}")
    return "\n".join(lines)
