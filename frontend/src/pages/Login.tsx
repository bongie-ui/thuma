import { useState, type FormEvent } from "react";
import { api } from "../api";
import { ErrorNote } from "../components/ui";
import { useAction, useApi, useSession } from "../hooks";
import type { Me } from "../types";

const COUNTRY: Record<string, string> = { ZA: "South Africa", US: "United States", GB: "United Kingdom", ZW: "Zimbabwe" };

export default function Login() {
  const { session, refresh } = useSession();
  const demo = useApi<Me[]>(session.demo_mode ? "/auth/demo-users/" : null);
  const { busy, error, run } = useAction();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  const asPersona = (u: string) => run(async () => {
    await api.post("/auth/demo-login/", { username: u });
    await refresh();
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => {
      await api.post("/auth/login/", { username, password });
      await refresh();
    });
  };

  return (
    <main className="login">
      <div className="row" style={{ marginBottom: "1rem" }}>
        <img src="/favicon.svg" alt="" width={40} height={40} />
        <div>
          <h1 style={{ margin: 0 }}>Thuma</h1>
          <div className="muted small">Money for family at home, spent the way you agreed.</div>
        </div>
      </div>

      {session.demo_mode && (
        <div className="card">
          <h2>Try the demo</h2>
          <p className="muted small">Pick a family member. Each one funds mandates from a different country.</p>
          {demo.loading && <p className="muted">Loading people…</p>}
          {demo.data?.length === 0 && <p className="notice info">No demo family yet. Run <code>python manage.py seed_demo</code>.</p>}
          {demo.data?.map((u) => (
            <button key={u.username} className="persona" disabled={busy} onClick={() => asPersona(u.username)}>
              <span>
                <strong>{u.name}</strong>
                <span className="muted small"> · {u.family?.name}</span>
              </span>
              <span className="muted small">{COUNTRY[u.country] ?? u.country}</span>
            </button>
          ))}
        </div>
      )}

      <form className="card" onSubmit={submit}>
        <h2>{session.demo_mode ? "Or log in" : "Log in"}</h2>
        <div className="field">
          <label htmlFor="u">Username</label>
          <input id="u" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="p">Password</label>
          <input id="p" type="password" autoComplete="current-password" value={password}
            onChange={(e) => setPassword(e.target.value)} />
        </div>
        <div className="field">
          <button className="primary" disabled={busy || !username || !password}>Log in</button>
        </div>
      </form>
      <ErrorNote error={error} />
    </main>
  );
}
