import time
from decimal import Decimal

import pytest

from bot.config import Config
from bot.rates.base import ProviderResult, to_decimal
from bot.rates.service import RateService, RateUnavailable

USD_TABLE = {
    "USD": Decimal(1),
    "CNY": Decimal("7.2"),
    "JPY": Decimal("150"),
    "EUR": Decimal("0.92"),
    "BTC": Decimal("0.000015"),
}


@pytest.fixture()
def service(tmp_path):
    config = Config(db_path=str(tmp_path / "test.db"))
    svc = RateService(config)
    svc.inject("stub", USD_TABLE)
    return svc


def test_cross_rate_via_usd(service):
    rate = service.get_rate("CNY", "JPY")
    assert rate.value == Decimal("150") / Decimal("7.2")
    assert rate.base == "CNY" and rate.quote == "JPY"


def test_identity_and_inverse(service):
    assert service.get_rate("USD", "USD").value == Decimal(1)
    rate = service.get_rate("USD", "CNY")
    assert rate.inverse == Decimal(1) / Decimal("7.2")


def test_unknown_currency_raises(service):
    with pytest.raises(RateUnavailable) as excinfo:
        service.get_rate("USD", "ZZZ")
    assert excinfo.value.code == "ZZZ"


def test_convert_applies_fee(service):
    conv = service.convert(Decimal(100), "USD", "CNY", fee_percent=Decimal(2))
    assert conv.gross == Decimal(720)
    assert conv.result == Decimal("705.6")
    assert conv.fee_amount == Decimal("14.4")
    assert conv.effective_rate == Decimal("7.056")


def test_convert_many_reports_missing(service):
    done, missing = service.convert_many(Decimal(1), "USD", ["CNY", "ZZZ", "JPY"])
    assert [c.quote for c in done] == ["CNY", "JPY"]
    assert missing == ["ZZZ"]


def test_priority_prefers_lower_number(service):
    """yahoo(10) 应该盖过 currency-api(50)，哪怕后者更晚写入。"""
    service.inject("currency-api", {"USD": Decimal(1), "CNY": Decimal("9.99")})
    service.inject("yahoo", {"USD": Decimal(1), "CNY": Decimal("7.11")})
    rate = service.get_rate("USD", "CNY")
    assert rate.value == Decimal("7.11")
    assert "yahoo" in rate.sources


def test_stale_flag(service):
    service.inject("stub", USD_TABLE, as_of=time.time() - 10_000)
    assert service.get_rate("USD", "CNY").stale is True


def test_change_percent_needs_history(service):
    assert service.change_percent("USD", "CNY") is None


def test_change_percent_uses_snapshots(service, monkeypatch):
    # 伪造一份 24 小时前的快照
    old = dict(USD_TABLE)
    old["CNY"] = Decimal("7.0")
    service._snapshots.insert(0, (time.time() - 86_400, old))
    change = service.change_percent("USD", "CNY")
    assert change is not None
    assert change == (Decimal("7.2") - Decimal(7)) / Decimal(7) * Decimal(100)


def test_available_codes(service):
    assert {"USD", "CNY", "JPY", "BTC"} <= service.available_codes()


def test_cache_roundtrip(tmp_path):
    config = Config(db_path=str(tmp_path / "test.db"))
    first = RateService(config)
    first.inject("stub", USD_TABLE)
    first._save_cache()

    second = RateService(config)
    second._load_cache()
    assert second.get_rate("USD", "CNY").value == Decimal("7.2")


def test_to_decimal_rejects_garbage():
    assert to_decimal("7.2") == Decimal("7.2")
    assert to_decimal(0) is None
    assert to_decimal(-1) is None
    assert to_decimal("nan") is None
    assert to_decimal(None) is None
    assert to_decimal("abc") is None


def test_provider_result_truthiness():
    assert not ProviderResult("x", {})
    assert ProviderResult("x", {"USD": Decimal(1)})
