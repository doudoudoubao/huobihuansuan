"""把真实的 Dispatcher 跑一遍，确认中间件注入与限流对子路由里的 handler 生效。

handler 通过依赖注入拿 `prefs`，一旦中间件挂错层级，注入就会失败并抛 TypeError，
所以这几个用例能兜住整条装配链路。
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from aiogram import Bot, Dispatcher, Router
from aiogram.types import Chat, Message, Update, User

from bot.config import Config
from bot.db import Database, UserPrefs
from bot.main import build_dispatcher
from bot.middlewares import PrefsMiddleware, ThrottleMiddleware
from bot.rates.service import RateService

FAKE_TOKEN = "123456789:AAEjQmFrZS10b2tlbi1mb3ItdW5pdC10ZXN0cw"


def make_message(text: str, user_id: int = 99, chat_id: int = 99) -> Message:
    return Message(
        message_id=1,
        date=datetime.now(timezone.utc),
        chat=Chat(id=chat_id, type="private"),
        from_user=User(id=user_id, is_bot=False, first_name="Tester", language_code="zh-hans"),
        text=text,
    )


@pytest.fixture()
async def db(tmp_path):
    database = Database(Config(db_path=str(tmp_path / "wiring.db")))
    await database.connect()
    yield database
    await database.close()


@pytest.fixture()
def bot():
    return Bot(token=FAKE_TOKEN)


async def test_prefs_reach_child_router_handlers(db, bot):
    seen: dict[str, object] = {}

    probe = Router(name="probe")

    @probe.message()
    async def handler(message: Message, prefs: UserPrefs, db: Database) -> None:  # noqa: ARG001
        seen["prefs"] = prefs
        seen["text"] = message.text

    dp = Dispatcher(db=db)
    dp.message.outer_middleware(PrefsMiddleware(db))
    dp.include_router(probe)

    await dp.feed_update(bot, Update(update_id=1, message=make_message("100 usd cny")))

    assert isinstance(seen.get("prefs"), UserPrefs)
    assert seen["prefs"].user_id == 99
    assert seen["prefs"].lang == "zh"  # 由 Telegram 的 language_code 推断


async def test_throttle_drops_rapid_second_message(db, bot):
    calls: list[str] = []
    probe = Router(name="probe")

    @probe.message()
    async def handler(message: Message) -> None:
        calls.append(message.text or "")

    dp = Dispatcher(db=db)
    dp.message.outer_middleware(ThrottleMiddleware(interval=10.0))
    dp.include_router(probe)

    await dp.feed_update(bot, Update(update_id=1, message=make_message("a")))
    await dp.feed_update(bot, Update(update_id=2, message=make_message("b")))

    assert calls == ["a"]


async def test_build_dispatcher_registers_expected_update_types(db, tmp_path):
    cfg = Config(db_path=str(tmp_path / "wiring.db"), bot_token=FAKE_TOKEN)
    rates = RateService(cfg)
    rates.inject("stub", {"USD": Decimal(1), "CNY": Decimal("7.2")})
    dp = build_dispatcher(cfg, db, rates)
    used = set(dp.resolve_used_update_types())
    assert {"message", "callback_query", "inline_query"} <= used
