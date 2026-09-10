// API client — proxied through Vite dev server to http://localhost:8000

const BASE = '/api/v1';

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`API error ${res.status}: ${path}`);
  return res.json();
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err?.detail?.message || `API error ${res.status}`);
  }
  return res.json();
}

// ── Types ──────────────────────────────────────────────────────────────────

export interface Hospital {
  id: number;
  hospital_code: string;
  hospital_name: string;
  integration_type: string;
  status: string;
  created_at: string;
}

export interface TransactionItem {
  id: number;
  hospital_code: string;
  common_code: string | null;
  description: string;
  quantity: number;
  unit_price: number;
  benchmark_price: number | null;
  benchmark_status: string | null;
  mapping_status: string | null;
  mapping_confidence: number | null;
  allowed_maximum: number | null;
  variance_percent: number | null;
}

export interface FWAResult {
  id: number;
  rule_code: string;
  rule_name: string;
  result: string;
  reason: string | null;
  severity: string | null;
  created_at: string;
}

export interface Adjudication {
  id: number;
  status: string;
  approved_amount: number;
  reason: string | null;
  reference: string | null;
  his_delivery_status: string | null;
  processed_at: string;
}

export interface IntegrationEvent {
  id: number;
  transaction_id?: string;
  event_type: string;
  source: string | null;
  status: string | null;
  payload: Record<string, unknown> | null;
  created_at: string;
}

export interface FacilityCode {
  local_code: string;
  description: string;
  category: string | null;
  common_code: string | null;
  common_description: string | null;
  mapped: boolean;
}

export interface Transaction {
  id: number;
  transaction_id: string;
  hospital: Hospital;
  patient_reference: string;
  submitted_amount: number;
  normalized_amount: number;
  status: string;
  created_at: string;
  updated_at: string;
  items: TransactionItem[];
  fwa_results: FWAResult[];
  adjudication: Adjudication | null;
  integration_events: IntegrationEvent[];
}

export interface TransactionListItem {
  id: number;
  transaction_id: string;
  hospital_name: string;
  hospital_code: string;
  patient_reference: string;
  submitted_amount: number;
  status: string;
  created_at: string;
}

export interface CodeMappingRow {
  hospital_code: string;
  hospital_name: string;
  local_code: string;
  local_description: string;
  common_code: string;
  common_description: string;
  category: string;
  mapping_status: string;
  confidence: number;
  terminology_system?: string;
  terminology_version?: string;
}

export interface BenchmarkRow {
  common_code: string;
  benchmark_price: number;
  allowed_variance_percent: number;
}

export interface DashboardMetrics {
  connected_hospitals: number;
  total_transactions: number;
  approved: number;
  review: number;
  fwa_flagged: number;
  rejected: number;
}

export interface SubmitTransactionPayload {
  hospital_id: string;
  transaction_id: string;
  patient_reference: string;
  items: Array<{
    hospital_code: string;
    description: string;
    quantity: number;
    unit_price: number;
  }>;
}

// ── API Functions ──────────────────────────────────────────────────────────

export const api = {
  getDashboardMetrics: () => get<DashboardMetrics>('/dashboard/metrics'),
  getHospitals: () => get<Hospital[]>('/hospitals'),
  getCodeMappings: () => get<CodeMappingRow[]>('/codes/mappings'),
  getBenchmarks: () => get<BenchmarkRow[]>('/benchmarks'),
  getTransactions: () => get<TransactionListItem[]>('/transactions'),
  getTransaction: (id: string) => get<Transaction>(`/transactions/${id}`),
  submitTransaction: (payload: SubmitTransactionPayload) =>
    // Routes through /demo/submit — the explicit internal path for admin demo/HIS tester.
    // Authenticated facility submissions use POST /transactions via fetchWithAuth.
    post<Transaction>('/demo/submit', payload),
  resetDemo: () => post<{ status: string; message: string }>('/demo/reset', {}),
  getAuditLogs: () => get<IntegrationEvent[]>('/audit/logs'),
};
