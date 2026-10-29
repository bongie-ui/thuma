import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { Loading } from "./components/ui";
import { SessionContext, useApi, usePoll, useSession } from "./hooks";
import Chat from "./pages/Chat";
import Home from "./pages/Home";
import Inbox from "./pages/Inbox";
import Login from "./pages/Login";
import MandateDetail from "./pages/MandateDetail";
import NewMandate from "./pages/NewMandate";
import People from "./pages/People";
import RequestDetail from "./pages/RequestDetail";
import { match, usePath } from "./router";
import type { PayRequest, Session } from "./types";

export default function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setSession(await api.get<Session>("/auth/me/"));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  if (!session) {
    return <main>{error ? <div className="notice error">{error} <button onClick={refresh}>Retry</button></div> : <Loading />}</main>;
  }
  return (
    <SessionContext.Provider value={{ session, refresh }}>
      {session.authenticated ? <Shell /> : <Login />}
    </SessionContext.Provider>
  );
}

function Shell() {
  const path = usePath();
  const inbox = useApi<PayRequest[]>("/requests/?inbox=1");
  usePoll(inbox.reload, 15000, true);
  useEffect(() => {
    void inbox.reload();
    // Refresh the inbox count whenever the page changes (an approval may have cleared it).
  }, [path]); // eslint-disable-line react-hooks/exhaustive-deps

  const section = path.split("/")[1] || "home";
  const tab = (href: string, label: string, key: string, count?: number) => (
    <a href={`#${href}`} className={section === key || (key === "home" && section === "mandates") ? "active" : ""}>
      {label}
      {count ? <span className="count">{count}</span> : null}
    </a>
  );

  return (
    <div className="app">
      <header className="topbar">
        <a className="logo" href="#/"><img src="/favicon.svg" alt="" />Thuma</a>
        <nav className="nav" aria-label="Main">
          {tab("/", "Mandates", "home")}
          {tab("/inbox", "Approvals", "inbox", inbox.data?.length)}
          {tab("/chat", "Chat", "chat")}
          {tab("/people", "People", "people")}
        </nav>
        <Who />
      </header>
      <main>
        <Route path={path} />
      </main>
    </div>
  );
}

function Route({ path }: { path: string }) {
  let m;
  if (path === "/" || path === "") return <Home />;
  if (path === "/mandates/new") return <NewMandate />;
  if ((m = match("/mandates/:id", path))) return <MandateDetail id={m.id} />;
  if ((m = match("/requests/:id", path))) return <RequestDetail id={m.id} />;
  if (path.startsWith("/inbox")) return <Inbox />;
  if (path.startsWith("/chat")) return <Chat path={path} />;
  if (path.startsWith("/people")) return <People />;
  return <div className="card empty">Page not found. <a href="#/">Go to your mandates</a></div>;
}

function Who() {
  const { session, refresh } = useSession();
  const user = session.user!;
  const logout = async () => {
    await api.post("/auth/logout/");
    window.location.hash = "/";
    await refresh();
  };
  return (
    <div className="who">
      <span className="name">{user.name}{user.family ? ` · ${user.family.name}` : ""}</span>
      <button className="small" onClick={logout}>{session.demo_mode ? "Switch person" : "Log out"}</button>
    </div>
  );
}
