"""老版本建的库启动后必须能继续用：缺的列自动补上。"""

import sqlite3

import pytest

from bot.config import Config
from bot.db import MIGRATIONS, SCHEMA, Database

# v1 的 users 表：没有 show_names
OLD_USERS_SCHEMA = """
CREATE TABLE users (
    user_id      INTEGER PRIMARY KEY,
    lang         TEXT    NOT NULL DEFAULT 'zh',
    base         TEXT    NOT NULL DEFAULT 'CNY',
    favorites    TEXT    NOT NULL DEFAULT 'USD,EUR,JPY,HKD,GBP',
    decimals     INTEGER NOT NULL DEFAULT 2,
    group_sep    INTEGER NOT NULL DEFAULT 1,
    show_source  INTEGER NOT NULL DEFAULT 1,
    show_change  INTEGER NOT NULL DEFAULT 1,
    tz           TEXT    NOT NULL DEFAULT 'Asia/Shanghai',
    fee_percent  TEXT    NOT NULL DEFAULT '',
    created_at   REAL    NOT NULL DEFAULT 0,
    updated_at   REAL    NOT NULL DEFAULT 0
);
"""


@pytest.fixture()
def legacy_db_path(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(OLD_USERS_SCHEMA)
    conn.execute(
        "INSERT INTO users (user_id, lang, base, favorites, decimals) VALUES (?,?,?,?,?)",
        (42, "zh", "JPY", "USD,EUR", 3),
    )
    conn.commit()
    conn.close()
    return path


async def test_old_database_gets_the_new_column(legacy_db_path):
    db = Database(Config(db_path=str(legacy_db_path)))
    await db.connect()
    try:
        async with db.conn.execute("PRAGMA table_info(users)") as cursor:
            columns = {row["name"] for row in await cursor.fetchall()}
        assert "show_names" in columns
    finally:
        await db.close()


async def test_existing_user_settings_survive_migration(legacy_db_path):
    db = Database(Config(db_path=str(legacy_db_path)))
    await db.connect()
    try:
        prefs = await db.get_prefs(42)
        assert prefs.base == "JPY"          # 老数据原封不动
        assert prefs.favorites == ["USD", "EUR"]
        assert prefs.decimals == 3
        assert prefs.show_names is True     # 新列拿到默认值
    finally:
        await db.close()


async def test_migration_is_idempotent(legacy_db_path):
    for _ in range(3):
        db = Database(Config(db_path=str(legacy_db_path)))
        await db.connect()
        await db.close()

    db = Database(Config(db_path=str(legacy_db_path)))
    await db.connect()
    try:
        prefs = await db.update_prefs(42, show_names=False)
        assert prefs.show_names is False
        db._cache.clear()
        assert (await db.get_prefs(42)).show_names is False
    finally:
        await db.close()


async def test_fresh_database_needs_no_migration(tmp_path):
    db = Database(Config(db_path=str(tmp_path / "new.db")))
    await db.connect()
    try:
        async with db.conn.execute("PRAGMA table_info(users)") as cursor:
            columns = {row["name"] for row in await cursor.fetchall()}
        for table, cols in MIGRATIONS.items():
            if table == "users":
                assert set(cols) <= columns
    finally:
        await db.close()


def test_migrations_match_the_schema():
    """MIGRATIONS 里的列必须在 SCHEMA 里也有，否则新库和老库会长得不一样。"""
    for table, columns in MIGRATIONS.items():
        assert f"CREATE TABLE IF NOT EXISTS {table}" in SCHEMA
        for column in columns:
            assert column in SCHEMA, f"{table}.{column} 只在 MIGRATIONS 里，SCHEMA 漏了"
