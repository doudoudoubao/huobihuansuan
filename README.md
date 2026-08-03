# 货币换算 · Telegram Bot

一个「不用记命令」的实时货币换算机器人。发 `100rmb` 就直接铺开一屏常用货币的汇率，
发 `100 usd cny` 就出单对详情；`100美元换人民币`、`$100`、`(23.5+40)*3 eur cny`
这些写法也都认。多数据源聚合、自动故障转移，法币约每分钟、加密货币约每 15 秒刷新一次。

---

## 一、能干什么

### 1. 直接打字换算（核心，不需要命令）

| 你发什么 | 它怎么理解 |
| --- | --- |
| `100 usd cny` / `100usd cny` | 100 美元 → 人民币 |
| `100美元换人民币` / `100刀多少人民币` | 中文自然语言 |
| `1000円是多少钱` / `100块 日元` | 俚语、汉字货币名 |
| `$100` / `￥500` / `🇯🇵1000` | 货币符号、国旗 emoji |
| `100rmb` / `100` | **只发金额就出一屏常用货币（默认 10 个）** |
| `100 usd` | 美元 → 你的常用币种列表 |
| `100 usd cny jpy krw` | 一次换多种 |
| `(23.5+40)*3 eur cny` | 先算式后换算 |
| `1.5k usd` / `10万日元` / `2亿越南盾` | k / w / m / b / 千 / 万 / 亿 |
| `100 usd cny +2%` | 扣 2% 手续费；`-2%` 表示加点 |

`¥` 这类有歧义的符号会跟着你的默认币种走：默认 CNY 就解析成人民币，默认 JPY 就是日元。

**只发金额时**（`100rmb`、`100`）直接铺开 10 行常用货币，下方按钮可以点进单个货币的
详情、刷新，或一键打开 ⭐ 常用币种面板。**写明目标货币时**（`100 usd cny`）给单对详情卡，
按钮是 **⇄ 反向 · 🔄 刷新 · 📈 走势 · 🔔 提醒** 加一排常用币种快捷切换。

#### 常用币种（决定「只发金额」列出哪些）

```
/fav                     打开面板，✅/▫️ 点按增删，支持翻页
/fav USD EUR JPY HKD     整份替换
/fav +KRW +THB           追加
/fav -GBP                移除
/add 韩元 泰铢            追加（中文也认）
/del 英镑                 移除
```

默认 10 个（USD HKD EUR JPY GBP KRW TWD SGD AUD THB），最多可收藏 20 个；
不够 10 个时会自动用主流货币补齐，保证一次总能看到一屏。
条数和上限可用 `MULTI_TARGET_COUNT` / `MAX_FAVORITES` 调整。

### 2. 实时汇率

- **法币**：Yahoo Finance（准实时）→ Frankfurter/ECB → open.er-api → currency-api
- **加密**：Binance → OKX → CoinGecko → currency-api
- 所有源统一折算到 USD 基准表，任意货币对走交叉汇率
- 单源失败自动退避重试并切到备用源，`/status` 可查看每个源的健康度
- 本地缓存落盘，重启后先用缓存顶上，不会出现空窗

### 3. 行情查询

```
/rate usd cny              当前汇率 + 1h/24h 涨跌
/chart usd cny 30          走势图 PNG（7 / 30 / 90 / 365 天）
/hist usd cny 2024-01-01   历史某天的汇率，并和今天对比
/refresh                   立刻强制刷新
/status                    数据源健康状况
```

### 4. 主动推送

```
/alert usd cny > 7.3       涨到 7.3 通知我（触发一次后自动停用）
/alert usd cny < 7.0       跌到 7.0 通知我
/alert usd cny 7.15        只给数字，自动判断是涨到还是跌到
/alert btc usdt %5         24 小时波动超过 5% 就通知（持续生效）
/alerts                    查看 / 一键删除
/subscribe 09:00 usd cny jpy   每天定时播报
/subs                      查看 / 取消播报
```

### 5. 个性化

```
/setbase CNY               默认币种
/fav                       常用币种面板（见上）
/fee 2                     默认手续费，之后每次换算自动带上；/fee off 关闭
/decimals 2                小数位
/lang                      中 / 英切换
/settings                  图形化设置面板
```

金额显示会自动适配数量级：日元韩元不显示小数，比特币这类小数值自动补足有效位数。

### 6. 到处都能用

