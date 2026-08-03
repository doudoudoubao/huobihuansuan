"""个性化设置：/settings /setbase /fav /lang /decimals 及对应回调。"""

from __future__ import annotations

import logging
import re
from decimal import Decimal, InvalidOperation

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from .. import currencies as cur_mod
from .. import formatting as fmt
from .. import keyboards as kb
from ..config import Config
from ..db import Database, UserPrefs
from ..i18n import t
from ..parser import parse_currency_list
from .utils import command_args, safe_edit

log = logging.getLogger(__name__)

router = Router(name="settings")


def settings_text(prefs: UserPrefs) -> str:
    lang = prefs.lang
    on, off = t(lang, "on"), t(lang, "off")
    base_meta = cur_mod.get(prefs.base)
    favorites = " ".join(f"{cur_mod.get(c).flag}{c}" for c in prefs.favorites) or "—"
    lines = [
        t(lang, "settings_title"),
        "",
        t(lang, "settings_base", base=f"{base_meta.flag}{prefs.base}"),
        t(lang, "settings_fav", fav=fmt.esc(favorites)),
        t(lang, "settings_decimals", n=prefs.decimals),
        t(lang, "settings_group", state=on if prefs.group_sep else off),
        t(lang, "settings_source", state=on if prefs.show_source else off),
        t(lang, "settings_change", state=on if prefs.show_change else off),
        t(lang, "settings_lang", name="中文" if lang == "zh" else "English"),
        t(lang, "settings_tz", tz=fmt.esc(prefs.tz)),
    ]
    return "\n".join(lines)


@router.message(Command("settings", "set", "config"))
async def cmd_settings(message: Message, prefs: UserPrefs) -> None:
    await message.answer(settings_text(prefs), reply_markup=kb.settings_keyboard(prefs))


@router.message(Command("setbase", "base", "home"))
async def cmd_setbase(message: Message, prefs: UserPrefs, db: Database) -> None:
    codes = parse_currency_list(command_args(message), limit=1)
    if not codes:
        await message.answer(t(prefs.lang, "usage_base"), reply_markup=kb.base_picker_keyboard(prefs))
        return
    updated = await db.update_prefs(prefs.user_id, base=codes[0])
    await message.answer(t(updated.lang, "base_set", base=codes[0]))


_SPLIT_RE = re.compile(r"[\s,，、;；]+")


def fav_panel_text(prefs: UserPrefs, config: Config) -> str:
    pretty = " ".join(f"{cur_mod.get(c).flag}{c}" for c in prefs.favorites) or "—"
    return t(
        prefs.lang,
        "usage_fav",
        fav=fmt.esc(pretty),
        n=len(prefs.favorites),
        max=config.max_favorites,
    )


def _parse_fav_edit(args: str, *, default_sign: str = "") -> tuple[list[str], list[str], bool]:
    """把 `+KRW -GBP JPY` 拆成 (要加的, 要删的, 是否增量模式)。"""
    add: list[str] = []
    remove: list[str] = []
    incremental = bool(default_sign)
    for chunk in _SPLIT_RE.split(args.strip()):
        if not chunk:
            continue
        sign = default_sign
        while chunk and chunk[0] in "+-＋－":
            sign = "-" if chunk[0] in "-－" else "+"
            incremental = True
            chunk = chunk[1:]
        code = cur_mod.resolve_code(chunk)
        if not code:
            continue
        (remove if sign == "-" else add).append(code)
    return add, remove, incremental


async def _apply_fav_edit(
    message: Message, prefs: UserPrefs, db: Database, config: Config, args: str, *, default_sign: str = ""
) -> None:
    add, remove, incremental = _parse_fav_edit(args, default_sign=default_sign)
    if not add and not remove:
        await message.answer(fav_panel_text(prefs, config), reply_markup=kb.fav_picker_keyboard(prefs))
        return

    if incremental:
        favorites = [c for c in prefs.favorites if c not in remove]
        for code in add:
            if code not in favorites:
                favorites.append(code)
    else:
        favorites = list(dict.fromkeys(add))

    trimmed = len(favorites) > config.max_favorites
    favorites = favorites[: config.max_favorites]
    updated = await db.update_prefs(prefs.user_id, favorites=favorites)

    pretty = " ".join(f"{cur_mod.get(c).flag}{c}" for c in favorites) or "—"
    text = t(updated.lang, "fav_set", fav=fmt.esc(pretty), n=len(favorites))
    if trimmed:
        text += "\n" + t(updated.lang, "fav_limit", max=config.max_favorites)
    await message.answer(text)


@router.message(Command("fav", "favorites", "favourite", "sc", "hot"))
async def cmd_fav(message: Message, prefs: UserPrefs, db: Database, config: Config) -> None:
    await _apply_fav_edit(message, prefs, db, config, command_args(message))


@router.message(Command("add", "addfav"))
async def cmd_add_fav(message: Message, prefs: UserPrefs, db: Database, config: Config) -> None:
    await _apply_fav_edit(message, prefs, db, config, command_args(message), default_sign="+")


@router.message(Command("del", "rm", "delfav"))
async def cmd_del_fav(message: Message, prefs: UserPrefs, db: Database, config: Config) -> None:
    await _apply_fav_edit(message, prefs, db, config, command_args(message), default_sign="-")


@router.message(Command("lang", "language", "yy"))
async def cmd_lang(message: Message, prefs: UserPrefs, db: Database) -> None:
    args = command_args(message).strip().lower()
    if args.startswith("en"):
        new_lang = "en"
    elif args.startswith("zh") or "中" in args:
        new_lang = "zh"
    else:
        new_lang = "en" if prefs.lang == "zh" else "zh"
    updated = await db.update_prefs(prefs.user_id, lang=new_lang)
    await message.answer(t(updated.lang, "lang_set"))


