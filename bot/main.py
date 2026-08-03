"""程序入口：装配 bot、汇率服务、数据库与后台任务。"""

from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    ErrorEvent,
)

from .config import Config, config as default_config
from .db import Database
from .handlers import build_router
from .middlewares import PrefsMiddleware, ThrottleMiddleware
from .rates.service import RateService
from .scheduler import Scheduler

log = logging.getLogger(__name__)

PRIVATE_COMMANDS = [
    BotCommand(command="start", description="开始 / 使用示例"),
    BotCommand(command="help", description="完整使用手册"),
    BotCommand(command="rate", description="查汇率  /rate usd cny"),
    BotCommand(command="chart", description="走势图  /chart usd cny 30"),
    BotCommand(command="hist", description="历史汇率  /hist usd cny 2024-01-01"),
    BotCommand(command="alert", description="到价提醒  /alert usd cny > 7.3"),
    BotCommand(command="alerts", description="我的提醒"),
    BotCommand(command="subscribe", description="每日播报  /subscribe 09:00 usd cny"),
    BotCommand(command="subs", description="我的播报"),
    BotCommand(command="setbase", description="默认币种  /setbase CNY"),
    BotCommand(command="fav", description="收藏币种  /fav USD JPY EUR"),
    BotCommand(command="settings", description="设置面板"),
    BotCommand(command="search", description="查找货币  /search 韩"),
    BotCommand(command="list", description="支持的货币"),
    BotCommand(command="refresh", description="立刻刷新汇率"),
    BotCommand(command="status", description="数据源状态"),
]

GROUP_COMMANDS = [
    BotCommand(command="c", description="换算  /c 100 usd cny"),
    BotCommand(command="rate", description="查汇率  /rate usd cny"),
    BotCommand(command="chart", description="走势图  /chart usd cny 30"),
    BotCommand(command="alert", description="到价提醒"),
    BotCommand(command="help", description="使用手册"),
]


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)


def build_dispatcher(cfg: Config, db: Database, rates: RateService) -> Dispatcher:
    dp = Dispatcher(db=db, rates=rates, config=cfg)

    # 用 outer middleware：它在过滤器之前执行且每个事件只跑一次，
    # 于是 prefs 对过滤器也可见，限流也能在匹配 handler 之前就把请求挡掉。
    prefs_mw = PrefsMiddleware(db)
    throttle_mw = ThrottleMiddleware(cfg.rate_limit_seconds)
    for observer in (dp.message, dp.callback_query, dp.inline_query, dp.edited_message):
        observer.outer_middleware(prefs_mw)
    for observer in (dp.message, dp.callback_query):
        observer.outer_middleware(throttle_mw)

    dp.include_router(build_router())

    @dp.errors()
    async def on_error(event: ErrorEvent) -> bool:
        log.exception("处理更新时出错: %s", event.exception)
        return True

    return dp


async def _set_commands(bot: Bot) -> None:
    try:
        await bot.set_my_commands(PRIVATE_COMMANDS, scope=BotCommandScopeAllPrivateChats())
        await bot.set_my_commands(GROUP_COMMANDS, scope=BotCommandScopeAllGroupChats())
    except Exception:  # noqa: BLE001 - 命令菜单失败不影响运行
        log.warning("设置命令菜单失败", exc_info=True)


async def run(cfg: Config | None = None) -> None:
    cfg = cfg or default_config
    cfg.validate()
    setup_logging(cfg.log_level)

    bot = Bot(token=cfg.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    db = Database(cfg)
    rates = RateService(cfg)
    scheduler = Scheduler(bot, db, rates, cfg)

    await db.connect()
    log.info("正在初始化汇率数据……")
    await rates.start()
    await scheduler.start()
    await _set_commands(bot)

    dp = build_dispatcher(cfg, db, rates)

    try:
        me = await bot.me()
        log.info("已登录为 @%s（%s）", me.username, me.id)
        if cfg.use_webhook:
            await _run_webhook(bot, dp, cfg)
        else:
            await bot.delete_webhook(drop_pending_updates=True)
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        log.info("正在退出……")
        await scheduler.stop()
        await rates.stop()
        await db.close()
        await bot.session.close()


async def _run_webhook(bot: Bot, dp: Dispatcher, cfg: Config) -> None:
    from aiohttp import web
    from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

    await bot.set_webhook(
        cfg.webhook_url,
        secret_token=cfg.webhook_secret or None,
        drop_pending_updates=True,
        allowed_updates=dp.resolve_used_update_types(),
    )
    app = web.Application()

    async def health(_request: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    app.router.add_get("/healthz", health)
    SimpleRequestHandler(
        dispatcher=dp, bot=bot, secret_token=cfg.webhook_secret or None
    ).register(app, path=cfg.webhook_path)
    setup_application(app, dp, bot=bot)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, cfg.webapp_host, cfg.webapp_port)
    await site.start()
    log.info("Webhook 已启动：%s → %s:%s", cfg.webhook_url, cfg.webapp_host, cfg.webapp_port)
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()


def main() -> None:
    try:
        asyncio.run(run())
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()
