"""极简双语文案表。t(lang, key, **kwargs) 找不到就回落到中文，再回落到 key 本身。"""

from __future__ import annotations

from typing import Any

ZH: dict[str, str] = {
    "start_title": "💱 <b>货币换算助手</b>",
    "start_body": (
        "直接发消息就能换算，<b>不用记命令</b>：\n"
        "• <code>100rmb</code>　<code>100</code>　只发金额就出一屏常用货币\n"
        "• <code>100 usd cny</code>　<code>100美元换人民币</code>\n"
        "• <code>100刀</code>　<code>1000円多少钱</code>　<code>$100</code>\n"
        "• <code>(23.5+40)*3 eur cny</code>　算式直接算\n"
        "• <code>100 usd cny jpy krw</code>　一次换多种\n"
        "• <code>100 usd cny +2%</code>　带手续费\n"
        "• <code>1.5k usd</code>　<code>10万日元</code>　支持万/亿/k/w\n\n"
        "那一屏列哪些货币由「常用币种」决定：/fav 点按增删，"
        "或 <code>/add 韩元</code>、<code>/del 英镑</code>。\n\n"
        "在任意聊天里输入 <code>@{username} 100 usd jpy</code> 可直接发送结果。\n\n"
        "常用命令：/rate 汇率 · /chart 走势 · /alert 到价提醒 · /subscribe 每日播报 · /settings 设置 · /help 全部帮助"
    ),
    "help_title": "📖 <b>使用手册</b>",
    "result_header": "💱 <b>{amount} {base}</b>",
    "rate_line": "1 {base} = {rate} {quote}",
    "inverse_line": "1 {quote} = {rate} {base}",
    "fee_line": "已扣手续费 {fee}%（{amount} {quote}）",
    "fee_line_bonus": "已加点 {fee}%（+{amount} {quote}）",
    "source_line": "数据源 {sources} · {ago}",
    "stale_warn": "⚠️ 汇率数据较旧（{ago}），正在重试刷新",
    "unavailable": "😥 暂时拿不到 <b>{code}</b> 的报价，稍后再试或换个币种。",
    "unknown_currency": "没认出货币：<code>{tokens}</code>\n试试 /search {first} 或直接发 <code>100 usd cny</code>",
    "no_match": "没看懂这句 🤔\n试试 <code>100 usd cny</code> 或 <code>100美元换人民币</code>，也可以 /help",
    "same_currency": "源币种和目标币种一样（{code}），换了个寂寞 😅",
    "refreshed": "✅ 已刷新（{n} 个数据源）",
    "refresh_failed": "⚠️ 刷新失败，仍在用缓存数据",
    "updated_at": "更新于 {ago}",
    "just_now": "刚刚",
    "seconds_ago": "{n} 秒前",
    "minutes_ago": "{n} 分钟前",
    "hours_ago": "{n} 小时前",
    "days_ago": "{n} 天前",
    "btn_reverse": "⇄ 反向",
    "btn_refresh": "🔄 刷新",
    "btn_chart": "📈 走势",
    "btn_alert": "🔔 提醒",
    "btn_more": "➕ 更多币种",
    "btn_edit_fav": "⭐ 常用",
    "btn_fav_reset": "↺ 恢复默认",
    "btn_back": "◀️ 返回",
    "btn_close": "✖️ 关闭",
    "settings_title": "⚙️ <b>设置</b>",
    "settings_base": "默认币种：<b>{base}</b>",
    "settings_fav": "收藏币种：<b>{fav}</b>",
    "settings_decimals": "小数位：<b>{n}</b>",
    "settings_group": "千分位：<b>{state}</b>",
    "settings_source": "显示数据源：<b>{state}</b>",
    "settings_change": "显示涨跌：<b>{state}</b>",
    "settings_lang": "语言：<b>{name}</b>",
    "settings_tz": "时区：<b>{tz}</b>",
    "on": "开",
    "off": "关",
    "base_set": "✅ 默认币种已设为 <b>{base}</b>",
    "fav_set": "✅ 常用币种已更新（{n} 个）：\n<b>{fav}</b>",
    "fav_limit": "常用币种最多 {max} 个，多出来的已忽略。",
    "fav_reset": "↺ 已恢复默认常用币种",
    "fav_empty": "收藏列表为空，用 <code>/fav USD JPY EUR</code> 设置。",
    "usage_base": "用法：<code>/setbase CNY</code>",
    "usage_fav": (
        "⭐ <b>常用币种</b>（决定只发金额时列出哪些）\n"
        "当前（{n}/{max}）：{fav}\n\n"
        "点下面的按钮增删，或者直接打字：\n"
        "<code>/fav USD EUR JPY HKD</code>　整份替换\n"
        "<code>/fav +KRW +THB</code>　追加\n"
        "<code>/fav -GBP</code>　移除\n"
        "也可以用 <code>/add 韩元</code> 和 <code>/del 英镑</code>"
    ),
    "usage_alert": (
        "用法：\n"
        "<code>/alert usd cny &gt; 7.3</code> 涨到就提醒\n"
        "<code>/alert usd cny &lt; 7.0</code> 跌到就提醒\n"
        "<code>/alert btc usdt %5</code> 24 小时波动超 5% 提醒"
    ),
    "usage_sub": "用法：<code>/subscribe 09:00 usd cny jpy</code>",
    "usage_chart": "用法：<code>/chart usd cny 30</code>（天数可选，默认 30）",
    "usage_hist": "用法：<code>/hist usd cny 2024-01-01</code>",
    "alert_added": "🔔 已添加提醒 #{id}：{desc}\n当前 {current}",
    "alert_limit": "提醒数量已达上限（{n} 条），先用 /alerts 删掉几个。",
    "alert_none": "还没有提醒。用 <code>/alert usd cny &gt; 7.3</code> 添加一条。",
    "alert_list_title": "🔔 <b>我的提醒</b>",
    "alert_deleted": "🗑 已删除提醒 #{id}",
    "alert_not_found": "没找到提醒 #{id}",
    "alert_cleared": "🗑 已清空 {n} 条提醒",
    "alert_fired": "🔔 <b>到价提醒</b>\n{desc}\n当前：<b>{current}</b>",
    "alert_fired_pct": "🔔 <b>波动提醒</b>\n{pair} 24h 变动 <b>{change}%</b>\n当前：<b>{current}</b>",
    "sub_added": "📅 已订阅 #{id}：{desc}",
    "sub_limit": "订阅数量已达上限（{n} 条）。",
    "sub_none": "还没有定时播报。用 <code>/subscribe 09:00 usd cny</code> 添加。",
    "sub_list_title": "📅 <b>我的定时播报</b>",
    "sub_deleted": "🗑 已取消订阅 #{id}",
    "sub_not_found": "没找到订阅 #{id}",
    "daily_title": "📅 <b>每日汇率播报</b>",
    "chart_title": "📈 <b>{base}/{quote}</b> 近 {days} 天",
    "chart_stats": "最高 {high} · 最低 {low} · 区间涨跌 {change}%",
    "chart_failed": "📉 拿不到 {base}/{quote} 的历史数据：{reason}",
    "hist_result": "🗓 <b>{day}</b>　1 {base} = <b>{rate}</b> {quote}\n对比今天 {today}（{change}%）",
    "search_none": "没找到匹配「{q}」的货币。",
    "search_title": "🔎 <b>搜索「{q}」</b>",
    "list_title": "🌍 <b>支持的货币</b>（共 {n} 种）",
    "rate_title": "💹 <b>{base} → {quote}</b>",
    "change_24h": "24h {arrow} {pct}%",
    "throttled": "慢一点～",
    "error_generic": "出了点问题，请稍后再试。",
    "lang_set": "✅ 语言已切换为中文",
    "inline_title": "{amount} {base} = {result} {quote}",
    "inline_desc": "1 {base} = {rate} {quote} · {ago}",
    "inline_empty_title": "输入金额和货币，例如 100 usd jpy",
    "inline_empty_desc": "支持中文、符号和算式",
    "status_title": "🩺 <b>数据源状态</b>",
}

