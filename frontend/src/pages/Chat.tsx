import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { api, money, uploadUrl, when } from "../api";
import { uploadFile } from "../components/RequestForm";
import { ErrorNote, Loading, SimTag } from "../components/ui";
import { useAction, useApi, usePoll, useSession } from "../hooks";
import { navigate, query } from "../router";
import type { Beneficiary, ChatCard, ChatMessage, Conversation, Payee } from "../types";

interface Thread {
  conversation: Conversation;
  messages: ChatMessage[];
}

export default function Chat({ path }: { path: string }) {
  const { session } = useSession();
  const conversations = useApi<Conversation[]>("/chat/conversations/");
  const beneficiaries = useApi<Beneficiary[]>(session.demo_mode ? "/beneficiaries/" : null);
  const payees = useApi<Payee[]>(session.demo_mode ? "/payees/" : null);
  const [otherNumber, setOtherNumber] = useState("");
  const opening = useAction();
  const selected = query(path).get("c");

  const open = (phone?: string) => opening.run(async () => {
    const c = await api.post<Conversation>("/chat/conversations/", phone ? { phone } : {});
    await conversations.reload();
    navigate(`/chat?c=${c.id}`);
  });

  // Start on the funder's own chat.
  useEffect(() => {
    if (!selected && conversations.data) {
      const mine = conversations.data.find((c) => c.is_me);
      if (mine) navigate(`/chat?c=${mine.id}`);
      else void open();
    }
  }, [selected, conversations.data]); // eslint-disable-line react-hooks/exhaustive-deps

  const actAs = [
    ...(beneficiaries.data ?? []).map((b) => ({ phone: b.phone, label: `${b.name} (beneficiary)` })),
    ...(payees.data ?? []).filter((p) => p.phone).map((p) => ({ phone: p.phone, label: `${p.name} (payee)` })),
  ];

  return (
    <div className="chat-layout">
      <aside>
        <h1>Chat</h1>
        <div className="conv-list">
          {conversations.data?.filter((c) => c.is_me).map((c) => (
            <button key={c.id} className={selected === c.id ? "active" : ""} onClick={() => navigate(`/chat?c=${c.id}`)}>Me (funder)</button>
          ))}
        </div>
        {session.demo_mode && (
          <div className="section">
            <h3>Talk as… <SimTag label="Demo" /></h3>
            <p className="small muted">See what a beneficiary, payee or stranger gets when they message the family's number.</p>
            <div className="conv-list">
              {actAs.map((a) => {
                const c = conversations.data?.find((x) => x.phone === a.phone);
                return (
                  <button key={a.phone} className={c && selected === c.id ? "active" : ""} disabled={opening.busy}
                    onClick={() => (c ? navigate(`/chat?c=${c.id}`) : open(a.phone))}>{a.label}</button>
                );
              })}
              {conversations.data?.filter((c) => !c.is_me && !actAs.some((a) => a.phone === c.phone)).map((c) => (
                <button key={c.id} className={selected === c.id ? "active" : ""} onClick={() => navigate(`/chat?c=${c.id}`)}>{c.label}</button>
              ))}
            </div>
            <div className="row" style={{ marginTop: "0.6rem" }}>
              <input aria-label="Any other phone number" placeholder="Other number" value={otherNumber}
                onChange={(e) => setOtherNumber(e.target.value)} style={{ flex: 1, minWidth: 0 }} />
              <button disabled={!otherNumber || opening.busy} onClick={() => { void open(otherNumber); setOtherNumber(""); }}>Open</button>
            </div>
            <ErrorNote error={opening.error} />
          </div>
        )}
      </aside>
      {selected ? <ThreadView key={selected} id={selected} /> : <Loading />}
    </div>
  );
}

