"""Inline 键盘与 callback_data 编解码。

callback_data 有 64 字节上限，所以统一用 `动作|参数1|参数2...` 的紧凑格式，
金额过长时降级为不带金额的动作（回调侧按 1 单位重算）。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Iterable, Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from . import currencies as cur_mod
from .db import UserPrefs
from .i18n import t

MAX_CB = 64
SEP = "|"


def pack(action: str, *parts: object) -> str:
    data = SEP.join([action, *(str(p) for p in parts)])
    if len(data.encode()) <= MAX_CB:
        return data
    # 超长时丢掉最后一个参数（通常是金额），回调侧会用默认值兜底
    trimmed = SEP.join([action, *(str(p) for p in parts[:-1])])
    return trimmed[:MAX_CB]


def unpack(data: str) -> tuple[str, list[str]]:
    parts = data.split(SEP)
    return parts[0], parts[1:]


def _amount_token(amount: Decimal) -> str:
    text = format(amount.normalize(), "f")
    return text if len(text) <= 18 else "1"


def conversion_keyboard(
    base: str,
    quote: str,
    amount: Decimal,
    prefs: UserPrefs,
    *,
    suggestions: Sequence[str] = (),
) -> InlineKeyboardMarkup:
    """单对换算结果下方的操作条 + 快捷目标币种。"""
    lang = prefs.lang
    amt = _amount_token(amount)
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t(lang, "btn_reverse"), callback_data=pack("rev", base, quote, amt)),
        InlineKeyboardButton(text=t(lang, "btn_refresh"), callback_data=pack("ref", base, quote, amt)),
        InlineKeyboardButton(text=t(lang, "btn_chart"), callback_data=pack("ch", base, quote, 30)),
        InlineKeyboardButton(text=t(lang, "btn_alert"), callback_data=pack("al", base, quote)),
    )

    picks = [c for c in (suggestions or prefs.targets_for(base)) if c not in (base, quote)][:6]
    row: list[InlineKeyboardButton] = []
    for code in picks:
        meta = cur_mod.get(code)
        row.append(
            InlineKeyboardButton(
                text=f"{meta.flag}{code}".strip(),
                callback_data=pack("cv", base, code, amt),
            )
        )
        if len(row) == 3:
            builder.row(*row)
            row = []
    if row:
        builder.row(*row)

    builder.row(
        InlineKeyboardButton(text=t(lang, "btn_more"), callback_data=pack("multi", base, amt)),
        InlineKeyboardButton(text=t(lang, "btn_close"), callback_data=pack("close")),
    )
    return builder.as_markup()


def multi_keyboard(
    base: str, amount: Decimal, prefs: UserPrefs, *, quotes: Sequence[str] = ()
) -> InlineKeyboardMarkup:
    """多币种速览下方：刷新 / 编辑常用 / 关闭，再加一排「看单个货币详情」。"""
    lang = prefs.lang
    amt = _amount_token(amount)
    builder = InlineKeyboardBuilder()

    row: list[InlineKeyboardButton] = []
    for code in list(quotes)[:8]:
        meta = cur_mod.get(code)
        row.append(
            InlineKeyboardButton(
                text=f"{meta.flag}{code}".strip(), callback_data=pack("cv", base, code, amt)
            )
        )
        if len(row) == 4:
            builder.row(*row)
            row = []
    if row:
        builder.row(*row)

    builder.row(
        InlineKeyboardButton(text=t(lang, "btn_refresh"), callback_data=pack("mref", base, amt)),
        InlineKeyboardButton(text=t(lang, "btn_edit_fav"), callback_data=pack("st", "fav")),
        InlineKeyboardButton(text=t(lang, "btn_close"), callback_data=pack("close")),
    )
    return builder.as_markup()


def rate_keyboard(base: str, quote: str, prefs: UserPrefs) -> InlineKeyboardMarkup:
    lang = prefs.lang
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t(lang, "btn_reverse"), callback_data=pack("rate", quote, base)),
        InlineKeyboardButton(text=t(lang, "btn_refresh"), callback_data=pack("rate", base, quote)),
    )
    builder.row(
        InlineKeyboardButton(text="7D", callback_data=pack("ch", base, quote, 7)),
        InlineKeyboardButton(text="30D", callback_data=pack("ch", base, quote, 30)),
        InlineKeyboardButton(text="90D", callback_data=pack("ch", base, quote, 90)),
        InlineKeyboardButton(text="1Y", callback_data=pack("ch", base, quote, 365)),
    )
    builder.row(InlineKeyboardButton(text=t(lang, "btn_close"), callback_data=pack("close")))
    return builder.as_markup()


def chart_keyboard(base: str, quote: str, days: int, prefs: UserPrefs) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    options = (7, 30, 90, 365)
    builder.row(
        *[
            InlineKeyboardButton(
                text=("• " if d == days else "") + (f"{d}D" if d < 365 else "1Y"),
                callback_data=pack("ch", base, quote, d),
            )
            for d in options
        ]
    )
    builder.row(InlineKeyboardButton(text=t(prefs.lang, "btn_close"), callback_data=pack("close")))
    return builder.as_markup()


def settings_keyboard(prefs: UserPrefs) -> InlineKeyboardMarkup:
    lang = prefs.lang
    on, off = t(lang, "on"), t(lang, "off")
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=f"💰 {prefs.base}", callback_data=pack("st", "base")),
        InlineKeyboardButton(text=f"⭐ {len(prefs.favorites)}", callback_data=pack("st", "fav")),
    )
    builder.row(
        InlineKeyboardButton(text=f"🔢 {prefs.decimals}", callback_data=pack("st", "dec")),
        InlineKeyboardButton(
            text=f"🔠 {on if prefs.group_sep else off}", callback_data=pack("st", "grp")
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text=f"🔗 {on if prefs.show_source else off}", callback_data=pack("st", "src")
        ),
        InlineKeyboardButton(
            text=f"📊 {on if prefs.show_change else off}", callback_data=pack("st", "chg")
        ),
    )
    builder.row(
        InlineKeyboardButton(text="🌐 中文 / English", callback_data=pack("st", "lang")),
    )
    builder.row(InlineKeyboardButton(text=t(lang, "btn_close"), callback_data=pack("close")))
    return builder.as_markup()


def decimals_keyboard(prefs: UserPrefs) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        *[
            InlineKeyboardButton(
                text=("• " if n == prefs.decimals else "") + str(n),
                callback_data=pack("st", "dec", n),
            )
            for n in range(0, 7)
        ]
    )
    builder.row(InlineKeyboardButton(text=t(prefs.lang, "btn_back"), callback_data=pack("st", "home")))
    return builder.as_markup()


def base_picker_keyboard(prefs: UserPrefs, codes: Iterable[str] | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    row: list[InlineKeyboardButton] = []
    for code in codes or cur_mod.POPULAR:
        meta = cur_mod.get(code)
        row.append(
            InlineKeyboardButton(
                text=("• " if code == prefs.base else "") + f"{meta.flag}{code}",
                callback_data=pack("st", "base", code),
            )
        )
        if len(row) == 4:
            builder.row(*row)
            row = []
    if row:
        builder.row(*row)
    builder.row(InlineKeyboardButton(text=t(prefs.lang, "btn_back"), callback_data=pack("st", "home")))
    return builder.as_markup()


FAV_PAGE_SIZE = 15  # 5 行 × 3 列


def fav_pool(prefs: UserPrefs) -> list[str]:
    """候选池顺序固定，翻页时按钮不会因为勾选而跳动。"""
    return list(dict.fromkeys(list(cur_mod.PICKER_POOL) + [c.upper() for c in prefs.favorites]))


def fav_picker_keyboard(prefs: UserPrefs, page: int = 0) -> InlineKeyboardMarkup:
    pool = fav_pool(prefs)
    pages = max(1, -(-len(pool) // FAV_PAGE_SIZE))
    page = max(0, min(page, pages - 1))
    chunk = pool[page * FAV_PAGE_SIZE : (page + 1) * FAV_PAGE_SIZE]

    builder = InlineKeyboardBuilder()
    row: list[InlineKeyboardButton] = []
    for code in chunk:
        meta = cur_mod.get(code)
        mark = "✅" if code in prefs.favorites else "▫️"
        row.append(
            InlineKeyboardButton(
                text=f"{mark}{meta.flag}{code}", callback_data=pack("st", "favtog", code, page)
            )
        )
        if len(row) == 3:
            builder.row(*row)
            row = []
    if row:
        builder.row(*row)

    if pages > 1:
        builder.row(
            InlineKeyboardButton(text="◀️", callback_data=pack("st", "favpg", (page - 1) % pages)),
            InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data=pack("st", "favpg", page)),
            InlineKeyboardButton(text="▶️", callback_data=pack("st", "favpg", (page + 1) % pages)),
        )
    builder.row(
        InlineKeyboardButton(text=t(prefs.lang, "btn_fav_reset"), callback_data=pack("st", "favrst", page)),
        InlineKeyboardButton(text=t(prefs.lang, "btn_back"), callback_data=pack("st", "home")),
    )
    return builder.as_markup()


def alerts_keyboard(alert_ids: Sequence[int], lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    row: list[InlineKeyboardButton] = []
    for alert_id in alert_ids:
        row.append(InlineKeyboardButton(text=f"🗑 #{alert_id}", callback_data=pack("aldel", alert_id)))
        if len(row) == 4:
            builder.row(*row)
            row = []
    if row:
        builder.row(*row)
    builder.row(InlineKeyboardButton(text=t(lang, "btn_close"), callback_data=pack("close")))
    return builder.as_markup()


def subs_keyboard(sub_ids: Sequence[int], lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    row: list[InlineKeyboardButton] = []
    for sub_id in sub_ids:
        row.append(InlineKeyboardButton(text=f"🗑 #{sub_id}", callback_data=pack("subdel", sub_id)))
        if len(row) == 4:
            builder.row(*row)
            row = []
    if row:
        builder.row(*row)
    builder.row(InlineKeyboardButton(text=t(lang, "btn_close"), callback_data=pack("close")))
    return builder.as_markup()
