import { useCallback, useEffect, useState } from "react";
import DasherPage from "./DasherPage.jsx";
import { api, orderTitle } from "../api.js";

const STATE_LABELS = {
  waiting: "Waiting",
  building: "Building",
  checking: "Checking…",
  needs_fix: "Needs fix",
  ready: "Ready",
  picked_up: "Picked up",
};

export default function OrdersPage({ onBack }) {
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedOrder, setSelectedOrder] = useState(null);
  const [busyId, setBusyId] = useState(null);

  const loadOrders = useCallback(async (signal) => {
    try {
      setError("");
      setOrders(await api.listOrders(signal));
    } catch (err) {
      if (err.name !== "AbortError") setError(err.message || "Unable to load orders.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    loadOrders(controller.signal);
    return () => controller.abort();
  }, [loadOrders]);

  async function openOrder(order) {
    // Only waiting orders get started; anything else reopens as-is (with its verdict).
    setBusyId(order.id);
    try {
      const opened = order.state === "waiting" ? await api.start(order.id) : order;
      setSelectedOrder(opened);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyId(null);
    }
  }

  async function resetDemo() {
    setLoading(true);
    try {
      setOrders(await api.reset());
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  if (selectedOrder) {
    return (
      <DasherPage
        order={selectedOrder}
        onDone={() => {
          setSelectedOrder(null);
          loadOrders();
        }}
      />
    );
  }

  return (
    <main className="page">
      <section className="orders-panel" aria-labelledby="orders-title">
        <header className="orders-header">
          <h1 id="orders-title">Orders</h1>
          <div className="orders-actions">
            <button className="orders-back" type="button" onClick={resetDemo}>
              Reset demo
            </button>
            {onBack && (
              <button className="orders-back" type="button" onClick={onBack}>
                ← Back
              </button>
            )}
          </div>
        </header>

        <div role="status">
          {loading && <p className="orders-message">Loading orders…</p>}
          {error && <p className="orders-message">{error}</p>}
          {!loading && !error && orders.length === 0 && (
            <p className="orders-message">No orders yet.</p>
          )}
        </div>

        {!loading && (
          <ul className="orders-list">
            {orders.map((order) => {
              const title = orderTitle(order);
              const label =
                order.state === "waiting" ? "Start" : order.state === "picked_up" ? "View" : "Open";
              return (
                <li className="order-row" key={order.id}>
                  <div className="order-details">
                    <span className="order-id">
                      #{order.id} · {order.source} · {STATE_LABELS[order.state] || order.state}
                      {order.has_allergy ? " · ⚠ allergy" : ""}
                    </span>
                    <h2 className="order-name">{title}</h2>
                  </div>
                  <button
                    className="order-start"
                    type="button"
                    disabled={busyId === order.id}
                    onClick={() => openOrder(order)}
                    aria-label={`${label} order ${order.id}, ${title}`}
                  >
                    {busyId === order.id ? "…" : label}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </main>
  );
}
