"""运行配置：全部通过环境变量注入，带合理默认值。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _env_str(key: str, default: str) -> str:
    value = os.getenv(key)
    return value if value not in (None, "") else default


def _env_int(key: str, default: int) -> int:
    try:
        return int(_env_str(key, str(default)))
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    try:
        return float(_env_str(key, str(default)))
    except ValueError:
        return default


def _env_bool(key: str, default: bool) -> bool:
    return _env_str(key, "1" if default else "0").strip().lower() in ("1", "true", "yes", "on")


def _env_list(key: str, default: list[str]) -> list[str]:
    raw = _env_str(key, "")
    if not raw:
        return list(default)
    return [item.strip().upper() for item in raw.replace(";", ",").split(",") if item.strip()]


@dataclass(slots=True)
class Config:
    # --- Telegram ---
    bot_token: str = field(default_factory=lambda: _env_str("BOT_TOKEN", ""))
    # 留空则使用长轮询；填写则以 webhook 模式运行
    webhook_base: str = field(default_factory=lambda: _env_str("WEBHOOK_BASE", ""))
    webhook_path: str = field(default_factory=lambda: _env_str("WEBHOOK_PATH", "/tg/webhook"))
    webhook_secret: str = field(default_factory=lambda: _env_str("WEBHOOK_SECRET", ""))
    webapp_host: str = field(default_factory=lambda: _env_str("WEBAPP_HOST", "0.0.0.0"))
    webapp_port: int = field(default_factory=lambda: _env_int("WEBAPP_PORT", 8080))
    admin_ids: list[int] = field(
        default_factory=lambda: [
            int(x) for x in _env_str("ADMIN_IDS", "").replace(";", ",").split(",") if x.strip().isdigit()
        ]
    )

    # --- 存储 ---
    db_path: str = field(default_factory=lambda: _env_str("DB_PATH", str(BASE_DIR / "data" / "bot.db")))

    # --- 汇率刷新 ---
    fiat_refresh_seconds: int = field(default_factory=lambda: _env_int("FIAT_REFRESH_SECONDS", 60))
    crypto_refresh_seconds: int = field(default_factory=lambda: _env_int("CRYPTO_REFRESH_SECONDS", 15))
    # 缓存超过该时长仍拿不到新数据时，回复中标记为「陈旧」
    stale_after_seconds: int = field(default_factory=lambda: _env_int("STALE_AFTER_SECONDS", 900))
    http_timeout: float = field(default_factory=lambda: _env_float("HTTP_TIMEOUT", 8.0))
    # 单条消息内 /rate、换算等对同一用户的最小间隔（秒），防刷
    rate_limit_seconds: float = field(default_factory=lambda: _env_float("RATE_LIMIT_SECONDS", 0.4))

    # --- 提醒 / 播报 ---
    alert_check_seconds: int = field(default_factory=lambda: _env_int("ALERT_CHECK_SECONDS", 60))
    max_alerts_per_user: int = field(default_factory=lambda: _env_int("MAX_ALERTS_PER_USER", 30))
    max_subs_per_user: int = field(default_factory=lambda: _env_int("MAX_SUBS_PER_USER", 10))

    # --- 默认用户偏好 ---
    default_base: str = field(default_factory=lambda: _env_str("DEFAULT_BASE", "CNY").upper())
    default_favorites: list[str] = field(
        default_factory=lambda: _env_list("DEFAULT_FAVORITES", ["USD", "EUR", "JPY", "HKD", "GBP"])
    )
    default_lang: str = field(default_factory=lambda: _env_str("DEFAULT_LANG", "zh"))
    default_decimals: int = field(default_factory=lambda: _env_int("DEFAULT_DECIMALS", 2))
    default_tz: str = field(default_factory=lambda: _env_str("DEFAULT_TZ", "Asia/Shanghai"))

    # --- 可选的付费数据源 ---
    exchangerate_api_key: str = field(default_factory=lambda: _env_str("EXCHANGERATE_API_KEY", ""))
    # 逗号分隔，用于禁用某些 provider，例如 "binance,coingecko"
    disabled_providers: list[str] = field(
        default_factory=lambda: [p.lower() for p in _env_list("DISABLED_PROVIDERS", [])]
    )

    log_level: str = field(default_factory=lambda: _env_str("LOG_LEVEL", "INFO").upper())

    def validate(self) -> None:
        if not self.bot_token:
            raise SystemExit(
                "缺少 BOT_TOKEN。请复制 .env.example 为 .env 并填入 @BotFather 给的 token。"
            )
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    @property
    def use_webhook(self) -> bool:
        return bool(self.webhook_base)

    @property
    def webhook_url(self) -> str:
        return self.webhook_base.rstrip("/") + self.webhook_path


config = Config()