@router.message(Command("decimals", "digits"))
async def cmd_decimals(message: Message, prefs: UserPrefs, db: Database) -> None:
    args = command_args(message).strip()
    if not args.isdigit():
        await message.answer(
            t(prefs.lang, "settings_decimals", n=prefs.decimals),
            reply_markup=kb.decimals_keyboard(prefs),
        )
        return
    updated = await db.update_prefs(prefs.user_id, decimals=max(0, min(8, int(args))))
    await message.answer(t(updated.lang, "settings_decimals", n=updated.decimals))


@router.message(Command("fee"))
async def cmd_fee(message: Message, prefs: UserPrefs, db: Database) -> None:
    """设置一个默认手续费百分比，之后每次换算自动带上。"""
    args = command_args(message).strip().rstrip("%％")
    if not args or args.lower() in ("off", "none", "0", "关", "取消"):
        await db.update_prefs(prefs.user_id, fee_percent=None)
        await message.answer("✅ 已关闭默认手续费" if prefs.lang == "zh" else "✅ Default fee cleared")
        return
    try:
        value = Decimal(args)
    except InvalidOperation:
        await message.answer(
            "用法：<code>/fee 2</code>（默认每次换算扣 2%），<code>/fee off</code> 关闭"
            if prefs.lang == "zh"
            else "Usage: <code>/fee 2</code> or <code>/fee off</code>"
        )
        return
    value = max(Decimal(-50), min(Decimal(50), value))
    await db.update_prefs(prefs.user_id, fee_percent=value)
    pct = fmt.fmt_number(value, decimals=2, group=False)
    await message.answer(
        f"✅ 默认手续费已设为 <b>{pct}%</b>" if prefs.lang == "zh" else f"✅ Default fee set to <b>{pct}%</b>"
    )


# --- 设置面板回调 -----------------------------------------------------------


@router.callback_query(F.data.startswith("st|"))
async def cb_settings(
    query: CallbackQuery, prefs: UserPrefs, db: Database, config: Config
) -> None:
    _, parts = kb.unpack(query.data or "")
    action = parts[0] if parts else "home"
    value = parts[1] if len(parts) > 1 else None
    message = query.message
    if message is None:
        await query.answer()
        return

    def page_of(raw: str | None) -> int:
        return int(raw) if raw and raw.isdigit() else 0

    if action == "home":
        await safe_edit(message, settings_text(prefs), kb.settings_keyboard(prefs))  # type: ignore[arg-type]
        await query.answer()
        return

    if action == "base":
        if value:
            prefs = await db.update_prefs(prefs.user_id, base=value.upper())
            await safe_edit(message, settings_text(prefs), kb.settings_keyboard(prefs))  # type: ignore[arg-type]
            await query.answer(t(prefs.lang, "base_set", base=value.upper()).replace("<b>", "").replace("</b>", ""))
        else:
            await safe_edit(message, t(prefs.lang, "usage_base"), kb.base_picker_keyboard(prefs))  # type: ignore[arg-type]
            await query.answer()
        return

    if action in ("fav", "favpg"):
        page = page_of(value)
        await safe_edit(message, fav_panel_text(prefs, config), kb.fav_picker_keyboard(prefs, page))  # type: ignore[arg-type]
        await query.answer()
        return

    if action == "favtog" and value:
        code = value.upper()
        page = page_of(parts[2] if len(parts) > 2 else None)
        favorites = list(prefs.favorites)
        if code in favorites:
            favorites.remove(code)
        elif len(favorites) < config.max_favorites:
            favorites.append(code)
        else:
            await query.answer(
                t(prefs.lang, "fav_limit", max=config.max_favorites), show_alert=True
            )
            return
        prefs = await db.update_prefs(prefs.user_id, favorites=favorites)
        await safe_edit(message, fav_panel_text(prefs, config), kb.fav_picker_keyboard(prefs, page))  # type: ignore[arg-type]
        await query.answer(("✅ " if code in favorites else "▫️ ") + code)
        return

    if action == "favrst":
        page = page_of(value)
        prefs = await db.update_prefs(prefs.user_id, favorites=list(config.default_favorites))
        await safe_edit(message, fav_panel_text(prefs, config), kb.fav_picker_keyboard(prefs, page))  # type: ignore[arg-type]
        await query.answer(t(prefs.lang, "fav_reset"))
        return

    if action == "dec":
        if value is not None and value.isdigit():
            prefs = await db.update_prefs(prefs.user_id, decimals=max(0, min(8, int(value))))
            await safe_edit(message, settings_text(prefs), kb.settings_keyboard(prefs))  # type: ignore[arg-type]
        else:
            await safe_edit(message, t(prefs.lang, "settings_decimals", n=prefs.decimals), kb.decimals_keyboard(prefs))  # type: ignore[arg-type]
        await query.answer()
        return

    toggles = {"grp": "group_sep", "src": "show_source", "chg": "show_change"}
    if action in toggles:
        field = toggles[action]
        prefs = await db.update_prefs(prefs.user_id, **{field: not getattr(prefs, field)})
        await safe_edit(message, settings_text(prefs), kb.settings_keyboard(prefs))  # type: ignore[arg-type]
        await query.answer()
        return

    if action == "lang":
        prefs = await db.update_prefs(prefs.user_id, lang="en" if prefs.lang == "zh" else "zh")
        await safe_edit(message, settings_text(prefs), kb.settings_keyboard(prefs))  # type: ignore[arg-type]
        await query.answer(t(prefs.lang, "lang_set"))
        return

    await query.answer()
