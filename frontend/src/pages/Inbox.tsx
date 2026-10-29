import { money, when } from "../api";
import { ApprovalActions, FraudCard } from "../components/Approval";
import { Empty, ErrorNote, Loading, riskTone } from "../components/ui";
import { useApi } from "../hooks";
import type { PayRequest } from "../types";

/** Escalations and fraud holds on mandates this funder funds. Fraud holds first. */
export default function Inbox() {
  const { data, error, loading, reload } = useApi<PayRequest[]>("/requests/?inbox=1");
  const sorted = [...(data ?? [])].sort((a, b) => Number(b.status === "HELD_FRAUD") - Number(a.status === "HELD_FRAUD"));

  return (
    <>
      <h1>Approvals</h1>
      <p className="muted">Requests the rules sent to the family: possible fraud, and anything over an approval limit.</p>
      <ErrorNote error={error} />
      {loading && !data && <Loading />}
      {data?.length === 0 && <Empty>Nothing is waiting for you.</Empty>}
      <div className="stack">
        {sorted.map((r) =>
          r.status === "HELD_FRAUD" && r.risk ? (
            <div key={r.id}>
              <FraudCard r={r} />
              <div className="card">
                <ApprovalActions r={r} onDone={() => reload()} />
                <a className="small" href={`#/requests/${r.id}`}>Full details</a>
              </div>
            </div>
          ) : (
            <div key={r.id} className="card" style={{ borderColor: "var(--warn)" }}>
              <div className="row between">
                <strong>{money(r.amount, r.currency)} {r.product}{r.beneficiary_name ? ` for ${r.beneficiary_name}` : ""}</strong>
                {r.risk && r.risk.level !== "LOW" && <span className={`badge ${riskTone(r.risk.level)}`}>Risk {r.risk.score}</span>}
              </div>
              <div className="small muted">{r.requester} · {r.mandate_title} · {when(r.created_at)}</div>
              <p style={{ margin: "0.5rem 0 0" }}>{r.decision?.reason}</p>
              {r.message_text && <blockquote className="small muted" style={{ margin: "0.4rem 0 0" }}>“{r.message_text}”</blockquote>}
              <ApprovalActions r={r} onDone={() => reload()} />
              <a className="small" href={`#/requests/${r.id}`}>Full details</a>
            </div>
          ),
        )}
      </div>
    </>
  );
}
