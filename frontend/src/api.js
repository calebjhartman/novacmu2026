// Thin client for the Flask backend (see backend/app.py for the routes).
// In dev, Vite proxies /api to http://127.0.0.1:5000.

const BASE = import.meta.env.VITE_API_BASE || "/api";

async function request(path, { method = "GET", body, signal } = {}) {
  const res = await fetch(`${BASE}${path}`, {
    method,
    signal,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try {
    data = await res.json();
  } catch {
    // non-JSON (e.g. proxy error page when the backend is down)
  }
  if (!res.ok) {
    const msg = data?.error || `Backend error ${res.status}${res.status >= 500 ? " — is the backend running?" : ""}`;
    throw new Error(msg);
  }
  return data;
}

export const api = {
  health: (signal) => request("/health", { signal }),
  listOrders: (signal) => request("/orders", { signal }).then((d) => d.orders),
  start: (id) => request(`/orders/${id}/start`, { method: "POST" }),
  check: (id, frames) =>
    request("/order_check", { method: "POST", body: { order_id: id, frames } }),
  confirm: (id, action, { line_id, item } = {}) =>
    request(`/orders/${id}/confirm`, { method: "POST", body: { action, line_id, item } }),
  pickup: (id) => request(`/orders/${id}/pickup`, { method: "POST" }),
  reset: () => request("/reset", { method: "POST" }).then((d) => d.orders),
};

// Short display name for an order built from its ticket, e.g. "Maya — Chicken bowl".
export function orderTitle(order) {
  const dishes = [...new Set((order.ticket?.assembly || []).map((l) => l.dish))];
  return `${order.customer_first_name}${dishes.length ? " — " + dishes.join(", ") : ""}`;
}
