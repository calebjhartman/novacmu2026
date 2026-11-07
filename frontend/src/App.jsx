import { useState } from "react";
import LoginPage from "./pages/LoginPage.jsx";
import ResturantPage from "./pages/ResturantPage.jsx";
import DasherPage from "./pages/DasherPage.jsx";
import OrdersPage from "./pages//OrdersPage.jsx";

import "./styles.css";

export default function App() {
  const [user, setUser] = useState(null);

  function handleLogin(username) {
    const normalizedUsername = username.trim().toLowerCase();

    setUser({
      username: username.trim(),
      role: "store"
    });
  }

  function handleLogout() {
    setUser(null);
  }

  if (!user) {
    return <LoginPage onLogin={handleLogin} />;
  }

  if (user.role === "store") {
    return <ResturantPage user={user} onLogout={handleLogout} />;
  }

  return <DasherPage user={user} onLogout={handleLogout} />;
}