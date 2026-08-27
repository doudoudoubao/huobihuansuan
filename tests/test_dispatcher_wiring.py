"""把真实的 Dispatcher 跑一遍，确认中间件注入与限流对子路由里的 handler 生效。

handler 通过依赖注入拿 `prefs`，一旦中间件挂错层级，注入就会失败并抛 TypeError，
所以这几个用例能兜住整条装配链路。
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from aiogram import Bot, Dispatcher, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Chat, InlineQuery, Message, Update, User

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


@pytest.fixture(autouse=True)
def _reusable_routers():
    """让 build_router() 在一次进程里能被反复调用。

    各个子路由都是模块级单例（handler 靠装饰器注册），aiogram 不允许同一个
    Router 挂到第二个父路由上。生产里 build_router() 只调一次，所以这不是
    线上问题；但测试要反复组装真实路由，用例之间得把父指针解开才不会互相绊倒。
    """
    from bot.handlers import alerts, common, convert, inline, market, settings

    routers = [common.router, settings.router, market.router,
               alerts.router, inline.router, convert.router]
    for child in routers:
        child._parent_router = None  # noqa: SLF001
    yield
    for child in routers:
        child._parent_router = None  # noqa: SLF001


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


# --- inline 模式 ---------------------------------------------------------
# inline 失败在用户那边是完全静默的：输入框上方什么都不弹，没有报错也没有提示。
# 唯一的线索就是日志，所以这两条用例盯的是「日志里说不说得清」。


def make_inline(text: str, user_id: int = 99) -> InlineQuery:
    return InlineQuery(
        id="q1",
        from_user=User(id=user_id, is_bot=False, first_name="Tester", language_code="zh-hans"),
        query=text,
        offset="",
    )


def _dispatcher(cfg_path, db) -> tuple[Dispatcher, Config]:
    cfg = Config(db_path=str(cfg_path / "wiring.db"), bot_token=FAKE_TOKEN)
    rates = RateService(cfg)
    rates.inject("stub", {"USD": Decimal(1), "CNY": Decimal("7.2")})
    return build_dispatcher(cfg, db, rates), cfg


async def test_inline_query_produces_results(db, bot, tmp_path, monkeypatch, caplog):
    dp, _ = _dispatcher(tmp_path, db)
    sent = []

    async def fake_call(self, method, request_timeout=None):  # noqa: ANN001, ARG001
        sent.append(method)
        return True

    monkeypatch.setattr(Bot, "__call__", fake_call)
    with caplog.at_level(logging.INFO, logger="bot.handlers.inline"):
        await dp.feed_update(bot, Update(update_id=1, inline_query=make_inline("100 usd cny")))

    assert len(sent) == 1, "应当调用一次 answerInlineQuery"
    assert sent[0].results, "答复里必须带结果，空结果等于用户什么都看不到"
    assert "收到 inline 查询" in caplog.text
    assert "已应答" in caplog.text


async def test_rejected_inline_results_are_logged_not_swallowed(
    db, bot, tmp_path, monkeypatch, caplog
):
    """API 回绝时要留下能定位的日志：原因、条数、原始 query，缺一样都查不下去。"""
    dp, _ = _dispatcher(tmp_path, db)

    async def fake_call(self, method, request_timeout=None):  # noqa: ANN001, ARG001
        raise TelegramBadRequest(method=method, message="Bad Request: RESULT_TYPE_INVALID")

    monkeypatch.setattr(Bot, "__call__", fake_call)
    with caplog.at_level(logging.ERROR):
        await dp.feed_update(bot, Update(update_id=1, inline_query=make_inline("100 usd cny")))

    assert "RESULT_TYPE_INVALID" in caplog.text
    assert "100 usd cny" in caplog.text