function ThreadView({ id }: { id: string }) {
  const { data, error, reload, setData } = useApi<Thread>(`/chat/${id}/messages/`);
  const [text, setText] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [pending, setPending] = useState<string | null>(null);
  const sending = useAction();
  const end = useRef<HTMLDivElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  usePoll(reload, 5000, !sending.busy); // delivery notices arrive on their own

  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth" });
  }, [data?.messages.length, pending]);

  const send = () => sending.run(async () => {
    const message = text.trim();
    setPending(message || "(photo)");
    setText("");
    try {
      const upload_ids = [];
      for (const f of files) upload_ids.push((await uploadFile(f)).id);
      setFiles([]);
      setData(await api.post<Thread>(`/chat/${id}/messages/`, { text: message, upload_ids }));
    } catch (e) {
      setText(message);
      throw e;
    } finally {
      setPending(null);
    }
  });
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (text.trim() || files.length) void send();
    }
  };

  return (
    <section className="card chat" aria-label="Conversation">
      <div className="chat-head">
        <strong>{data?.conversation.is_me ? "Thuma assistant" : data?.conversation.label ?? "…"}</strong>
        <div className="small muted">
          {data?.conversation.is_me
            ? "Ask about balances, request support, or why something was refused. It cannot pay or change rules."
            : "You are writing as this number. The assistant treats it exactly like a real message from it."}
        </div>
      </div>
      <div className="messages">
        <ErrorNote error={error} />
        {!data && !error && <Loading />}
        {data?.messages.length === 0 && <p className="muted small" style={{ textAlign: "center" }}>Say hello in English, isiNdebele or Shona.</p>}
        {data?.messages.map((m) => (
          <div key={m.id} style={{ display: "contents" }}>
            <div className={`bubble ${m.role}`}>
              {m.text}
              {m.attachments.map((a) => (
                a.content_type.startsWith("image/")
                  ? <img key={a.upload_id} src={uploadUrl(a.upload_id)} alt={a.name} />
                  : <span key={a.upload_id} className="att">📎 {a.name}</span>
              ))}
              <span className="att" style={{ marginTop: "0.2rem" }}>{when(m.created_at)}</span>
            </div>
            {m.role === "assistant" && m.card && <DecisionCard card={m.card} />}
          </div>
        ))}
        {pending && <div className="bubble user" style={{ opacity: 0.6 }}>{pending}</div>}
        {sending.busy && <div className="typing">Assistant is checking…</div>}
        <div ref={end} />
      </div>
      {sending.error && <div style={{ padding: "0 0.6rem" }}><ErrorNote error={sending.error} /></div>}
      {files.length > 0 && (
        <div className="chips">
          {files.map((f, i) => (
            <span className="chip" key={i}>{f.name}
              <button className="link-btn" aria-label={`Remove ${f.name}`} onClick={() => setFiles(files.filter((_, j) => j !== i))}>×</button>
            </span>
          ))}
        </div>
      )}
      <div className="composer">
        <input ref={fileInput} type="file" accept="image/*" multiple hidden
          onChange={(e) => { setFiles([...files, ...Array.from(e.target.files ?? [])]); e.target.value = ""; }} />
        <button aria-label="Attach a photo" title="Attach a photo of a quote, invoice or progress" onClick={() => fileInput.current?.click()}>📷</button>
        <textarea aria-label="Message" rows={1} value={text} onChange={(e) => setText(e.target.value)} onKeyDown={onKey}
          placeholder="Write a message" />
        <button className="primary" disabled={sending.busy || (!text.trim() && files.length === 0)} onClick={send}>Send</button>
      </div>
    </section>
  );
}

function DecisionCard({ card }: { card: ChatCard }) {
  const s = card.status;
  const tone = s === "PAID" || s === "APPROVED" ? "ok" : s === "REFUSED" || s === "FAILED" || s === "CONFIRMED_FRAUD" ? "bad"
    : s === "HELD_FRAUD" || s === "ESCALATED" ? "warn" : "info";
  const title = {
    PAID: "Paid", APPROVED: "Approved, paying now", REFUSED: "Refused", ESCALATED: "Waiting for a funder",
    HELD_FRAUD: "Held for verification", CONFIRMED_FRAUD: "Reported as fraud", FAILED: "Payment failed",
  }[s as string] ?? s;
  const p = card.payment;
  return (
    <div className={`decision-card ${tone}`}>
      <div className="row between">
        <strong>{title}</strong>
        <span>{money(card.amount)} {card.product}</span>
      </div>
      {card.message && <div className="small">{card.message}</div>}
      {card.reason && s !== "APPROVED" && s !== "PAID" && <div className="small">{card.reason}</div>}
      {p && (
        <div className="small row" style={{ marginTop: "0.25rem" }}>
          <span>Payment {p.status.toLowerCase()}{p.delivery && p.delivery !== "N/A" ? ` · ${p.delivery.replace(/_/g, " ").toLowerCase()}` : ""}</span>
          {p.collection_code && <strong>Code {p.collection_code}</strong>}
          {p.simulated_rail && <SimTag />}
        </div>
      )}
      <a className="small" href={`#/requests/${card.request_id}`}>Details</a>
    </div>
  );
}