EN: dict[str, str] = {
    "start_title": "💱 <b>Currency Converter</b>",
    "start_body": (
        "Just type — <b>no commands needed</b>:\n"
        "• <code>100usd</code>　<code>100</code>　an amount alone lists your favourites\n"
        "• <code>100 usd cny</code>　<code>100 bucks to yen</code>\n"
        "• <code>$100</code>　<code>￥1000</code>\n"
        "• <code>(23.5+40)*3 eur cny</code>　inline math\n"
        "• <code>100 usd cny jpy krw</code>　multi-target\n"
        "• <code>100 usd cny +2%</code>　with a fee\n"
        "• <code>1.5k usd</code>　k / m / b suffixes\n\n"
        "That list is your favourites: /fav to tap through them, "
        "or <code>/add krw</code> / <code>/del gbp</code>.\n\n"
        "In any chat type <code>@{username} 100 usd jpy</code> to send a result.\n\n"
        "Commands: /rate · /chart · /alert · /subscribe · /settings · /help"
    ),
    "help_title": "📖 <b>Manual</b>",
    "result_header": "💱 <b>{amount} {base}</b>",
    "rate_line": "1 {base} = {rate} {quote}",
    "inverse_line": "1 {quote} = {rate} {base}",
    "fee_line": "fee {fee}% applied (−{amount} {quote})",
    "fee_line_bonus": "markup {fee}% applied (+{amount} {quote})",
    "source_line": "via {sources} · {ago}",
    "stale_warn": "⚠️ Rates are stale ({ago}); refreshing",
    "unavailable": "😥 No quote for <b>{code}</b> right now. Try again later.",
    "unknown_currency": "Unrecognised: <code>{tokens}</code>\nTry /search {first} or <code>100 usd cny</code>",
    "no_match": "Didn't get that 🤔\nTry <code>100 usd cny</code>, or /help",
    "same_currency": "Source and target are the same ({code}) 😅",
    "refreshed": "✅ Refreshed ({n} sources)",
    "refresh_failed": "⚠️ Refresh failed, serving cached rates",
    "updated_at": "updated {ago}",
    "just_now": "just now",
    "seconds_ago": "{n}s ago",
    "minutes_ago": "{n}m ago",
    "hours_ago": "{n}h ago",
    "days_ago": "{n}d ago",
    "btn_reverse": "⇄ Reverse",
    "btn_refresh": "🔄 Refresh",
    "btn_chart": "📈 Chart",
    "btn_alert": "🔔 Alert",
    "btn_more": "➕ More",
    "btn_edit_fav": "⭐ Favourites",
    "btn_fav_reset": "↺ Reset",
    "btn_back": "◀️ Back",
    "btn_close": "✖️ Close",
    "settings_title": "⚙️ <b>Settings</b>",
    "settings_base": "Home currency: <b>{base}</b>",
    "settings_fav": "Favourites: <b>{fav}</b>",
    "settings_decimals": "Decimals: <b>{n}</b>",
    "settings_group": "Thousands separator: <b>{state}</b>",
    "settings_source": "Show sources: <b>{state}</b>",
    "settings_change": "Show 24h change: <b>{state}</b>",
    "settings_lang": "Language: <b>{name}</b>",
    "settings_tz": "Timezone: <b>{tz}</b>",
    "on": "on",
    "off": "off",
    "base_set": "✅ Home currency set to <b>{base}</b>",
    "fav_set": "✅ Favourites updated ({n}):\n<b>{fav}</b>",
    "fav_limit": "At most {max} favourites; extras ignored.",
    "fav_reset": "↺ Favourites reset to defaults",
    "fav_empty": "No favourites yet. Use <code>/fav USD JPY EUR</code>.",
    "usage_base": "Usage: <code>/setbase USD</code>",
    "usage_fav": (
        "⭐ <b>Favourites</b> (what an amount-only message lists)\n"
        "Current ({n}/{max}): {fav}\n\n"
        "Tap below, or type:\n"
        "<code>/fav USD EUR JPY HKD</code>　replace\n"
        "<code>/fav +KRW +THB</code>　add\n"
        "<code>/fav -GBP</code>　remove\n"
        "or use <code>/add krw</code> and <code>/del gbp</code>"
    ),
    "usage_alert": (
        "Usage:\n"
        "<code>/alert usd cny &gt; 7.3</code>\n"
        "<code>/alert usd cny &lt; 7.0</code>\n"
        "<code>/alert btc usdt %5</code> (24h move ≥ 5%)"
    ),
    "usage_sub": "Usage: <code>/subscribe 09:00 usd cny jpy</code>",
    "usage_chart": "Usage: <code>/chart usd cny 30</code>",
    "usage_hist": "Usage: <code>/hist usd cny 2024-01-01</code>",
    "alert_added": "🔔 Alert #{id} created: {desc}\nNow {current}",
    "alert_limit": "Alert limit reached ({n}). Remove some with /alerts.",
    "alert_none": "No alerts yet. Try <code>/alert usd cny &gt; 7.3</code>.",
    "alert_list_title": "🔔 <b>Your alerts</b>",
    "alert_deleted": "🗑 Alert #{id} removed",
    "alert_not_found": "Alert #{id} not found",
    "alert_cleared": "🗑 Removed {n} alerts",
    "alert_fired": "🔔 <b>Alert</b>\n{desc}\nNow: <b>{current}</b>",
    "alert_fired_pct": "🔔 <b>Volatility alert</b>\n{pair} moved <b>{change}%</b> in 24h\nNow: <b>{current}</b>",
    "sub_added": "📅 Subscribed #{id}: {desc}",
    "sub_limit": "Subscription limit reached ({n}).",
    "sub_none": "No daily digests yet. Try <code>/subscribe 09:00 usd cny</code>.",
    "sub_list_title": "📅 <b>Your daily digests</b>",
    "sub_deleted": "🗑 Subscription #{id} cancelled",
    "sub_not_found": "Subscription #{id} not found",
    "daily_title": "📅 <b>Daily rates</b>",
    "chart_title": "📈 <b>{base}/{quote}</b> last {days} days",
    "chart_stats": "High {high} · Low {low} · Change {change}%",
    "chart_failed": "📉 No history for {base}/{quote}: {reason}",
    "hist_result": "🗓 <b>{day}</b>　1 {base} = <b>{rate}</b> {quote}\nvs today {today} ({change}%)",
    "search_none": "No currency matches «{q}».",
    "search_title": "🔎 <b>Search “{q}”</b>",
    "list_title": "🌍 <b>Supported currencies</b> ({n})",
    "rate_title": "💹 <b>{base} → {quote}</b>",
    "change_24h": "24h {arrow} {pct}%",
    "throttled": "Slow down a bit~",
    "error_generic": "Something went wrong, please retry.",
    "lang_set": "✅ Language switched to English",
    "inline_title": "{amount} {base} = {result} {quote}",
    "inline_desc": "1 {base} = {rate} {quote} · {ago}",
    "inline_empty_title": "Type an amount and currencies, e.g. 100 usd jpy",
    "inline_empty_desc": "Chinese, symbols and math all work",
    "status_title": "🩺 <b>Provider status</b>",
}

TABLES: dict[str, dict[str, str]] = {"zh": ZH, "en": EN}


def normalize_lang(code: str | None) -> str:
    if not code:
        return "zh"
    code = code.lower()
    if code.startswith("zh"):
        return "zh"
    return "en" if code.startswith("en") else ("zh" if code in TABLES else "en")


def t(lang: str, key: str, **kwargs: Any) -> str:
    table = TABLES.get(lang or "zh", ZH)
    template = table.get(key) or ZH.get(key) or key
    if not kwargs:
        return template
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError, ValueError):
        return template
