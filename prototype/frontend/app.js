// 简单的前端 API 客户端与共享状态（Vue 3 CDN，无构建步骤）。
const API = (location.origin && location.origin.startsWith("http")) ? location.origin : "http://127.0.0.1:8000";

const Session = {
  get token() { return localStorage.getItem("steel_token") || ""; },
  set token(v) { localStorage.setItem("steel_token", v); },
  get merchant() { return localStorage.getItem("steel_merchant") || ""; },
  set merchant(v) { localStorage.setItem("steel_merchant", v); },
};

async function api(path, { method = "GET", body, auth = true } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (auth && Session.token) headers["Authorization"] = "Bearer " + Session.token;
  const res = await fetch(API + path, {
    method, headers, body: body ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch (e) { data = null; }
  if (!res.ok) throw { status: res.status, detail: (data && data.detail) || res.statusText };
  return data;
}

// 一键载入演示数据：商家 A(101)/B(102)、客户 C1(战略)/C2(公域)、货源、需求
async function seedDemo() {
  const a = await api("/merchants", { method: "POST", auth: false,
    body: { merchant_id: 101, enterprise_id: 1 } });
  const b = await api("/merchants", { method: "POST", auth: false,
    body: { merchant_id: 102, enterprise_id: 2 } });
  await api("/enterprises", { method: "POST", auth: false, body: {
    enterprise_id: 11, name: "高价值终端 C1", ent_type: "end_user",
    region_code: "华北", main_categories: ["螺纹"] } });
  await api("/enterprises", { method: "POST", auth: false, body: {
    enterprise_id: 12, name: "公域散客 C2", ent_type: "retailer",
    region_code: "华北", main_categories: ["螺纹"] } });
  const ha = { "Authorization": "Bearer " + a.token, "Content-Type": "application/json" };
  const hb = { "Authorization": "Bearer " + b.token, "Content-Type": "application/json" };
  await fetch(API + "/relations", { method: "POST", headers: ha,
    body: JSON.stringify({ customer_enterprise_id: 11, relation_type: "dealt" }) });
  await fetch(API + "/relations/strategic", { method: "POST", headers: ha,
    body: JSON.stringify({ customer_enterprise_id: 11 }) });
  await fetch(API + "/relations", { method: "POST", headers: hb,
    body: JSON.stringify({ customer_enterprise_id: 12, relation_type: "inquired" }) });
  await api("/demands", { method: "POST", auth: false, body: {
    demand_id: 1001, enterprise_id: 11, category: "螺纹", spec: "HRB400E Φ20",
    quantity: 200, delivery_region: "华北", target_price: 3850, urgency: "urgent" } });
  await api("/demands", { method: "POST", auth: false, body: {
    demand_id: 1002, enterprise_id: 12, category: "螺纹", spec: "HRB400E Φ20",
    quantity: 50, delivery_region: "华北", target_price: 3850, is_public: true } });
  await fetch(API + "/listings", { method: "POST", headers: hb, body: JSON.stringify({
    listing_id: 2001, merchant_id: 102, category: "螺纹", spec: "HRB400E Φ20",
    quantity: 500, price: 3820, warehouse_region: "华北", visibility: "public" }) });
  // B 试图访问 A 的战略客户 C1，制造一条被拒审计
  await fetch(API + "/gateway/access?customer_id=11", { headers: hb });
  await fetch(API + "/gateway/access?customer_id=11", { headers: ha });
  return { a, b };
}

function NavBar(active) {
  const items = [
    ["index.html", "首页"],
    ["dashboard.html", "客户主权看板"],
    ["matching.html", "智能撮合"],
    ["pricelock.html", "智能锁价"],
  ];
  return `<div class="sidebar">
    <div class="brand">货袋子现货平台<small>智能获客 / 运营 / 转化</small></div>
    <div class="nav">${items.map(([h, t]) =>
      `<a href="${h}" class="${active === h ? "active" : ""}">${t}</a>`).join("")}</div>
  </div>`;
}
