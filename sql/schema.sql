-- 货袋子钢铁现货平台 · 数据底座建表脚本
-- 对应 docs/01-数据底座详细设计.md 与 docs/02-私域公域与归属机制详细设计.md
-- 方言以 SQLite 为基线（便于原型演示），生产可平移到 MySQL/PostgreSQL。

PRAGMA foreign_keys = ON;

-- 企业（产业链任一主体：生产/批发/贸易/门零/终端）
CREATE TABLE IF NOT EXISTS enterprise (
    enterprise_id   INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    ent_type        TEXT NOT NULL CHECK (ent_type IN ('producer','wholesaler','trader','retailer','end_user')),
    scale           TEXT CHECK (scale IN ('large','medium','small','micro')),
    region_code     TEXT,
    main_categories TEXT,            -- JSON 数组：螺纹/线材/热卷/中厚板/型钢...
    qualification   TEXT,            -- JSON：营业执照/纳税人类型等
    credit_score    INTEGER DEFAULT 60,
    created_at      TEXT NOT NULL,
    updated_at      TEXT
);

-- 商家（平台付费经营者，客户的拥有方）
CREATE TABLE IF NOT EXISTS merchant (
    merchant_id     INTEGER PRIMARY KEY,
    enterprise_id   INTEGER NOT NULL REFERENCES enterprise(enterprise_id),
    tier            TEXT DEFAULT 'standard',
    created_at      TEXT NOT NULL
);

-- 联系人（电话脱敏托管，真实号码存独立保险库）
CREATE TABLE IF NOT EXISTS contact (
    contact_id          INTEGER PRIMARY KEY,
    enterprise_id       INTEGER NOT NULL REFERENCES enterprise(enterprise_id),
    name                TEXT,
    role                TEXT CHECK (role IN ('boss','purchaser','sales','finance','warehouse')),
    phone_token         TEXT,        -- 虚拟号映射 ID，非真实号码
    wechat_bound        INTEGER DEFAULT 0,
    is_decision_maker   INTEGER DEFAULT 0
);

