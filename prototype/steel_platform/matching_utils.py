"""撮合辅助：规格兼容与区域邻近度（对应 docs/03）。"""
from __future__ import annotations

# 规格替代表（示意）：键规格可替代值规格集合
SPEC_SUBSTITUTION: dict[str, set[str]] = {
    "HRB400E Φ20": {"HRB400E Φ20"},
}

# 区域邻近度示意矩阵（相邻区域物流成本低 -> 邻近度高）
REGION_ADJACENCY: dict[tuple[str, str], float] = {
    ("华北", "华北"): 1.0,
    ("华北", "华东"): 0.6,
    ("华东", "华东"): 1.0,
    ("华东", "华北"): 0.6,
    ("华北", "华中"): 0.7,
    ("华中", "华北"): 0.7,
}


def spec_compatible(d_cat: str, d_spec: str, l_cat: str, l_spec: str) -> bool:
    if d_cat != l_cat:
        return False
    if d_spec == l_spec:
        return True
    subs = SPEC_SUBSTITUTION.get(l_spec, set())
    return d_spec in subs


def region_proximity(a: str, b: str) -> float:
    if a == b:
        return 1.0
    return REGION_ADJACENCY.get((a, b), 0.3)
