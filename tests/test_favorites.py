"""「只发一个金额就出一屏常用货币」以及常用列表的增删。"""

from decimal import Decimal

import pytest

from bot import currencies as cur_mod
from bot import keyboards as kb
from bot.config import Config
from bot.db import Database, UserPrefs
from bot.handlers.core import respond_to_text
from bot.handlers.settings import _parse_fav_edit, fav_panel_text
from bot.rates.service import RateService

WIDE_TABLE = {
    code: Decimal("7.2") for code in
    ("CNY", "USD", "HKD", "EUR", "JPY", "GBP", "KRW", "TWD", "SGD", "AUD",
     "THB", "CAD", "CHF", "NZD", "MYR", "PHP", "VND", "RUB", "INR", "MOP", "IDR")
}
WIDE_TABLE["USD"] = Decimal(1)


@pytest.fixture()
def config(tmp_path):
    return Config(db_path=str(tmp_path / "fav.db"))


@pytest.fixture()
def rates(config):
    service = RateService(config)
    service.inject("stub", WIDE_TABLE)
    return service


@pytest.fixture()
async def db(config):
    database = Database(config)
    await database.connect()
    yield database
    await database.close()


# --- targets_for -------------------------------------------------------------


def test_default_favorites_are_ten(config):
    assert len(config.default_favorites) == 10
    assert config.multi_target_count == 10


def test_targets_for_returns_requested_count():
    prefs = UserPrefs(user_id=1, base="CNY", favorites=["USD", "EUR", "JPY"])
    targets = prefs.targets_for("CNY", limit=10)
    assert len(targets) == 10
    assert targets[:3] == ["USD", "EUR", "JPY"]  # 常用的排前面
    assert "CNY" not in targets  # 源币种被排除


def test_targets_for_puts_home_currency_first():
    prefs = UserPrefs(user_id=1, base="CNY", favorites=["USD", "EUR"])
    assert prefs.targets_for("JPY", limit=10)[0] == "CNY"


def test_targets_for_never_duplicates():
    prefs = UserPrefs(user_id=1, base="USD", favorites=["USD", "USD", "EUR"])
    targets = prefs.targets_for("CNY", limit=12)
    assert len(targets) == len(set(targets))


def test_targets_for_works_with_empty_favorites():
    prefs = UserPrefs(user_id=1, base="CNY", favorites=[])
    targets = prefs.targets_for("CNY", limit=10)
    assert len(targets) == 10
    assert all(cur_mod.is_known(code) for code in targets)


# --- 端到端：只发一个金额 ------------------------------------------------------


async def test_amount_with_currency_lists_ten(db, rates, config):
    prefs = await db.get_prefs(1)
    rendered = await respond_to_text(
        "100rmb", prefs, rates, db, target_count=config.multi_target_count
    )
    assert rendered.ok
    rows = [line for line in rendered.text.split("\n") if "<code>" in line]
    assert len(rows) == 10


async def test_bare_amount_lists_ten(db, rates, config):
    prefs = await db.get_prefs(1)
    rendered = await respond_to_text(
        "100", prefs, rates, db, target_count=config.multi_target_count
    )
    rows = [line for line in rendered.text.split("\n") if "<code>" in line]
    assert len(rows) == 10


async def test_explicit_targets_still_win(db, rates, config):
    prefs = await db.get_prefs(1)
    rendered = await respond_to_text(
        "100 cny jpy", prefs, rates, db, target_count=config.multi_target_count
    )
    # 写明了目标就只换那一个，不铺开
    assert "= " in rendered.text
    assert rendered.single is not None and rendered.single.quote == "JPY"


# --- 常用列表增删 -------------------------------------------------------------


def test_parse_fav_edit_replace():
    add, remove, incremental = _parse_fav_edit("usd jpy eur")
    assert add == ["USD", "JPY", "EUR"] and remove == [] and incremental is False


def test_parse_fav_edit_incremental():
    add, remove, incremental = _parse_fav_edit("+韩元 -英镑 泰铢")
    assert add == ["KRW", "THB"] and remove == ["GBP"] and incremental is True


def test_parse_fav_edit_default_sign():
    add, remove, incremental = _parse_fav_edit("krw thb", default_sign="+")
    assert add == ["KRW", "THB"] and incremental is True

    add, remove, incremental = _parse_fav_edit("gbp", default_sign="-")
    assert remove == ["GBP"] and add == [] and incremental is True


def test_parse_fav_edit_ignores_junk():
    add, remove, _ = _parse_fav_edit("usd, 不存在的币, jpy")
    assert add == ["USD", "JPY"] and remove == []


def test_parse_fav_edit_handles_fullwidth_signs():
    add, remove, incremental = _parse_fav_edit("＋KRW －GBP")
    assert add == ["KRW"] and remove == ["GBP"] and incremental is True


async def test_favorites_survive_a_round_trip(db):
    await db.update_prefs(1, favorites=["KRW", "THB", "USD"])
    db._cache.clear()
    assert (await db.get_prefs(1)).favorites == ["KRW", "THB", "USD"]


# --- 选择面板 -----------------------------------------------------------------


def test_fav_picker_pages_cover_the_whole_pool():
    prefs = UserPrefs(user_id=1, base="CNY", favorites=["USD"])
    pool = kb.fav_pool(prefs)
    pages = max(1, -(-len(pool) // kb.FAV_PAGE_SIZE))
    seen: set[str] = set()
    for page in range(pages):
        for row in kb.fav_picker_keyboard(prefs, page).inline_keyboard:
            for button in row:
                action, parts = kb.unpack(button.callback_data or "")
                if len(parts) > 1 and parts[0] == "favtog":
                    seen.add(parts[1])
    assert seen == set(pool)


def test_fav_picker_marks_selected():
    prefs = UserPrefs(user_id=1, base="CNY", favorites=["USD"])
    texts = [b.text for row in kb.fav_picker_keyboard(prefs, 0).inline_keyboard for b in row]
    assert any(text.startswith("✅") and "USD" in text for text in texts)
    assert any(text.startswith("▫️") for text in texts)


def test_fav_picker_clamps_out_of_range_pages():
    prefs = UserPrefs(user_id=1, base="CNY", favorites=["USD"])
    assert kb.fav_picker_keyboard(prefs, 999).inline_keyboard
    assert kb.fav_picker_keyboard(prefs, -5).inline_keyboard


def test_all_callback_data_fits_telegram_limit():
    prefs = UserPrefs(user_id=1, base="CNY", favorites=list(cur_mod.PICKER_POOL[:20]))
    markups = [kb.fav_picker_keyboard(prefs, page) for page in range(5)]
    markups.append(kb.multi_keyboard("CNY", Decimal("123456.78"), prefs, quotes=list(cur_mod.FILLER)))
    for markup in markups:
        for row in markup.inline_keyboard:
            for button in row:
                assert button.callback_data
                assert len(button.callback_data.encode()) <= 64, button.callback_data


def test_fav_panel_text_shows_count(config):
    prefs = UserPrefs(user_id=1, base="CNY", favorites=["USD", "JPY"])
    text = fav_panel_text(prefs, config)
    assert "2/20" in text
    assert "USD" in text and "JPY" in text


def test_multi_keyboard_has_edit_and_refresh():
    prefs = UserPrefs(user_id=1, base="CNY", favorites=["USD", "JPY"])
    markup = kb.multi_keyboard("CNY", Decimal(100), prefs, quotes=["USD", "JPY"])
    actions = {
        kb.unpack(b.callback_data or "")[0]
        for row in markup.inline_keyboard
        for b in row
    }
    assert {"mref", "st", "close", "cv"} <= actions
