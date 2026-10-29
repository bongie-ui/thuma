import { money } from "../api";
import FundButton from "../components/FundButton";
import Ledger from "../components/Ledger";
import QuickActions from "../components/QuickActions";
import RequestForm from "../components/RequestForm";
import { Empty, ErrorNote, Loading, RequestRow } from "../components/ui";
import { useApi } from "../hooks";
import type { Beneficiary, Mandate, PayRequest } from "../types";
import { ContributionBar } from "./Home";

export default function MandateDetail({ id }: { id: string }) {
  const mandate = useApi<Mandate>(`/mandates/${id}/`);
  const requests = useApi<PayRequest[]>(`/requests/?mandate=${id}`);
  const beneficiaries = useApi<Beneficiary[]>("/beneficiaries/");
  const m = mandate.data;

  const refresh = () => {
    void mandate.reload();
    void requests.reload();
  };

  if (mandate.error) return <ErrorNote error={mandate.error} />;
  if (!m) return <Loading />;
  const covered = beneficiaries.data?.filter((b) => m.beneficiary_ids.includes(b.id)) ?? [];

  return (
    <>
      <a href="#/" className="small">← Mandates</a>
      <div className="section-title" style={{ marginTop: "0.5rem" }}>
        <div>
          <span className="mandate-type">{m.type_label}</span>
          <h1>{m.title}</h1>
        </div>
        <span className={`badge ${m.status === "ACTIVE" ? "ok" : ""}`}>{m.status.toLowerCase()}</span>
      </div>
      {m.purpose_text && <p className="muted">“{m.purpose_text}”</p>}

      <div className="grid">
        <div className="card">
          <div className="big">{money(m.balance, m.currency)}</div>
          <div className="small muted" style={{ marginBottom: "0.6rem" }}>available of {money(m.funded, m.currency)} funded</div>
          <ContributionBar m={m} />
          <hr />
          <FundButton mandate={m} onFunded={refresh} />
        </div>
        <div className="card">
          <div className="row between">
            <h3 style={{ margin: 0 }}>Rules</h3>
            <span className={`badge ${m.signature_valid ? "ok" : "bad"}`} title="HMAC signature over the rules">
              {m.signature_valid ? `Signed · v${m.version}` : "Signature broken"}
            </span>
          </div>
          <ul className="rules">
            {m.rules.map((r) => <li key={r.id}><span className="tick">✓</span>{r.text}</li>)}
          </ul>
          <p className="small muted" style={{ margin: "0.5rem 0 0" }}>
            The rules engine decides every payment. The assistant can only make a request stricter, never approve it.
          </p>
        </div>
      </div>

      {covered.map((b) => <QuickActions key={b.id} mandate={m} beneficiary={b} onChange={refresh} />)}
      {covered.length === 0 && <div className="section"><RequestForm mandate={m} /></div>}

      <div className="section">
        <h2>Requests</h2>
        <ErrorNote error={requests.error} />
        {requests.data?.length === 0 && <Empty>No requests yet. Payees and family can also ask in the chat.</Empty>}
        <div className="stack">{requests.data?.map((r) => <RequestRow key={r.id} r={r} showMandate={false} />)}</div>
      </div>

      <div className="section card">
        <h2>Ledger</h2>
        <p className="small muted">Every change is recorded here and can never be edited.</p>
        <Ledger key={requests.data?.length ?? 0} query={`mandate=${m.id}`} />
      </div>
    </>
  );
}
