import { useState } from "react";
import { api } from "../api";
import { ErrorNote, Loading, SimTag } from "../components/ui";
import { useAction, useApi } from "../hooks";
import type { Beneficiary, Family, Payee } from "../types";

const PRODUCTS = ["airtime", "bundles", "cash"];
const PAYEE_KINDS: [string, string][] = [
  ["SUPPLIER", "Supplier"], ["SCHOOL", "School"], ["FUNERAL_PROVIDER", "Funeral provider"], ["MEDICAL_AID", "Medical aid"], ["OTHER", "Other"],
];

export default function People() {
  const beneficiaries = useApi<Beneficiary[]>("/beneficiaries/");
  const payees = useApi<Payee[]>("/payees/");
  const family = useApi<Family>("/family/");

  return (
    <>
      <h1>People</h1>
      <div className="section">
        <h2>Beneficiaries</h2>
        <p className="small muted">The people the family supports. Only their registered numbers are trusted.</p>
        <ErrorNote error={beneficiaries.error} />
        {beneficiaries.loading && !beneficiaries.data && <Loading />}
        <div className="stack">
          {beneficiaries.data?.map((b) => <BeneficiaryCard key={b.id} b={b} onSaved={beneficiaries.reload} />)}
          <AddBeneficiary onSaved={beneficiaries.reload} />
        </div>
      </div>

      <div className="section">
        <h2>Payees</h2>
        <p className="small muted">Businesses that can be paid directly. Real payouts go through PayPal.</p>
        <ErrorNote error={payees.error} />
        <div className="grid">
          {payees.data?.map((p) => (
            <div className="card" key={p.id}>
              <div className="row between">
                <strong>{p.name}</strong>
                {p.verified ? <span className="badge ok">Verified</span> : <span className="badge warn">Not verified</span>}
              </div>
              <div className="small muted">{p.kind_label}</div>
              <div className="row small" style={{ marginTop: "0.35rem" }}>
                <span className="badge">{p.rail_label}</span>
                {p.rail === "BILLER_SIM" && <SimTag />}
                {p.rail === "LOCAL_MOBILE_MONEY" && <SimTag label="Simulated last mile" />}
              </div>
              {p.phone && <div className="small muted" style={{ marginTop: "0.3rem" }}>Chat number {p.phone}</div>}
            </div>
          ))}
        </div>
        <div className="section"><AddPayee onSaved={payees.reload} /></div>
      </div>

      <div className="section">
        <h2>Family</h2>
        <div className="card">
          <ul className="funders">
            {family.data?.members.map((m) => (
              <li key={m.user_id}>
                <span>{m.name} <span className="muted small">· {m.role.toLowerCase()}{m.country ? ` · ${m.country}` : ""}</span></span>
                <span className="small muted">{m.phone}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </>
  );
}

function BeneficiaryCard({ b, onSaved }: { b: Beneficiary; onSaved: () => void }) {
  const [editing, setEditing] = useState(false);
  const [phone, setPhone] = useState(b.phone);
  const { busy, error, run } = useAction();
  const save = () => run(async () => {
    await api.patch(`/beneficiaries/${b.id}/`, { phone });
    setEditing(false);
    onSaved();
  });

  return (
    <div className="card">
      <div className="row between">
        <div>
          <strong>{b.name}</strong> <span className="muted small">{b.relationship}</span>
          <div className="small">{b.phone}</div>
        </div>
        <div className="row small">{b.allowed_products.map((p) => <span key={p} className="badge brand">{p}</span>)}</div>
      </div>
      {b.phone_recently_changed && (
        <div className="notice warn small" style={{ marginTop: "0.5rem" }}>Number changed recently: extra fraud checks apply until 72 hours have passed.</div>
      )}
      {editing ? (
        <div className="stack">
          <div className="notice warn small">
            Changing the number makes every request for {b.name} go through extra fraud checks for 72 hours.
            Scammers often ask families to “update” a number first.
          </div>
          <div className="row">
            <input aria-label="New phone number" value={phone} onChange={(e) => setPhone(e.target.value)} style={{ maxWidth: "14rem" }} />
            <button className="primary" disabled={busy || phone === b.phone} onClick={save}>Save number</button>
            <button onClick={() => { setEditing(false); setPhone(b.phone); }}>Cancel</button>
          </div>
          <ErrorNote error={error} />
        </div>
      ) : (
        <button className="link-btn small" style={{ marginTop: "0.4rem" }} onClick={() => setEditing(true)}>Change number</button>
      )}
    </div>
  );
}

function AddBeneficiary({ onSaved }: { onSaved: () => void }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: "", relationship: "", phone: "", allowed_products: ["airtime", "bundles"] });
  const { busy, error, run } = useAction();
  const save = () => run(async () => {
    await api.post("/beneficiaries/", form);
    setOpen(false);
    setForm({ name: "", relationship: "", phone: "", allowed_products: ["airtime", "bundles"] });
    onSaved();
  });
  if (!open) return <button onClick={() => setOpen(true)}>Register a beneficiary</button>;
  return (
    <div className="card">
      <h3>Register a beneficiary</h3>
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))" }}>
        <div><label htmlFor="b-name">Name</label><input id="b-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
        <div><label htmlFor="b-rel">Relationship</label><input id="b-rel" value={form.relationship} onChange={(e) => setForm({ ...form, relationship: e.target.value })} /></div>
        <div><label htmlFor="b-phone">Phone</label><input id="b-phone" placeholder="0771234567" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></div>
      </div>
      <div className="field">
        <label>Allowed</label>
        <div className="checks">
          {PRODUCTS.map((p) => (
            <label key={p}>
              <input type="checkbox" checked={form.allowed_products.includes(p)} onChange={(e) => setForm({
                ...form, allowed_products: e.target.checked ? [...form.allowed_products, p] : form.allowed_products.filter((x) => x !== p),
              })} />{p}
            </label>
          ))}
        </div>
      </div>
      <div className="row field">
        <button className="primary" disabled={busy || !form.name || !form.phone} onClick={save}>Register</button>
        <button onClick={() => setOpen(false)}>Cancel</button>
      </div>
      <ErrorNote error={error} />
    </div>
  );
}

function AddPayee({ onSaved }: { onSaved: () => void }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: "", kind: "SUPPLIER", paypal_email: "", phone: "" });
  const { busy, error, run } = useAction();
  const save = () => run(async () => {
    await api.post("/payees/", { ...form, rail: "PAYPAL_PAYOUT" });
    setOpen(false);
    setForm({ name: "", kind: "SUPPLIER", paypal_email: "", phone: "" });
    onSaved();
  });
  if (!open) return <button onClick={() => setOpen(true)}>Add a payee</button>;
  return (
    <div className="card">
      <h3>Add a payee</h3>
      <p className="small muted">New payees start unverified. Paid by PayPal Payout to their PayPal email.</p>
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))" }}>
        <div><label htmlFor="p-name">Business name</label><input id="p-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
        <div>
          <label htmlFor="p-kind">Kind</label>
          <select id="p-kind" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
            {PAYEE_KINDS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
        </div>
        <div><label htmlFor="p-email">PayPal email</label><input id="p-email" type="email" value={form.paypal_email} onChange={(e) => setForm({ ...form, paypal_email: e.target.value })} /></div>
        <div><label htmlFor="p-phone">Chat number (optional)</label><input id="p-phone" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></div>
      </div>
      <div className="row field">
        <button className="primary" disabled={busy || !form.name || !form.paypal_email} onClick={save}>Add</button>
        <button onClick={() => setOpen(false)}>Cancel</button>
      </div>
      <ErrorNote error={error} />
    </div>
  );
}
