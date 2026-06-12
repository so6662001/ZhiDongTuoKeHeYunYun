# 钢铁现货平台核心引擎 · 参考实现（原型）

把 `docs/` 的详细设计落成**可运行的 Python 原型**，用最小代价验证关键逻辑，尤其是"撮合绝不命中私域客户"这条防撬客铁律。纯标准库实现，无需安装依赖。

## 目录结构

```
prototype/
├── steel_platform/
│   ├── models.py          # 领域模型与枚举（docs/01）
│   ├── store.py           # 内存仓储（生产替换为 sql/schema.sql 的数据库）
│   ├── ownership.py       # 归属引擎：保护期/续期/状态机/撞单仲裁（docs/02）
│   ├── gateway.py         # 权限/归属网关：可见性过滤+审计（docs/06）
│   ├── matching.py        # 公域撮合评分引擎（docs/03）
│   ├── matching_utils.py  # 规格兼容/区域邻近度
│   ├── ranking.py         # LTR 排序模型 + 反馈闭环（docs/03 模型化升级）
│   ├── credit.py          # 信用评分与账期推荐（docs/05）
│   ├── pricelock.py       # 智能锁价引擎（docs/05）
│   ├── recovery.py        # 弃单挽回引擎（docs/05）
│   └── triggers.py        # 触发器引擎：补货/价格异动（docs/04）
├── api/                   # FastAPI REST 接口层
│   ├── app.py             # 应用与路由（含 /docs Swagger）
│   └── schemas.py         # Pydantic 请求/响应模型
├── tests/                 # unittest 单元测试（41 个）
├── requirements.txt       # API 层依赖（核心引擎零依赖）
└── demo.py                # 端到端演示脚本
```

## 运行

```bash
# 端到端演示（5 个场景，含防撬客断言）
python3 prototype/demo.py

# 单元测试（41 个，纯标准库 + API 层）
cd prototype && python3 -m unittest discover -s tests -p "test_*.py"

# 启动 REST API（需先 pip install -r requirements.txt）
cd prototype && uvicorn api.app:app --reload
# 浏览器打开 http://127.0.0.1:8000/docs 查看交互式 API 文档
```

## 模块对应方向

- 方向1 REST API：`api/`（FastAPI + OpenAPI 文档）。
- 方向2 撮合模型化：`ranking.py`（逻辑回归 LTR + 反馈闭环），`matching.py` 训练后自动切换模型分。
- 方向3 锁价与弃单挽回：`pricelock.py`、`recovery.py`。
- 方向4 产品原型：见 `docs/08-产品原型与界面设计.md` 与 `docs/mockups/`。

## 演示覆盖的关键结论

1. **防撬客（撮合层）**：B 上架货源做撮合时，A 的战略客户 C1 永不出现在结果里；公域散客 C2 正常被撮合。
2. **防撬客（网关层）**：B 访问 A 的战略客户被拒绝并记审计；A 访问自己客户被允许。
3. **信用与账期**：A 级客户给账期、D 级客户要求全额预付。
4. **智能补货提醒**：仅对商家自己的归属客户触发（scope=owner_only）。
5. **撞单仲裁**：同一客户被多家争夺时，按"成交关系 > 询价关系"判定归属。

## 与生产实现的关系

- 内存 `store` 仅为演示；生产用 `sql/schema.sql` 的表结构，并把数据访问统一收口到 `gateway`（权限/归属网关是防撬客的物理闸门）。
- 评分权重、保护期天数、信用阈值均为可配置参数，便于运营按行业反馈调参。
- AI 模型（撮合 LTR、信用 GBDT、复购预测）在原型里以规则近似，对应 docs 的"先规则后模型"路线。
