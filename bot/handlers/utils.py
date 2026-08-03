"""处理器公共小工具。"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

log = logging.getLogger(__name__)


async def safe_edit(
    message: Message,
    text: str,
    keyboard: InlineKeyboardMarkup | None = None,
) -> bool:
    """编辑消息，吞掉「内容未变化」这类无害错误。"""
    try:
        await message.edit_text(text, reply_markup=keyboard, disable_web_page_preview=True)
        return True
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc).lower():
            return True
        log.debug("编辑消息失败: %s", exc)
        return False
    except (TelegramForbiddenError, TelegramRetryAfter) as exc:
        log.debug("编辑消息被拒绝: %s", exc)
        return False


async def answer_or_edit(
    event: Message | CallbackQuery,
    text: str,
    keyboard: InlineKeyboardMarkup | None = None,
) -> None:
    if isinstance(event, CallbackQuery):
        if event.message:
            await safe_edit(event.message, text, keyboard)  # type: ignore[arg-type]
        await event.answer()
    else:
        await event.answer(text, reply_markup=keyboard, disable_web_page_preview=True)


def parse_decimal(token: str, default: Decimal = Decimal(1)) -> Decimal:
    try:
        value = Decimal(token)
    except (InvalidOperation, ValueError, TypeError):
        return default
    return value if value.is_finite() else default


def command_args(message: Message) -> str:
    """取命令后面的参数原文。"""
    text = message.text or message.caption or ""
    parts = text.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def is_group(message: Message) -> bool:
    return message.chat.type in ("group", "supergroup")
