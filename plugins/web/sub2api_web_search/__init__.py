from __future__ import annotations

from .provider import Sub2APIWebSearchProvider


def register(ctx) -> None:
    ctx.register_web_search_provider(Sub2APIWebSearchProvider())
