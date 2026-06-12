"""测试公共脚手架。"""
from __future__ import annotations

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from steel_platform.gateway import PermissionGateway
from steel_platform.matching import MatchingEngine
from steel_platform.ownership import OwnershipEngine
from steel_platform.store import Store
from steel_platform.triggers import TriggerEngine

NOW = datetime(2026, 6, 12)


def build():
    store = Store()
    own = OwnershipEngine(store)
    gw = PermissionGateway(store)
    match = MatchingEngine(store, own, gw)
    trig = TriggerEngine(store, own)
    return store, own, gw, match, trig