-- 行为事件流（高频写入，画像与标签的源数据）
CREATE TABLE IF NOT EXISTS event (
    event_id        INTEGER PRIMARY KEY,
    enterprise_id   INTEGER NOT NULL REFERENCES enterprise(enterprise_id),
    contact_id      INTEGER REFERENCES contact(contact_id),
    event_type      TEXT NOT NULL CHECK (event_type IN
                      ('view','search','inquiry','quote','visit','order','abandon','chat','share')),
    category        TEXT,
    spec            TEXT,
    quantity        REAL,
    price           REAL,
    direction       TEXT CHECK (direction IN ('buy','sell')),
    region_code     TEXT,
    keywords        TEXT,            -- JSON 数组
    occurred_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_event_ent ON event(enterprise_id, occurred_at);

-- 货源（卖方挂货）
CREATE TABLE IF NOT EXISTS listing (
    listing_id          INTEGER PRIMARY KEY,
    merchant_id         INTEGER NOT NULL REFERENCES merchant(merchant_id),
    category            TEXT NOT NULL,
    spec                TEXT NOT NULL,
    quantity            REAL NOT NULL,
    price               REAL,
    price_type          TEXT CHECK (price_type IN ('fixed','negotiable')),
    warehouse_region    TEXT,
    account_period_days INTEGER DEFAULT 0,
    visibility          TEXT NOT NULL DEFAULT 'public'
                          CHECK (visibility IN ('private','assigned','public')),
    status              TEXT NOT NULL DEFAULT 'on_sale'
                          CHECK (status IN ('on_sale','locked','sold','off_shelf')),
    created_at          TEXT NOT NULL
);

-- 求购意图（买方需求）
CREATE TABLE IF NOT EXISTS demand (
    demand_id       INTEGER PRIMARY KEY,
    enterprise_id   INTEGER NOT NULL REFERENCES enterprise(enterprise_id),
    category        TEXT NOT NULL,
    spec            TEXT NOT NULL,
    quantity        REAL NOT NULL,
    target_price    REAL,
    delivery_region TEXT,
    urgency         TEXT CHECK (urgency IN ('urgent','normal','watching')),
    is_public       INTEGER DEFAULT 0,
    valid_until     TEXT,
    created_at      TEXT NOT NULL
);

-- 客户归属关系（防撬客核心载体）
CREATE TABLE IF NOT EXISTS customer_relation (
    relation_id             INTEGER PRIMARY KEY,
    merchant_id             INTEGER NOT NULL REFERENCES merchant(merchant_id),
    customer_enterprise_id  INTEGER NOT NULL REFERENCES enterprise(enterprise_id),
    relation_type           TEXT NOT NULL CHECK (relation_type IN
                              ('imported','invited','inquired','dealt','claimed')),
    is_strategic            INTEGER NOT NULL DEFAULT 0,
    protect_until           TEXT,
    visibility              TEXT NOT NULL DEFAULT 'private'
                              CHECK (visibility IN ('private','assigned','public')),
    status                  TEXT NOT NULL DEFAULT 'active'
                              CHECK (status IN ('active','expired','returned_to_pool')),
    last_interaction_at     TEXT,        -- 战略客户"经营时钟"，用于反"圈而不耕"降级判断
    strategic_since         TEXT,        -- 设为战略客户的时间
    created_at              TEXT NOT NULL,
    updated_at              TEXT,
    UNIQUE (merchant_id, customer_enterprise_id)
);

-- 商家战略名额配置（反囤积：战略客户是稀缺、需经营维持的有限资源）
CREATE TABLE IF NOT EXISTS strategic_quota (
    merchant_id     INTEGER PRIMARY KEY REFERENCES merchant(merchant_id),
    quota           INTEGER NOT NULL DEFAULT 20,
    updated_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_relation_customer ON customer_relation(customer_enterprise_id);

-- 同一客户全局至多被一家设为战略客户（互斥，先到先得）
CREATE UNIQUE INDEX IF NOT EXISTS uq_strategic_customer
    ON customer_relation(customer_enterprise_id) WHERE is_strategic = 1;

-- 信用档案
CREATE TABLE IF NOT EXISTS credit_profile (
    enterprise_id       INTEGER PRIMARY KEY REFERENCES enterprise(enterprise_id),
    repayment_on_time   REAL,        -- 回款及时率 0-1
    overdue_count       INTEGER DEFAULT 0,
    fulfillment_rate    REAL,        -- 履约率 0-1
    cancel_rate         REAL,        -- 取消率 0-1
    years_in_business   INTEGER,
    score               INTEGER,     -- 0-100
    tier                TEXT CHECK (tier IN ('A','B','C','D')),
    updated_at          TEXT
);

-- 成交记录
CREATE TABLE IF NOT EXISTS deal (
    deal_id             INTEGER PRIMARY KEY,
    buyer_enterprise_id INTEGER NOT NULL REFERENCES enterprise(enterprise_id),
    seller_merchant_id  INTEGER NOT NULL REFERENCES merchant(merchant_id),
    category            TEXT,
    spec                TEXT,
    quantity            REAL,
    price               REAL,
    account_period_days INTEGER,
    repaid              INTEGER DEFAULT 0,
    created_at          TEXT NOT NULL
);

-- 访问审计日志（客户主权可验证）
CREATE TABLE IF NOT EXISTS access_audit (
    audit_id            INTEGER PRIMARY KEY,
    actor_merchant_id   INTEGER,
    target_customer_id  INTEGER,
    action              TEXT CHECK (action IN ('view','contact','distribute','claim','export')),
    channel             TEXT,
    result              TEXT CHECK (result IN ('allowed','denied')),
    reason              TEXT,
    occurred_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_target ON access_audit(target_customer_id, occurred_at);
