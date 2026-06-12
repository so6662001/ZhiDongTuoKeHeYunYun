"""智能锁价引擎（对应 docs/05 第 3 节）。

钢价高频波动，锁价在波动期为买方锁定价格一定时长，降低决策犹豫、加速成交；
收取小额保证金防恶意占价，并对平台锁价敞口做限额控制。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional


class LockStatus(str, Enum):
    ACTIVE = "active"
    EXERCISED = "exercised"   # 已在锁价内下单
    EXPIRED = "expired"       # 到期未下单，价格释放
    CANCELLED = "cancelled"


# 可选锁价时长（小时）→ 行情越波动，可选时长越短（由上层按波动率裁剪）
ALLOWED_DURATIONS_H = (2, 6, 24)

# 保证金费率（按货值），可配置
MARGIN_RATE = 0.01


@dataclass
class PriceLock:
    lock_id: int
    buyer_enterprise_id: int
    listing_id: int
    locked_price: float
    quantity: float
    created_at: datetime
    expires_at: datetime
    margin: float
    status: LockStatus = LockStatus.ACTIVE


@dataclass
class LockResult:
    ok: bool
    lock: Optional[PriceLock] = None
    reason: str = ""


class PriceLockEngine:
    def __init__(self, exposure_limit_tons: float = 5000.0) -> None:
        self.locks: dict[int, PriceLock] = {}
        self.exposure_limit_tons = exposure_limit_tons
        self._seq = 0

    def _next_id(self) -> int:
        self._seq += 1
        return self._seq

    def current_exposure(self, now: datetime) -> float:
        return sum(
            l.quantity
            for l in self.locks.values()
            if l.status == LockStatus.ACTIVE and l.expires_at > now
        )

    def quote_margin(self, price: float, quantity: float) -> float:
        return round(price * quantity * MARGIN_RATE, 2)

    def create_lock(
        self,
        buyer_enterprise_id: int,
        listing_id: int,
        price: float,
        quantity: float,
        duration_hours: int,
        now: datetime,
        volatility: float = 0.0,
    ) -> LockResult:
        """创建锁价。剧烈行情(volatility 高)只允许较短时长；超敞口限额拒绝。"""
        allowed = self._allowed_durations(volatility)
        if duration_hours not in allowed:
            return LockResult(False, reason=f"当前行情仅允许锁价时长 {allowed} 小时")
        if self.current_exposure(now) + quantity > self.exposure_limit_tons:
            return LockResult(False, reason="平台锁价敞口已达限额，暂不可锁价")
        lock = PriceLock(
            lock_id=self._next_id(),
            buyer_enterprise_id=buyer_enterprise_id,
            listing_id=listing_id,
            locked_price=price,
            quantity=quantity,
            created_at=now,
            expires_at=now + timedelta(hours=duration_hours),
            margin=self.quote_margin(price, quantity),
        )
        self.locks[lock.lock_id] = lock
        return LockResult(True, lock=lock)

    @staticmethod
    def _allowed_durations(volatility: float) -> tuple[int, ...]:
        if volatility >= 0.05:      # 剧烈波动 -> 只允许 2 小时
            return (2,)
        if volatility >= 0.02:      # 中等波动 -> 最长 6 小时
            return (2, 6)
        return ALLOWED_DURATIONS_H

    def exercise(self, lock_id: int, now: datetime) -> LockResult:
        """在锁价有效期内下单 -> 锁价生效成交。"""
        lock = self.locks.get(lock_id)
        if lock is None:
            return LockResult(False, reason="锁价不存在")
        if lock.status != LockStatus.ACTIVE:
            return LockResult(False, reason=f"锁价状态为 {lock.status.value}")
        if now > lock.expires_at:
            lock.status = LockStatus.EXPIRED
            return LockResult(False, lock=lock, reason="锁价已过期")
        lock.status = LockStatus.EXERCISED
        return LockResult(True, lock=lock)

    def expire_due(self, now: datetime) -> list[PriceLock]:
        """定时释放到期未行权的锁价（保证金按规则处理）。"""
        expired = []
        for lock in self.locks.values():
            if lock.status == LockStatus.ACTIVE and now > lock.expires_at:
                lock.status = LockStatus.EXPIRED
                expired.append(lock)
        return expired