- **私聊**：随便发，直接出结果
- **群聊**：@我、回复我，或 `/c 100 usd cny`；只有写明货币的换算式才会接话，不刷屏
- **Inline 模式**：在任何聊天框输入 `@你的bot 100 usd jpy`，选中即发送，
  第一条还会给一个「一次换多种」的汇总卡片

### 7. 覆盖范围

100+ 法币、30+ 加密货币，外加黄金 / 白银 / 铂金（`/list`、`/search 韩` 查询）。

---

## 二、跑起来

### 方式 A：本机直接跑

```bash
git clone <repo> && cd huobihuansuan
pip install -r requirements.txt

cp .env.example .env
# 编辑 .env，把 @BotFather 给的 BOT_TOKEN 填进去

python run.py
```

### 方式 B：Docker

```bash
cp .env.example .env    # 填好 BOT_TOKEN
docker compose up -d --build
docker compose logs -f
```

数据落在 `./data/`（SQLite + 汇率缓存），备份这个目录就够了。

### BotFather 需要做的两件事

1. `/setinline` 打开 inline 模式（否则 `@bot 100 usd jpy` 用不了），
   placeholder 建议填 `100 usd jpy`
2. 想让 bot 在群里能读到普通消息，`/setprivacy` → `Disable`；
   保持 `Enable` 也能用，只是群里必须 @它或用 `/c`

命令菜单在启动时自动注册，不用手动 `/setcommands`。

---

## 三、配置项

全部通过环境变量（或 `.env`）注入，完整清单见 `.env.example`。常调的几个：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `BOT_TOKEN` | — | **必填** |
| `FIAT_REFRESH_SECONDS` | `60` | 法币后台刷新间隔 |
| `CRYPTO_REFRESH_SECONDS` | `15` | 加密货币刷新间隔 |
| `STALE_AFTER_SECONDS` | `900` | 超过此时长的数据会在回复里标注「较旧」 |
| `DEFAULT_BASE` | `CNY` | 新用户的默认币种 |
| `DEFAULT_FAVORITES` | 10 个主流货币 | 新用户的常用列表 |
| `MULTI_TARGET_COUNT` | `10` | 只发金额时一次列几行 |
| `MAX_FAVORITES` | `20` | 每个用户最多收藏几个 |
| `DISABLED_PROVIDERS` | 空 | 逗号分隔，禁用指定数据源 |
| `WEBHOOK_BASE` | 空 | 留空走长轮询；填了就切 webhook |

Webhook 模式下会额外暴露 `GET /healthz` 供探活。

---

## 四、代码结构

```
bot/
├── config.py         环境变量配置
├── currencies.py     货币元数据 + 别名词典（中文名/俚语/符号/国旗）
├── parser.py         自然语言与算式解析（沙箱化的 AST 求值）
├── formatting.py     数字格式化与消息渲染
├── i18n.py           中英文案表
├── keyboards.py      Inline 键盘与 callback_data 编解码
├── chart.py          走势图渲染（matplotlib 可选）
├── db.py             SQLite：偏好 / 提醒 / 订阅 / 使用统计
├── middlewares.py    偏好注入 + 限流
├── scheduler.py      提醒巡检 + 每日播报
├── main.py           装配与启动（长轮询 / webhook）
├── rates/
│   ├── base.py       Provider 基类、HTTP 客户端、健康度与退避
│   ├── providers.py  7 个数据源的具体实现
│   └── service.py    聚合、缓存、交叉汇率、涨跌幅、历史
└── handlers/
    ├── core.py       换算主流程（消息/回调/inline 共用）
    ├── convert.py    自由文本换算 + 结果卡按钮
    ├── market.py     /rate /chart /hist /search /list /refresh /status
    ├── alerts.py     /alert /subscribe 系列
    ├── settings.py   /settings 及设置面板
    ├── inline.py     Inline 模式
    └── common.py     /start /help /about /me
```

### 加一个数据源

继承 `RateProvider`，实现 `fetch()` 返回「1 USD = X 单位目标货币」的映射，
然后加进 `providers.ALL_PROVIDER_CLASSES`。`priority` 越小越优先，
服务层会自动做优先级合并、失败退避和交叉汇率计算。

---

## 五、测试

```bash
python -m pytest        # 全部离线用例，不打真实 API
python -m pyflakes bot tests run.py
```

数据源的解析逻辑用录制好的响应体做单测（`tests/test_providers.py`），
汇率服务可以用 `RateService.inject()` 直接喂一张报价表，方便离线调试。

---

## 六、说明

汇率为市场中间参考价，用于日常估算。实际结汇、购汇、交易请以银行或交易所的
实时报价为准。
