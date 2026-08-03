"""把所有子路由汇总成一个根路由。

注册顺序很重要：命令类路由必须排在「自由文本」路由前面。
"""

from __future__ import annotations

from aiogram import Router

from . import alerts, common, convert, inline, market, settings


def build_router() -> Router:
    root = Router(name="root")
    root.include_router(common.router)
    root.include_router(settings.router)
    root.include_router(market.router)
    root.include_router(alerts.router)
    root.include_router(inline.router)
    root.include_router(convert.router)  # 兜底：自由文本换算
    return root


__all__ = ["build_router"]
