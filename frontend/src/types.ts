// Shapes returned by the Django API (backend/*/serializers.py and views.py).

export interface Me {
  id: number;
  username: string;
  name: string;
  family: { id: string; name: string } | null;
  role: "ADMIN" | "FUNDER" | "VIEWER" | null;
  country: string;
}

export interface Session {
  authenticated: boolean;
  user: Me | null;
  demo_mode: boolean;
}

export interface Member {
  user_id: number;
  username: string;
  name: string;
  role: string;
  country: string;
  phone: string;
  paypal_email: string;
}

export interface Family {
  id: string;
  name: string;
  role: string;
  members: Member[];
}

export interface Beneficiary {
  id: string;
  name: string;
  relationship: string;
  phone: string;
  allowed_products: string[];
  verified_at: string | null;
  phone_changed_at: string | null;
  phone_recently_changed: boolean;
}

export interface Payee {
  id: string;
  name: string;
  kind: string;
  kind_label: string;
  rail: string;
  rail_label: string;
  paypal_email: string;
  external_ref: string;
  phone: string;
  verified: boolean;
  shared: boolean;
  simulated: boolean;
}

export interface RuleInput {
  kind: string;
  params: Record<string, unknown>;
}

export interface Rule extends RuleInput {
  id?: string;
  position?: number;
  text: string;
}

export interface Funder {
  user_id: number;
  name: string;
  role: "OWNER" | "CO_FUNDER";
  contributed: string;
}

export interface Mandate {
  id: string;
  type: string;
  type_label: string;
  title: string;
  purpose_text: string;
  status: string;
  currency: string;
  version: number;
  signature_valid: boolean;
  expires_at: string | null;
  created_at: string;
  balance: string;
  funded: string;
  funders: Funder[];
  rules: Rule[];
  beneficiary_ids: string[];
  pending: number;
}

export interface Draft {
  type: string;
  type_label: string;
  title: string;
  rules: Rule[];
  explanation: string;
  questions: string[];
  errors: string[];
  purpose_text: string;
}

export interface Signal {
  signal: string;
  weight: number;
  detail: string;
}

export interface AiFlag {
  flag: string;
  reason: string;
  quote: string;
}

export interface Risk {
  level: "LOW" | "MEDIUM" | "HIGH";
  score: number;
  signals: Signal[];
  ai_flags: AiFlag[];
  ai_summary: string;
  suggested_verification: string;
  model_name: string;
}

export interface Payment {
  id: string;
  rail: string;
  amount: string;
  reference: string;
  external_id: string;
  simulated: boolean;
  status: "PENDING" | "SUCCESS" | "FAILED" | "RETURNED";
  last_mile_status: "N/A" | "DELIVERING" | "DELIVERED" | "AWAITING_COLLECTION" | "COLLECTED";
  collection_code: string;
  created_at: string;
  updated_at: string;
}

export type RequestStatus =
  | "NEW" | "ASSESSED" | "APPROVED" | "REFUSED" | "ESCALATED" | "HELD_FRAUD" | "PAID" | "FAILED" | "CANCELLED"
  | "CONFIRMED_FRAUD";

export interface PayRequest {
  id: string;
  mandate: string;
  mandate_title: string;
  mandate_type: string;
  currency: string;
  channel: string;
  requester: string;
  requester_phone: string;
  beneficiary: string | null;
  beneficiary_name: string | null;
  payee: string | null;
  payee_name: string | null;
  payee_simulated: boolean;
  product: string;
  amount: string;
  message_text: string;
  summary_en: string;
  status: RequestStatus;
  created_at: string;
  decision: { outcome: string; reason: string; decided_by: string } | null;
  risk: Risk | null;
  payment: Payment | null;
}

export interface RuleResult {
  rule_id: string | null;
  kind: string;
  passed: boolean;
  detail: string;
}

export interface RequestDetail extends PayRequest {
  evidence: {
    id: string;
    kind: string;
    upload_id: string | null;
    upload_name: string | null;
    content_type: string | null;
    extracted: Record<string, unknown>;
    model_name: string;
    created_at: string;
  }[];
  decisions: { id: string; outcome: string; reason: string; rule_results: RuleResult[]; decided_by: string;
    created_at: string }[];
  approvals: { id: string; user_name: string; action: string; note: string; created_at: string }[];
  rail_transactions: Payment[];
  allowed_actions: string[];
}

export interface LedgerEntry {
  id: string;
  event: string;
  mandate: string;
  mandate_title: string;
  request: string | null;
  amount: string | null;
  actor: string;
  actor_name: string;
  data: Record<string, unknown>;
  created_at: string;
}

export interface Coverage {
  product: string;
  period: string;
  cap: string | null;
  used: string;
  min_interval_hours: number | null;
  covered_by: { request_id: string; by: string; amount: string; at: string; status: string }[];
  summary: string;
}

export interface Conversation {
  id: string;
  phone: string | null;
  is_me: boolean;
  label: string;
  updated_at: string;
}

// Scoped by the backend (agent/chat.py outcome): a requester never sees fraud details.
export interface ChatCard {
  request_id: string;
  status: RequestStatus;
  amount: string;
  product: string;
  message?: string;
  decision?: string;
  reason?: string;
  failed_rules?: string[];
  payment?: { status: string; delivery: string; simulated_rail: boolean; collection_code?: string };
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  attachments: { upload_id: string; name: string; content_type: string }[];
  created_at: string;
  card: ChatCard | null;
}
