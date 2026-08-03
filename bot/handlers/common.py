"""入口命令：/start /help /about /me。"""

from __future__ import annotations

import logging
from decimal import Decimal

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from .. import currencies as cur_mod
from .. import formatting as fmt
from ..config import Config
from ..db import Database, UserPrefs
from ..i18n import t
from ..keyboards import settings_keyboard
from ..rates.service import RateService

log = logging.getLogger(__name__)

router = Router(name="common")

HELP_ZH = """📖 <b>使用手册</b>

<b>① 直接打字换算（推荐）</b>
<code>100rmb</code>　<code>100</code>　只发金额 → 一屏常用货币（默认 10 个）
<code>100 usd cny</code>　<code>100usd</code>
<code>100美元换人民币</code>　<code>1000円多少钱</code>　<code>100刀</code>
<code>$100</code>　<code>￥500</code>　<code>🇯🇵1000</code>
<code>100 usd cny jpy krw</code>　一次换多种
<code>(23.5+40)*3 eur cny</code>　算式直接算
<code>1.5k usd</code>　<code>10万日元</code>　<code>2亿越南盾</code>
<code>100 usd cny +2%</code>　带手续费（-2% 表示加点）

<b>② 行情</b>
/rate usd cny　当前汇率 + 24h 涨跌
/chart usd cny 30　走势图（7/30/90/365 天）
/hist usd cny 2024-01-01　历史某天汇率
/refresh　立刻拉取最新汇率
/status　各数据源健康状况

<b>③ 提醒与播报</b>
/alert usd cny &gt; 7.3　涨到就通知
/alert usd cny &lt; 7.0　跌到就通知
/alert btc usdt %5　24h 波动超 5% 通知
/alerts　查看/删除提醒
/subscribe 09:00 usd cny jpy　每天定时播报
/subs　查看/取消播报

<b>④ 个性化</b>
/setbase CNY　默认币种
/fav　常用币种面板，点按增删（决定「只发金额」时列哪些）
/fav USD EUR JPY HKD　整份替换
/add 韩元 泰铢　追加；/del 英镑　移除
/fee 2　默认手续费；/fee off 关闭
/decimals 2　小数位
/lang　中英切换
/settings　图形化设置面板

<b>⑤ 任意聊天内使用</b>
输入 <code>@{username} 100 usd jpy</code>，选中结果直接发出去。

<b>⑥ 群里怎么用</b>
@我、回复我，或用 <code>/c 100 usd cny</code>。
写明货币的换算式我才会接话，不会刷屏。

<b>货币</b>：/list 全部列表　/search 韩 关键词检索
支持 100+ 法币、30+ 加密货币与黄金白银。"""

HELP_EN = """📖 <b>Manual</b>

<b>① Just type (recommended)</b>
<code>100usd</code>　<code>100</code>　amount alone → 10 favourites at once
<code>100 usd cny</code>
<code>$100</code>　<code>￥500</code>　<code>🇯🇵1000</code>
<code>100 usd cny jpy krw</code>　multi-target
<code>(23.5+40)*3 eur cny</code>　inline math
<code>1.5k usd</code>　<code>2.4m jpy</code>
<code>100 usd cny +2%</code>　apply a fee (−2% = markup)

<b>② Market</b>
/rate usd cny
/chart usd cny 30
/hist usd cny 2024-01-01
/refresh · /status

<b>③ Alerts &amp; digests</b>
/alert usd cny &gt; 7.3
/alert usd cny &lt; 7.0
/alert btc usdt %5
/alerts · /subscribe 09:00 usd cny · /subs

<b>④ Preferences</b>
/fav　tap-to-toggle favourites panel (what an amount alone lists)
/add krw thb · /del gbp · /setbase USD · /fee 2
/decimals 2 · /lang · /settings

<b>⑤ Anywhere</b>
Type <code>@{username} 100 usd jpy</code> in any chat.

<b>⑥ In groups</b>
Mention me, reply to me, or use <code>/c 100 usd cny</code>.

<b>Currencies</b>: /list · /search &lt;keyword&gt;
100+ fiat, 30+ crypto, plus gold and silver."""


@router.message(CommandStart())
async def cmd_start(
    message: Message, prefs: UserPrefs, rates: RateService, config: Config
) -> None:
    me = await message.bot.me()
    username = me.username or "bot"
    text = (
        f"{t(prefs.lang, 'start_title')}\n\n"
        f"{t(prefs.lang, 'start_body', username=username)}"
    )
    await message.answer(text, disable_web_page_preview=True)

    # 顺手演示一次「只发金额」的效果，第一眼就知道长什么样
    from .core import build_conversion

    source = prefs.base
    rendered = await build_conversion(
        Decimal(100),
        source,
        prefs.targets_for(source, limit=config.multi_target_count),
        prefs,
        rates,
    )
    if rendered.ok:
        await message.answer(rendered.text, reply_markup=rendered.keyboard, disable_web_page_preview=True)


@router.message(Command("help", "bz", "manual"))
async def cmd_help(message: Message, prefs: UserPrefs) -> None:
    me = await message.bot.me()
    template = HELP_ZH if prefs.lang == "zh" else HELP_EN
    await message.answer(template.format(username=me.username or "bot"), disable_web_page_preview=True)


@router.message(Command("me", "whoami", "profile"))
async def cmd_me(message: Message, prefs: UserPrefs, db: Database) -> None:
    top = await db.top_codes(prefs.user_id, limit=8)
    alerts = await db.count_alerts(prefs.user_id)
    subs = await db.count_subscriptions(prefs.user_id)
    base_meta = cur_mod.get(prefs.base)
    lines = [
        "👤 <b>我的设置</b>" if prefs.lang == "zh" else "👤 <b>Your profile</b>",
        "",
        f"💰 {base_meta.flag}{prefs.base}",
        f"⭐ {fmt.esc(' '.join(prefs.favorites) or '—')}",
        f"🔔 {alerts}　📅 {subs}",
        f"🔥 {fmt.esc(' '.join(top) or '—')}",
    ]
    await message.answer("\n".join(lines), reply_markup=settings_keyboard(prefs))


@router.message(Command("about", "gy"))
async def cmd_about(message: Message, prefs: UserPrefs, rates: RateService) -> None:
    sources = ", ".join(sorted({row["name"] for row in rates.status() if row["currencies"]}))
    if prefs.lang == "zh":
        text = (
            "💱 <b>货币换算助手</b>\n\n"
            "多数据源聚合，法币约每分钟、加密货币约每 15 秒刷新一次，"
            "单一数据源故障会自动切换到备用源。\n\n"
            f"<b>当前在用</b>：{fmt.esc(sources or '—')}\n\n"
            "汇率为市场参考价，实际结汇/购汇请以银行或交易所报价为准。"
        )
    else:
        text = (
            "💱 <b>Currency Converter</b>\n\n"
            "Aggregates several providers with automatic failover. "
            "Fiat refreshes about once a minute, crypto about every 15 seconds.\n\n"
            f"<b>Live sources</b>: {fmt.esc(sources or '—')}\n\n"
            "Rates are indicative mid-market quotes, not a dealing rate."
        )
    await message.answer(text, disable_web_page_preview=True)
