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
│   ├── triggers.py        # 触发器引擎：补货/价格异动（docs/04）
│   └── persistence.py     # SQLite 持久化（基于 sql/schema.sql，docs/01）
├── api/                   # FastAPI REST 接口层
│   ├── app.py             # 应用与路由（鉴权/多租户/持久化/静态前端）
│   ├── auth.py            # Bearer 令牌鉴权 + 多租户上下文
│   └── schemas.py         # Pydantic 请求/响应模型
├── frontend/              # Vue 3 (CDN) 可交互前端，由 /ui 提供
│   ├── index.html         # 载入演示数据 + 身份切换
│   ├── dashboard.html     # 客户主权看板
│   ├── matching.html      # 智能撮合
│   ├── pricelock.html     # 智能锁价
│   ├── app.js / styles.css
├── tests/                 # unittest 单元测试（50 个）
├── requirements.txt       # API/前端依赖（核心引擎零依赖）
└── demo.py                # 端到端演示脚本
```

## 运行

```bash
# 端到端演示（5 个场景，含防撬客断言）
python3 prototype/demo.py

# 单元测试（50 个，纯标准库 + API + 持久化）
cd prototype && python3 -m unittest discover -s tests -p "test_*.py"

# 启动 REST API + 前端（需先 pip install -r requirements.txt）
cd prototype && uvicorn api.app:app --reload
#   API 文档:  http://127.0.0.1:8000/docs
#   可交互前端: http://127.0.0.1:8000/ui/index.html
#   开启持久化: STEEL_DB=./steel.db uvicorn api.app:app
```

## 使用前端

1. 启动服务后打开 `http://127.0.0.1:8000/ui/index.html`。
2. 点击「一键载入演示数据并登录」（创建商家 A/B、客户 C1 战略/C2 公域、货源与需求）。
3. 进入各页面体验：
   - **客户主权看板**：用商家 102 登录查询客户 11，可见"拒绝(owned_by_other)"——防撬客可视化。
   - **智能撮合**：商家 102 撮合货源 2001，结果只含公域 C2(#12)，战略客户 C1(#11) 永不出现。
   - **智能锁价**：选时长锁价、查看保证金、行权成交。

## 模块对应方向

- REST API（鉴权/多租户）：`api/`（FastAPI + OpenAPI + Bearer 令牌，actor=已鉴权商家，防伪造冲抢）。
- 撮合模型化：`ranking.py`（逻辑回归 LTR + 反馈闭环），`matching.py` 训练后自动切换模型分。
- 锁价与弃单挽回：`pricelock.py`、`recovery.py`。
- 真实持久化：`persistence.py` 基于 `sql/schema.sql` 的 SQLite 存储（init/save/load）。
- 可交互前端：`frontend/`（Vue 3 CDN）。
- 产品原型图：见 `docs/08-产品原型与界面设计.md` 与 `docs/mockups/`。

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
