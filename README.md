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

## 二、安装

### 第 0 步：拿到 BOT_TOKEN（约 1 分钟）

1. 在 Telegram 里搜 **@BotFather**，点 Start
2. 发送 `/newbot`
3. 先取一个显示名（中文也行，比如「汇率助手」）
4. 再取一个用户名，**必须以 `bot` 结尾**，比如 `my_huilv_bot`
5. BotFather 会回一串 token，形如 `123456789:AAEhBOweik6ad9r_wAbCdEf...`，复制好
6. 顺手开一下 inline 模式：发 `/setinline` → 选中你的 bot → 提示语填 `100 usd jpy`

> token 等于账号密码，别提交进 Git、别发群里。泄露了就去 BotFather 发 `/revoke` 重置。

---

### 方式 A：Docker（推荐）

机器上有 Docker 就行，不用管 Python 版本。

```bash
git clone https://github.com/doudoudoubao/huobihuansuan.git
cd huobihuansuan

cp .env.example .env
nano .env            # 把 BOT_TOKEN=  后面填上刚才那串

docker compose up -d --build
docker compose logs -f
```

日志里出现 `已登录为 @你的bot名` 就成了，去 Telegram 找它发个 `100rmb` 试试。

日常管理：

```bash
docker compose logs -f          # 看日志
docker compose restart          # 重启
docker compose down             # 停止
docker compose up -d --build    # 改了代码后重新部署
```

---

### 方式 B：直接用 Python 跑

需要 **Python 3.11 或更高**（`python3 -V` 确认一下）。

```bash
git clone https://github.com/doudoudoubao/huobihuansuan.git
cd huobihuansuan

python3 -m venv .venv
source .venv/bin/activate        # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt

cp .env.example .env             # Windows: copy .env.example .env
# 编辑 .env 填入 BOT_TOKEN

python run.py --check            # 先自检，见下
python run.py                    # 正式启动
```

按 `Ctrl+C` 停止。

---

### 启动前：先自检一遍

正式启动前建议先跑：

```bash
python run.py --check
```

它会依次验证配置、数据库、Telegram 连通性和 7 个汇率源，输出类似：

```
🩺 部署自检
──────────────────────────────────────────────
✅ 配置　　　token 格式正确，数据目录 /app/data
✅ 数据库　　/app/data/bot.db 可读写
✅ Telegram　已登录 @my_huilv_bot
✅ 汇率源　　6/7 个可用
     🟢 yahoo            22 种货币
     🟢 binance          31 种货币
     🔴 coingecko        被限流 (429)
     ...
✅ 试算　　　1 USD = 7.2431 CNY（来自 yahoo）
──────────────────────────────────────────────
全部通过，可以 python run.py 正式启动了。
```

任何一步失败都会直接告诉你原因和怎么修，不会甩一堆 traceback。
Docker 下自检：`docker compose run --rm bot python run.py --check`。

---

### 让它开机自启（systemd，Linux 服务器）

用 Docker 的话 `restart: unless-stopped` 已经管了，这段可跳过。

```bash
sudo tee /etc/systemd/system/huobihuansuan.service > /dev/null <<EOF
[Unit]
Description=Currency Converter Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$PWD
ExecStart=$PWD/.venv/bin/python $PWD/run.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now huobihuansuan
sudo systemctl status huobihuansuan       # 看状态
journalctl -u huobihuansuan -f            # 看日志
```

---

### 大陆服务器：配代理

`api.telegram.org` 在大陆直连不通，在 `.env` 里加一行：

```bash
TELEGRAM_PROXY=http://127.0.0.1:7890        # 或 socks5://127.0.0.1:1080
```

代理跑在宿主机、bot 跑在 Docker 里时，把地址写成 `http://host.docker.internal:7890`，
并在 `docker-compose.yml` 的 `bot` 服务下加：

```yaml
    extra_hosts:
      - "host.docker.internal:host-gateway"
```

留空则直连；留空时也会自动沿用环境变量 `HTTPS_PROXY`。

> 数据源那边（Yahoo / Binance 等）大多在大陆能直连，但如果 `--check` 显示大片红色，
> 说明服务器出网受限，最省事的办法是直接换一台境外小鸡。

---

### BotFather 的两个可选开关

1. `/setinline` —— 不开的话 `@你的bot 100 usd jpy` 这种用法不可用（**建议开**）
2. `/setprivacy` → `Disable` —— 让 bot 在群里能读到普通消息。
   保持默认的 `Enable` 也能用，只是群里必须 @它、回复它或用 `/c`

命令菜单（输入 `/` 弹出的那个列表）启动时自动注册，不用手动 `/setcommands`。

---

### 装完之后

数据全在 `./data/` 里（SQLite + 汇率缓存），**备份这个目录就等于备份了一切**。
升级只要 `git pull` 然后重启（Docker 用户加 `--build`），数据库会自动兼容。

---

### 常见问题

| 现象 | 原因和解法 |
| --- | --- |
| `❌ 缺少 BOT_TOKEN` | `.env` 没建，或者 `BOT_TOKEN=` 后面是空的 |
| `❌ BOT_TOKEN 格式不对` | 复制时漏字符，或把引号一起粘进去了 |
| `❌ 401 Unauthorized` | token 错了或被 `/revoke` 过，去 BotFather `/mybots` 重新拿 |
| `❌ 连不上 api.telegram.org` | 需要代理，见上面「大陆服务器」一节 |
| bot 不回话 | 先在私聊里发 `/start`；看 `docker compose logs -f` 有没有报错 |
| 群里不回话 | 正常：群里要 @它、回复它，或用 `/c 100 usd cny`；想让它读所有消息就关 privacy |
| `@bot ...` 没结果 | BotFather 里没开 `/setinline` |
| 回复里写「数据较旧」 | 汇率源暂时连不上，发 `/status` 看哪个红了 |
| `/chart` 没图只有字符 | 没装 matplotlib，`pip install matplotlib` 即可 |
| 端口被占用 | 只有 webhook 模式才用端口，长轮询模式不需要，把 `WEBHOOK_BASE` 留空 |

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
| `TELEGRAM_PROXY` | 空 | 访问 api.telegram.org 的代理，支持 http / socks5 |
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
python -m pytest              # 全部离线用例，不打真实 API
python -m pyflakes bot tests run.py
python run.py --check         # 连真实环境跑一遍（需要 BOT_TOKEN）
```

数据源的解析逻辑用录制好的响应体做单测（`tests/test_providers.py`），
汇率服务可以用 `RateService.inject()` 直接喂一张报价表，方便离线调试。

---

## 六、说明

汇率为市场中间参考价，用于日常估算。实际结汇、购汇、交易请以银行或交易所的
实时报价为准。
