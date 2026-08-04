"""程序入口：装配 bot、汇率服务、数据库与后台任务。"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramUnauthorizedError
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    ErrorEvent,
)

from .config import Config, StartupError, config as default_config
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
    BotCommand(command="fav", description="常用币种面板（决定一次列出哪些）"),
    BotCommand(command="add", description="加常用币种  /add 韩元 泰铢"),
    BotCommand(command="del", description="删常用币种  /del 英镑"),
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


def build_bot(cfg: Config) -> Bot:
    """按需带上代理——大陆机器直连 api.telegram.org 通常是不通的。"""
    session = None
    if cfg.telegram_proxy:
        try:
            session = AiohttpSession(proxy=cfg.telegram_proxy)
        except RuntimeError as exc:  # aiogram 走代理要额外的 aiohttp-socks
            raise StartupError(
                f"启用代理 {cfg.telegram_proxy} 失败：{exc}\n"
                "  装一下依赖：pip install aiohttp-socks\n"
                "  如果本来就不需要代理，清掉 .env 里的 TELEGRAM_PROXY，"
                "并检查环境变量 HTTPS_PROXY 是否被别处设过。"
            ) from exc
    return Bot(
        token=cfg.bot_token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


async def _login(bot: Bot, cfg: Config):  # noqa: ANN202
    """连一次 Telegram，把常见失败翻译成人话。"""
    try:
        return await bot.me()
    except TelegramUnauthorizedError as exc:
        raise StartupError(
            "Telegram 拒绝了这个 BOT_TOKEN（401 Unauthorized）。\n"
            "  token 可能填错了，或者已经在 @BotFather 里 /revoke 过。\n"
            "  去 @BotFather 发 /mybots → 选中机器人 → API Token 重新复制一份。"
        ) from exc
    except Exception as exc:  # noqa: BLE001 - 代理库会抛各种自定义异常，统一归为连不上
        if cfg.telegram_proxy:
            hint = (
                f"当前代理：{cfg.telegram_proxy}\n"
                "  代理本身可能没起来、端口写错，或者不允许 CONNECT 到 443。"
            )
        else:
            hint = (
                "没有配置代理。大陆的服务器直连通常不通，\n"
                "  可在 .env 里设 TELEGRAM_PROXY=http://127.0.0.1:7890（或 socks5://127.0.0.1:1080）。"
            )
        raise StartupError(
            f"连不上 api.telegram.org：{type(exc).__name__}: {exc}\n  {hint}\n"
            "  自测一下：curl -sS https://api.telegram.org/bot<你的TOKEN>/getMe"
        ) from exc


async def run(cfg: Config | None = None) -> None:
    cfg = cfg or default_config
    cfg.validate()
    setup_logging(cfg.log_level)

    bot = build_bot(cfg)
    db = Database(cfg)
    rates = RateService(cfg)
    scheduler = Scheduler(bot, db, rates, cfg)

    await db.connect()
    log.info("正在初始化汇率数据……")
    await rates.start()
    await scheduler.start()

    dp = build_dispatcher(cfg, db, rates)

    try:
        me = await _login(bot, cfg)
        log.info("已登录为 @%s（%s）", me.username, me.id)
        await _set_commands(bot)
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


async def self_check(cfg: Config | None = None) -> int:
    """`python run.py --check`：部署前把配置、Telegram 连通性、汇率源过一遍。"""
    cfg = cfg or default_config
    print("🩺 部署自检\n" + "─" * 46)

    try:
        cfg.validate()
    except StartupError as exc:
        print(f"❌ 配置\n   {str(exc).replace(chr(10), chr(10) + '   ')}")
        return 1
    print(f"✅ 配置　　　token 格式正确，数据目录 {Path(cfg.db_path).parent}")

    db = Database(cfg)
    try:
        await db.connect()
        print(f"✅ 数据库　　{cfg.db_path} 可读写")
    except Exception as exc:  # noqa: BLE001
        print(f"❌ 数据库　　{exc}")
        return 1
    finally:
        await db.close()

    try:
        bot = build_bot(cfg)
    except StartupError as exc:
        print(f"❌ 代理\n   {str(exc).replace(chr(10), chr(10) + '   ')}")
        return 1
    try:
        me = await _login(bot, cfg)
        proxy = f"（经代理 {cfg.telegram_proxy}）" if cfg.telegram_proxy else ""
        print(f"✅ Telegram　已登录 @{me.username}{proxy}")
    except StartupError as exc:
        print(f"❌ Telegram\n   {str(exc).replace(chr(10), chr(10) + '   ')}")
        return 1
    finally:
        await bot.session.close()

    rates = RateService(cfg)
    try:
        ok = await rates.refresh(force=True)
        rows = rates.status()
        live = [row for row in rows if row["currencies"]]
        if not live:
            print("❌ 汇率源　　一个都没连上，检查服务器出网或设 DISABLED_PROVIDERS")
            return 1
        print(f"{'✅' if ok >= 2 else '⚠️ '} 汇率源　　{len(live)}/{len(rows)} 个可用")
        for row in rows:
            mark = "🟢" if row["currencies"] else "🔴"
            detail = f"{row['currencies']:>4} 种货币" if row["currencies"] else (row["error"] or "无数据")[:60]
            print(f"     {mark} {row['name']:<13} {detail}")
        try:
            rate = rates.get_rate("USD", "CNY")
            print(f"✅ 试算　　　1 USD = {rate.value:.4f} CNY（来自 {'/'.join(rate.sources)}）")
        except Exception as exc:  # noqa: BLE001
            print(f"⚠️  试算　　　USD/CNY 拿不到：{exc}")
    finally:
        await rates.http.close()

    print("─" * 46 + "\n全部通过，可以 python run.py 正式启动了。")
    return 0


def main(argv: list[str] | None = None) -> None:
    args = argv if argv is not None else sys.argv[1:]
    try:
        if args and args[0] in ("--check", "-c", "check"):
            raise SystemExit(asyncio.run(self_check()))
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
    except StartupError as exc:
        print(f"\n❌ 启动失败\n\n{exc}\n", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
