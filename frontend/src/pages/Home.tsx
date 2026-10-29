import { money } from "../api";
import { Empty, ErrorNote, FUNDER_COLORS, Loading, RequestRow } from "../components/ui";
import { useApi, useSession } from "../hooks";
import type { Mandate, PayRequest } from "../types";

export default function Home() {
  const { session } = useSession();
  const mandates = useApi<Mandate[]>("/mandates/");
  const recent = useApi<PayRequest[]>("/requests/");

  return (
    <>
      <div className="section-title">
        <div>
          <h1>{session.user?.family?.name ?? "Your family"}</h1>
          <p className="muted" style={{ margin: 0 }}>Mandates: money your family set aside, with rules for how it may be spent.</p>
        </div>
        <a className="btn primary" href="#/mandates/new">New mandate</a>
      </div>

      <ErrorNote error={mandates.error} />
      {mandates.loading && !mandates.data && <Loading what="Loading mandates" />}
      {mandates.data?.length === 0 && (
        <Empty>No mandates yet. <a href="#/mandates/new">Describe what the money is for</a> and the assistant drafts the rules.</Empty>
      )}
      <div className="grid">
        {mandates.data?.map((m) => <MandateCard key={m.id} m={m} />)}
      </div>

      <div className="section">
        <h2>Recent requests</h2>
        <ErrorNote error={recent.error} />
        {recent.data?.length === 0 && <Empty>No requests yet.</Empty>}
        <div className="stack">
          {recent.data?.slice(0, 6).map((r) => <RequestRow key={r.id} r={r} />)}
        </div>
      </div>
    </>
  );
}

export function ContributionBar({ m }: { m: Mandate }) {
  const total = Number(m.funded) || 1;
  return (
    <>
      <div className="bar" aria-hidden>
        {m.funders.map((f, i) => (
          <span key={f.user_id} style={{ width: `${(Number(f.contributed) / total) * 100}%`, background: FUNDER_COLORS[i % FUNDER_COLORS.length] }} />
        ))}
      </div>
      <ul className="funders">
        {m.funders.map((f, i) => (
          <li key={f.user_id}>
            <span><span className="dot" style={{ background: FUNDER_COLORS[i % FUNDER_COLORS.length] }} />{f.name}{f.role === "OWNER" ? " (owner)" : ""}</span>
            <span>{money(f.contributed, m.currency)}</span>
          </li>
        ))}
      </ul>
    </>
  );
}

function MandateCard({ m }: { m: Mandate }) {
  return (
    <a className="card card-link" href={`#/mandates/${m.id}`}>
      <div className="row between">
        <span className="mandate-type">{m.type_label}</span>
        {m.pending > 0 && <span className="badge warn">{m.pending} waiting</span>}
        {m.status !== "ACTIVE" && <span className="badge">{m.status.toLowerCase()}</span>}
      </div>
      <h3 style={{ marginTop: "0.3rem" }}>{m.title}</h3>
      <div className="row between" style={{ margin: "0.4rem 0" }}>
        <div>
          <div className="big">{money(m.balance, m.currency)}</div>
          <div className="small muted">available of {money(m.funded, m.currency)} funded</div>
        </div>
        {!m.signature_valid && <span className="badge bad">Signature broken</span>}
      </div>
      <ContributionBar m={m} />
    </a>
  );
}
