export default function LoginPage({ onLogin }) {
  function handleSubmit(event) {
    event.preventDefault();

    const username = event.currentTarget.elements.username.value.trim();

    if (username) {
      onLogin(username);
    }
  }

  return (
    <main className="page">
      <section className="login-card">
        <h1>Welcome.</h1>

        <form onSubmit={handleSubmit}>
          <label htmlFor="username">Username</label>
          <input
            id="username"
            name="username"
            type="text"
            placeholder="Username (resturant or dasher)"
            autoComplete="username"
            required
          />

          <label htmlFor="password">Password</label>
          <input
            id="password"
            name="password"
            type="password"
            placeholder="Any password"
            autoComplete="current-password"
            required
          />

          <button className="login-button" type="submit">
            Log in
            <span aria-hidden="true">→</span>
          </button>
        </form>
      </section>
    </main>
  );
}