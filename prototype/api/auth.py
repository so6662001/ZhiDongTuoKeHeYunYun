"""API 鉴权与多租户上下文（方向1 增强）。

每个请求携带 Bearer 令牌，解析出当前商家身份（MerchantContext）。
后续涉及客户数据的操作一律以"已鉴权商家"作为 actor，杜绝伪造他人身份冲抢客户。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Header, HTTPException


@dataclass
class MerchantContext:
    merchant_id: int
    tier: str = "standard"


class TokenRegistry:
    """演示用令牌表（生产替换为鉴权中心/JWT 校验）。"""

    def __init__(self) -> None:
        self._token_to_merchant: dict[str, MerchantContext] = {}

    def issue(self, merchant_id: int, token: str, tier: str = "standard") -> None:
        self._token_to_merchant[token] = MerchantContext(merchant_id, tier)

    def resolve(self, token: str) -> Optional[MerchantContext]:
        return self._token_to_merchant.get(token)


def parse_bearer(authorization: Optional[str]) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="缺少或非法的 Authorization 头")
    return authorization.split(" ", 1)[1].strip()


def make_auth_dependency(registry: TokenRegistry):
    """生成 FastAPI 依赖：从 Authorization 头解析出 MerchantContext。"""

    def _dep(authorization: Optional[str] = Header(default=None)) -> MerchantContext:
        token = parse_bearer(authorization)
        ctx = registry.resolve(token)
        if ctx is None:
            raise HTTPException(status_code=401, detail="令牌无效")
        return ctx

    return _dep
