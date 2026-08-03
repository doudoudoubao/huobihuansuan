from decimal import Decimal

import pytest

from bot.config import Config
from bot.db import Database
from bot.rates.service import RateService
from bot.scheduler import Scheduler


@pytest.fixture()
def config(tmp_path):
    return Config(db_path=str(tmp_path / "test.db"), default_base="CNY")


@pytest.fixture()
async def db(config):
    database = Database(config)
    await database.connect()
    yield database
    await database.close()


@pytest.fixture()
def rates(config):
    service = RateService(config)
    service.inject(
        "stub",
        {"USD": Decimal(1), "CNY": Decimal("7.2"), "JPY": Decimal(150), "USDT": Decimal(1), "BTC": Decimal("0.000015")},
    )
    return service


class FakeBot:
    """只记录发出去的消息，不碰网络。"""

    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id, text, **_kwargs):
        self.sent.append((chat_id, text))


async def test_prefs_defaults_and_update(db, config):
    prefs = await db.get_prefs(42)
    assert prefs.base == "CNY"
    assert prefs.favorites == config.default_favorites

    updated = await db.update_prefs(42, base="USD", decimals=4, favorites=["JPY", "KRW"])
    assert updated.base == "USD" and updated.decimals == 4

    db._cache.clear()  # 强制走一次真实读取
    reread = await db.get_prefs(42)
    assert reread.base == "USD"
    assert reread.favorites == ["JPY", "KRW"]


async def test_usage_tracking(db):
    await db.note_usage(1, ["USD", "JPY"])
    await db.note_usage(1, ["USD"])
    assert (await db.top_codes(1))[0] == "USD"


async def test_alert_crud(db):
    alert_id = await db.add_alert(1, 100, "USD", "CNY", ">", Decimal("7.5"))
    alerts = await db.list_alerts(1)
    assert len(alerts) == 1 and alerts[0].id == alert_id
    assert "≥ 7.5" in alerts[0].describe()

    assert await db.delete_alert(1, alert_id) is True
    assert await db.delete_alert(1, alert_id) is False
    assert await db.list_alerts(1) == []


async def test_alert_fires_and_deactivates(db, rates, config):
    bot = FakeBot()
    scheduler = Scheduler(bot, db, rates, config)  # type: ignore[arg-type]

    # 目标 7.0，现价 7.2 —— 立即触发
    await db.add_alert(1, 555, "USD", "CNY", ">", Decimal("7.0"))
    assert await scheduler.check_alerts() == 1
    assert bot.sent and bot.sent[0][0] == 555

    # 一次性提醒触发后应停用，不再重复推送
    assert await scheduler.check_alerts() == 0
    assert len(bot.sent) == 1


async def test_alert_not_fired_when_condition_unmet(db, rates, config):
    bot = FakeBot()
    scheduler = Scheduler(bot, db, rates, config)  # type: ignore[arg-type]
    await db.add_alert(1, 555, "USD", "CNY", ">", Decimal("9.9"))
    assert await scheduler.check_alerts() == 0
    assert bot.sent == []


async def test_percent_alert_uses_baseline(db, rates, config):
    bot = FakeBot()
    scheduler = Scheduler(bot, db, rates, config)  # type: ignore[arg-type]
    # 基准 7.2、阈值 1%：不动就不该响
    await db.add_alert(1, 555, "USD", "CNY", "pct", Decimal(1), repeat=True, baseline=Decimal("7.2"))
    assert await scheduler.check_alerts() == 0

    # 汇率跳到 7.5（+4.2%）后触发
    rates.inject("stub", {"USD": Decimal(1), "CNY": Decimal("7.5")})
    assert await scheduler.check_alerts() == 1
    assert "波动" in bot.sent[0][1] or "moved" in bot.sent[0][1]


async def test_subscription_crud(db):
    sub_id = await db.add_subscription(1, 200, "CNY", ["USD", "JPY"], "09:00", "Asia/Shanghai")
    subs = await db.list_subscriptions(1)
    assert len(subs) == 1 and subs[0].quotes == ["USD", "JPY"]
    assert await db.delete_subscription(1, sub_id) is True


async def test_deactivate_for_chat(db):
    await db.add_alert(1, 777, "USD", "CNY", ">", Decimal(1))
    await db.add_subscription(1, 777, "CNY", ["USD"], "09:00", "UTC")
    await db.deactivate_for_chat(777)
    assert await db.list_alerts(1) == []
    assert await db.list_subscriptions(1) == []


async def test_stats(db):
    await db.get_prefs(1)
    await db.add_alert(1, 1, "USD", "CNY", ">", Decimal(1))
    stats = await db.stats()
    assert stats["users"] >= 1 and stats["alerts"] == 1
