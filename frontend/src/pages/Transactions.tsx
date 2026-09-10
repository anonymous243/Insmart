import React, { useEffect, useState, useRef } from 'react';
import { api, Transaction, TransactionListItem, Hospital, CodeMappingRow, BenchmarkRow } from '../api/client';
import { StatusBadge } from '../components/StatusBadge';
import { CURRENCY_SYMBOL, CURRENCY_LOCALE } from '../config';

function fmt(n: number) {
  return new Intl.NumberFormat(CURRENCY_LOCALE, { minimumFractionDigits: 2 }).format(n);
}

// ── Deterministic demo scenarios ──────────────────────────────────────────────
// Each has a fixed patient reference so results are predictable.
// Scenario 3 requires the demo DB to be reset (which seeds DEMO-PRIOR-001) first.

const DEMO_SCENARIOS = [
  {
    id: 'S1',
    label: 'Scenario 1 — Approved',
    hospital: 'H001',
    hospitalName: 'Hanoi General Hospital',
    color: 'var(--green)',
    borderColor: 'var(--border)',
    bgColor: 'var(--bg-surface)',
    expectedOutcome: 'APPROVED',
    outcomeDesc: 'Within benchmark, FWA clear → TPA Core approves',
    items: [
      { hospital_code: 'CARD001', description: 'Cardiology Consultation', quantity: 1, unit_price: 700 },
      { hospital_code: 'XR001',   description: 'Chest X-Ray',             quantity: 1, unit_price: 480 },
    ],
    patient_reference: 'PAT-089',
    notes: [
      'CARD001 → CONS-CARD (benchmark: 750, max: 900, submitted: 700 ✓)',
      'XR001 → XR-CHEST (benchmark: 500, max: 600, submitted: 480 ✓)',
    ],
  },
  {
    id: 'S2',
    label: 'Scenario 2 — Price Review',
    hospital: 'H002',
    hospitalName: 'Saigon Medical Center',
    color: 'var(--yellow)',
    borderColor: 'var(--border)',
    bgColor: 'var(--bg-surface)',
    expectedOutcome: 'REVIEW',
    outcomeDesc: 'Submitted price exceeds benchmark maximum → FWA-003 PRICE_FLAG → TPA Core: Review',
    items: [
      { hospital_code: 'CC-102', description: 'Cardiac Consultation', quantity: 1, unit_price: 1100 },
    ],
    patient_reference: 'PAT-211',
    notes: [
      'CC-102 → CONS-CARD (benchmark: 750, max: 900, submitted: 1100 ✗)',
      'FWA-003 Price Anomaly triggered: +46.7% over benchmark',
    ],
  },
  {
    id: 'S3',
    label: 'Scenario 3 — FWA Duplicate',
    hospital: 'H001',
    hospitalName: 'Hanoi General Hospital',
    color: 'var(--red)',
    borderColor: 'var(--border)',
    bgColor: 'var(--bg-surface)',
    expectedOutcome: 'REJECTED',
    outcomeDesc: 'Same patient, same hospital, same service, same day → FWA-001 Duplicate → TPA Core: Rejected',
    items: [
      { hospital_code: 'CARD001', description: 'Cardiology Consultation', quantity: 1, unit_price: 700 },
    ],
    patient_reference: 'PAT-933',
    notes: [
      'Patient PAT-933 has an existing CONS-CARD claim at H001 processed earlier today',
      'FWA-001 Duplicate Service triggered → REJECTED',
    ],
  },
];

// Processing pipeline stages — mapped from integration event types
const PIPELINE_STAGES: { key: string; label: string; events: string[] }[] = [
  { key: 'RECEIVED',       label: 'Received',          events: ['TRANSACTION_RECEIVED'] },
  { key: 'VALIDATED',      label: 'Validated',          events: ['CODE_MAPPED'] },
  { key: 'NORMALIZED',     label: 'Codes Normalized',   events: ['CODE_MAPPED'] },
  { key: 'BENCHMARKED',    label: 'Benchmarked',        events: ['BENCHMARK_COMPLETED'] },
  { key: 'FWA_CHECKED',    label: 'FWA Checked',        events: ['FWA_COMPLETED'] },
  { key: 'SENT_TO_TPA',    label: 'Sent to TPA Core',   events: ['TPA_SUBMITTED'] },
  { key: 'ADJUDICATED',    label: 'Adjudicated',        events: ['TPA_RESPONSE_RECEIVED'] },
  { key: 'HIS_SENT',       label: 'HIS Response Sent',  events: ['HIS_CALLBACK_SENT'] },
  { key: 'HIS_ACK',        label: 'HIS Acknowledged',   events: ['HIS_CALLBACK_DELIVERED', 'HIS_CALLBACK_ACKNOWLEDGED'] },
];

function getCompletedStages(events: { event_type: string }[]): Set<string> {
  const completed = new Set<string>();
  const eventTypes = new Set(events.map(e => e.event_type));
  for (const stage of PIPELINE_STAGES) {
    if (stage.events.some(et => eventTypes.has(et))) {
      completed.add(stage.key);
    }
  }
  return completed;
}

// ── Stage Tracker component ──────────────────────────────────────────────────

const StageTracker: React.FC<{ completedStages: Set<string>; adjStatus?: string }> = ({ completedStages, adjStatus }) => {
  return (
    <div style={{ display: 'flex', gap: 0, flexWrap: 'wrap' }}>
      {PIPELINE_STAGES.map((stage, i) => {
        const done = completedStages.has(stage.key);
        const isAdj = stage.key === 'ADJUDICATED';
        const adjColor = adjStatus === 'APPROVED' ? 'var(--green)' : adjStatus === 'REJECTED' ? 'var(--red)' : 'var(--yellow)';
        return (
          <React.Fragment key={stage.key}>
            <div style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: 4,
              minWidth: 80,
              flex: '1 1 0',
            }}>
              <div style={{
                width: 32, height: 32,
                borderRadius: '50%',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                background: done ? (isAdj && adjStatus ? adjColor : 'var(--accent)') : 'var(--bg-surface)',
                border: `2px solid ${done ? (isAdj && adjStatus ? adjColor : 'var(--accent)') : 'var(--border)'}`,
                color: done ? '#fff' : 'var(--text-muted)',
                transition: 'all 0.3s ease',
                fontWeight: 700,
                fontSize: 12,
              }}>
                {done ? '✓' : String(i + 1)}
              </div>
              <div style={{
                fontSize: 10,
                color: done ? (isAdj && adjStatus ? adjColor : 'var(--accent)') : 'var(--text-muted)',
                textAlign: 'center',
                fontWeight: done ? 600 : 400,
                lineHeight: 1.3,
                transition: 'color 0.3s',
              }}>{stage.label}</div>
            </div>
            {i < PIPELINE_STAGES.length - 1 && (
              <div style={{
                flex: '0 0 20px',
                display: 'flex',
                alignItems: 'center',
                paddingBottom: 20,
                color: completedStages.has(PIPELINE_STAGES[i + 1]?.key) ? 'var(--green)' : 'var(--border)',
                fontSize: 14,
                transition: 'color 0.3s',
              }}>—</div>
            )}
          </React.Fragment>
        );
      })}
    </div>
  );
};

// ── Transaction Detail panel ───────────────────────────────────────────────────

const TxnDetailPanel: React.FC<{ txn: Transaction; onClose: () => void }> = ({ txn, onClose }) => {
  const adj = txn.adjudication;
  const hasFWAFlags = txn.fwa_results.some(r => r.result !== 'PASS');
  const completedStages = getCompletedStages(txn.integration_events);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20, marginTop: 4 }}>
      {/* Processing pipeline tracker */}
      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <div className="card-title" style={{ margin: 0 }}>Processing Pipeline</div>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            <StatusBadge value={txn.status} />
            <button className="btn btn-secondary btn-sm" onClick={onClose}>✕ Close</button>
          </div>
        </div>
        <StageTracker completedStages={completedStages} adjStatus={adj?.status} />
      </div>

      <div className="two-col">
        {/* Claim Items — code normalization + benchmarks */}
        <div>
          <div className="section-title">Claim Line Items</div>
          {txn.items.map(item => (
            <div key={item.id} className="card" style={{ marginBottom: 12, padding: '14px 16px' }}>
              {/* Normalization arrow */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10 }}>
                <div>
                  <div className="norm-arrow" style={{ marginBottom: 3 }}>
                    <span className="norm-from">{item.hospital_code}</span>
                    <span className="norm-sep">→</span>
                    <span className="norm-to">{item.common_code || 'UNMAPPED'}</span>
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{item.description}</div>
                </div>
                <StatusBadge value={item.benchmark_status || 'NO_BENCHMARK'} />
              </div>
              <div className="kv-list">
                <div className="kv-row">
                  <span className="kv-key">Submitted</span>
                  <span className="kv-val">{CURRENCY_SYMBOL} {item.unit_price.toFixed(2)}</span>
                </div>
                <div className="kv-row">
                  <span className="kv-key">Benchmark</span>
                  <span className="kv-val">{item.benchmark_price ? `${CURRENCY_SYMBOL} ${item.benchmark_price.toFixed(2)}` : '—'}</span>
                </div>
                <div className="kv-row">
                  <span className="kv-key">Allowed Maximum</span>
                  <span className="kv-val" style={{ color: 'var(--green)' }}>
                    {item.allowed_maximum ? `${CURRENCY_SYMBOL} ${item.allowed_maximum.toFixed(2)}` : '—'}
                  </span>
                </div>
                <div className="kv-row">
                  <span className="kv-key">Variance</span>
                  <span className="kv-val" style={{ color: (item.variance_percent || 0) > 0 ? 'var(--yellow)' : 'var(--green)' }}>
                    {item.variance_percent != null
                      ? `${item.variance_percent > 0 ? '+' : ''}${item.variance_percent.toFixed(1)}%`
                      : '—'}
                  </span>
                </div>
              </div>
              {item.benchmark_price && item.allowed_maximum && (
                <div className="benchmark-bar-wrap" style={{ marginTop: 10 }}>
                  <div className="benchmark-bar">
                    <div
                      className={`benchmark-bar-fill ${item.benchmark_status?.toLowerCase() === 'pass' ? 'pass' : 'review'}`}
                      style={{ width: `${Math.min(100, (item.unit_price / (item.allowed_maximum * 1.25)) * 100)}%` }}
                    />
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: 'var(--text-muted)', marginTop: 3 }}>
                    <span>{CURRENCY_SYMBOL} 0</span>
                    <span style={{ color: 'var(--green)' }}>Max {CURRENCY_SYMBOL} {item.allowed_maximum.toFixed(0)}</span>
                    <span>{CURRENCY_SYMBOL} {(item.allowed_maximum * 1.25).toFixed(0)}</span>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>

        {/* FWA + Adjudication */}
        <div>
          <div className="section-title">FWA Engine Results</div>
          {txn.fwa_results.map(r => (
            <div key={r.id} className="card" style={{
              marginBottom: 10, padding: '12px 14px',
              borderColor: r.result !== 'PASS' ? 'var(--border-light)' : 'var(--border)',
              background: 'var(--bg-card)',
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                <div><span className="tag" style={{ marginRight: 8 }}>{r.rule_code}</span><strong style={{ fontSize: 13 }}>{r.rule_name}</strong></div>
                <StatusBadge value={r.result} />
              </div>
              {r.reason && <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 4, lineHeight: 1.5 }}>{r.reason}</div>}
            </div>
          ))}

          {adj && (
            <>
              <div className="section-title" style={{ marginTop: 18 }}>TPA Core Decision</div>
              <div className="card" style={{
                padding: '16px',
                borderColor: 'var(--border)',
              }}>
                <div style={{ textAlign: 'center', padding: '12px 0 16px' }}>
                  <div style={{
                    fontSize: 26, fontWeight: 900, letterSpacing: '0.05em',
                    color: adj.status === 'APPROVED' ? 'var(--green)' : adj.status === 'REJECTED' ? 'var(--red)' : 'var(--yellow)',
                    marginBottom: 6,
                  }}>{adj.status}</div>
                  <div style={{ fontSize: 18, fontWeight: 700 }}>
                    {CURRENCY_SYMBOL} {fmt(adj.approved_amount)}
                  </div>
                  {adj.reference && (
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', marginTop: 4 }}>
                      Ref: {adj.reference}
                    </div>
                  )}
                </div>
                {adj.reason && (
                  <div style={{ fontSize: 12, color: 'var(--text-secondary)', padding: '8px 10px', background: 'var(--yellow-bg)', borderRadius: 6, marginBottom: 10 }}>
                    {adj.reason}
                  </div>
                )}
                <div className="kv-row">
                  <span className="kv-key">HIS Delivery</span>
                  <StatusBadge value={adj.his_delivery_status || 'PENDING'} />
                </div>
              </div>
            </>
          )}
        </div>
      </div>

      {/* Integration event timeline */}
      <div>
        <div className="section-title">Integration Event Log</div>
        <div className="card">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
            {[...txn.integration_events]
              .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime())
              .map((ev, i, arr) => {
                const isLast = i === arr.length - 1;
                return (
                  <div key={ev.id} style={{ display: 'flex', gap: 12, paddingBottom: isLast ? 0 : 16, position: 'relative' }}>
                    {!isLast && (
                      <div style={{ position: 'absolute', left: 11, top: 26, bottom: 0, width: 2, background: 'var(--border)', zIndex: 0 }} />
                    )}
                    <div style={{
                      width: 24, height: 24, borderRadius: '50%', flexShrink: 0, zIndex: 1,
                      background: ev.status === 'ERROR' ? 'var(--red-bg)' : 'var(--accent-glow)',
                      border: `2px solid ${ev.status === 'ERROR' ? 'var(--red)' : 'var(--accent)'}`,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      fontSize: 10, color: ev.status === 'ERROR' ? 'var(--red)' : 'var(--accent)',
                      fontWeight: 700,
                    }}>✓</div>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 13, fontWeight: 600 }}>{ev.event_type.replace(/_/g, ' ')}</div>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                        {new Date(ev.created_at).toLocaleTimeString('en-GB', { hour12: false })}.{String(new Date(ev.created_at).getMilliseconds()).padStart(3, '0')}
                        {ev.source && <span style={{ marginLeft: 10, color: 'var(--accent)' }}>[{ev.source}]</span>}
                      </div>
                    </div>
                  </div>
                );
              })}
          </div>
        </div>
      </div>
    </div>
  );
};

// ── HIS Transaction Tester ───────────────────────────────────────────────────

const HISTransactionTester: React.FC<{ onResult: (txn: Transaction) => void }> = ({ onResult }) => {
  const [hospitals, setHospitals] = useState<Hospital[]>([]);
  const [mappings, setMappings] = useState<CodeMappingRow[]>([]);
  const [benchmarks, setBenchmarks] = useState<BenchmarkRow[]>([]);

  const [hospitalId, setHospitalId] = useState('');
  const [patientRef, setPatientRef] = useState(`PAT-${Math.floor(1000 + Math.random() * 9000)}`);
  
  const [items, setItems] = useState([{ hospital_code: '', description: '', quantity: 1, unit_price: 0 }]);
  
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    Promise.all([
      api.getHospitals(),
      api.getCodeMappings(),
      api.getBenchmarks()
    ]).then(([hs, ms, bs]) => {
      setHospitals(hs);
      setMappings(ms);
      setBenchmarks(bs);
      if (hs.length > 0) setHospitalId(hs[0].hospital_code);
    }).catch(e => console.error(e));
  }, []);

  const handleAddItem = () => {
    setItems([...items, { hospital_code: '', description: '', quantity: 1, unit_price: 0 }]);
  };

  const handleItemChange = (index: number, field: string, value: any) => {
    const newItems = [...items];
    if (field === 'hospital_code') {
      const mapping = mappings.find(m => m.hospital_code === hospitalId && m.local_code === value);
      newItems[index] = { ...newItems[index], hospital_code: value, description: mapping?.local_description || '' };
    } else {
      newItems[index] = { ...newItems[index], [field]: value };
    }
    setItems(newItems);
  };

  const handleRemoveItem = (index: number) => {
    setItems(items.filter((_, i) => i !== index));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!hospitalId || !patientRef || items.some(it => !it.hospital_code || it.unit_price <= 0)) {
      setError('Please fill in all fields correctly.');
      return;
    }
    setSubmitting(true);
    setError('');
    
    try {
      const txnId = `TEST-${Date.now()}`;
      const txn = await api.submitTransaction({
        hospital_id: hospitalId,
        transaction_id: txnId,
        patient_reference: patientRef,
        items: items
      });
      onResult(txn);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSubmitting(false);
    }
  };

  const hospitalMappings = mappings.filter(m => m.hospital_code === hospitalId);

  return (
    <div className="card" style={{ marginBottom: 24, padding: 20 }}>
      <div className="card-title">HIS Transaction Tester</div>
      <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 16 }}>
        Simulates an automated transaction submitted by a connected Hospital HIS to the Central API Hub.
      </p>
      
      {error && <div className="alert alert-error" style={{ marginBottom: 16 }}>{error}</div>}
      
      <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        <div className="two-col" style={{ gap: 16 }}>
          <div>
            <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 4 }}>Hospital</label>
            <select className="form-select" value={hospitalId} onChange={e => { setHospitalId(e.target.value); setItems([{ hospital_code: '', description: '', quantity: 1, unit_price: 0 }]); }} style={{ width: '100%', padding: 8 }}>
              {hospitals.map(h => <option key={h.hospital_code} value={h.hospital_code}>{h.hospital_name} ({h.hospital_code})</option>)}
            </select>
          </div>
          <div>
            <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 4 }}>Patient Reference</label>
            <div style={{ display: 'flex', gap: 8 }}>
              <input className="form-input" value={patientRef} onChange={e => setPatientRef(e.target.value)} style={{ flex: 1, padding: 8 }} />
              <button type="button" className="btn btn-secondary btn-sm" onClick={() => setPatientRef(`PAT-${Math.floor(1000 + Math.random() * 9000)}`)}>Gen</button>
            </div>
          </div>
        </div>

        <div>
          <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 8 }}>Service Items</label>
          
          <div style={{ display: 'flex', gap: 12, marginBottom: 4, padding: '0 12px' }}>
            <div style={{ flex: 2, fontSize: 11, fontWeight: 600, color: 'var(--text-secondary)' }}>SERVICE CODE</div>
            <div style={{ flex: 1, fontSize: 11, fontWeight: 600, color: 'var(--text-secondary)' }}>QUANTITY</div>
            <div style={{ flex: 1, fontSize: 11, fontWeight: 600, color: 'var(--text-secondary)' }}>UNIT PRICE</div>
            {items.length > 1 && <div style={{ width: 28 }}></div>}
          </div>

          {items.map((it, idx) => {
            const mapping = hospitalMappings.find(m => m.local_code === it.hospital_code);
            const benchmark = mapping ? benchmarks.find(b => b.common_code === mapping.common_code) : null;
            const allowedMax = benchmark ? benchmark.benchmark_price * (1 + benchmark.allowed_variance_percent / 100) : null;

            return (
              <div key={idx} style={{ padding: 12, border: '1px solid var(--border)', borderRadius: 6, marginBottom: 12, background: 'var(--bg-surface)' }}>
                <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
                  <div style={{ flex: 2 }}>
                    <select className="form-select" value={it.hospital_code} onChange={e => handleItemChange(idx, 'hospital_code', e.target.value)} style={{ width: '100%', padding: 8 }}>
                      <option value="">-- Select Service --</option>
                      {hospitalMappings.map(m => (
                        <option key={m.local_code} value={m.local_code}>{m.local_code} - {m.local_description}</option>
                      ))}
                    </select>
                  </div>
                  <div style={{ flex: 1 }}>
                    <input type="number" min="1" className="form-input" value={it.quantity} onChange={e => handleItemChange(idx, 'quantity', parseInt(e.target.value) || 1)} placeholder="Qty" style={{ width: '100%', padding: 8 }} />
                  </div>
                  <div style={{ flex: 1 }}>
                    <input type="number" min="0" step="0.01" className="form-input" value={it.unit_price} onChange={e => handleItemChange(idx, 'unit_price', parseFloat(e.target.value) || 0)} placeholder="Price" style={{ width: '100%', padding: 8 }} />
                  </div>
                  {items.length > 1 && (
                    <button type="button" className="btn btn-secondary btn-sm" onClick={() => handleRemoveItem(idx)} style={{ padding: '8px 12px' }}>✕</button>
                  )}
                </div>

                {mapping && (
                  <div style={{ marginTop: 12, padding: 8, background: 'var(--bg-card)', borderRadius: 4, fontSize: 12, border: '1px solid var(--border-light)' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <div>
                        <span style={{ color: 'var(--text-muted)' }}>Normalization: </span>
                        <strong>{mapping.local_code}</strong> → <strong style={{ color: 'var(--accent)' }}>{mapping.common_code}</strong> ({mapping.common_description})
                      </div>
                      {benchmark && allowedMax && (
                        <div>
                          <span style={{ color: 'var(--text-muted)' }}>Max Allowed: </span>
                          <strong style={{ color: 'var(--green)' }}>{CURRENCY_SYMBOL} {allowedMax.toFixed(2)}</strong>
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
          <button type="button" className="btn btn-secondary btn-sm" onClick={handleAddItem}>+ Add Service</button>
        </div>

        <div style={{ marginTop: 8 }}>
          <button type="submit" className="btn btn-primary" disabled={submitting || items.length === 0} style={{ width: '100%', background: 'var(--accent)', color: 'white', borderColor: 'var(--accent)' }}>
            {submitting ? 'Submitting...' : 'Submit Transaction'}
          </button>
        </div>
      </form>
    </div>
  );
};

// ── Main Transactions / HIS Simulation page ───────────────────────────────────

export const Transactions: React.FC = () => {
  const [list, setList] = useState<TransactionListItem[]>([]);
  const [selected, setSelected] = useState<Transaction | null>(null);
  const [loading, setLoading] = useState(true);

  const [submitting, setSubmitting] = useState(false);
  const [activeScenario, setActiveScenario] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState('');

  // Progressive stage reveal: we animate through stages after result comes back
  const [simulatingStages, setSimulatingStages] = useState<Set<string>>(new Set());
  const [resultTxn, setResultTxn] = useState<Transaction | null>(null);

  const [resetting, setResetting] = useState(false);
  const [resetMsg, setResetMsg] = useState('');

  const refresh = () => api.getTransactions().then(setList).finally(() => setLoading(false));

  useEffect(() => { refresh(); }, []);

  const openDetail = (id: string) => {
    api.getTransaction(id).then(t => { setResultTxn(null); setSelected(t); });
  };

  const handleReset = async () => {
    setResetting(true);
    setResetMsg('');
    setSubmitError('');
    setResultTxn(null);
    setSelected(null);
    try {
      await api.resetDemo();
      setResetMsg('Environment reset. All scenarios will now process sequentially.');
      refresh();
    } catch (e: any) {
      setSubmitError('Reset failed: ' + e.message);
    } finally {
      setResetting(false);
    }
  };

  const exportToCSV = () => {
    if (list.length === 0) return;
    const header = ['Transaction ID', 'Hospital Code', 'Hospital Name', 'Patient Ref', 'Submitted Amount', 'Status', 'Received At'];
    const rows = list.map(t => [
      t.transaction_id,
      t.hospital_code,
      t.hospital_name,
      t.patient_reference,
      t.submitted_amount,
      t.status,
      new Date(t.created_at).toLocaleString('en-GB')
    ]);
    
    const csvContent = [
      header.join(','),
      ...rows.map(row => row.map(cell => `"${cell}"`).join(','))
    ].join('\n');
    
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.setAttribute('download', `transactions_export_${new Date().getTime()}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const runScenario = async (scenario: typeof DEMO_SCENARIOS[0]) => {
    setSubmitting(true);
    setActiveScenario(scenario.id);
    setSubmitError('');
    setResultTxn(null);
    setSelected(null);
    setSimulatingStages(new Set(['RECEIVED']));

    const txnId = `${scenario.id}-${Date.now()}`;

    // Animate stages while the API call is in flight
    const stageKeys = PIPELINE_STAGES.map(s => s.key);
    let stageIdx = 1;
    const intervalRef = setInterval(() => {
      if (stageIdx < stageKeys.length) {
        setSimulatingStages(prev => new Set([...prev, stageKeys[stageIdx]]));
        stageIdx++;
      }
    }, 400);

    try {
      const txn = await api.submitTransaction({
        hospital_id: scenario.hospital,
        transaction_id: txnId,
        patient_reference: scenario.patient_reference,
        items: scenario.items,
      });
      clearInterval(intervalRef);
      // Mark all stages complete from actual events
      setSimulatingStages(getCompletedStages(txn.integration_events));
      setResultTxn(txn);
      refresh();
    } catch (e: any) {
      clearInterval(intervalRef);
      setSubmitError(e.message);
    } finally {
      setSubmitting(false);
      setActiveScenario(null);
    }
  };

  // Show transaction list with detail
  if (selected) {
    return (
      <>
        <div className="page-header">
          <h2>Transaction Detail</h2>
          <p>Complete processing record — normalization, benchmarking, FWA, TPA Core decision, HIS delivery</p>
        </div>
        <div className="page-body">
          <button className="back-link" onClick={() => { setSelected(null); refresh(); }}>← Back to Transactions</button>
          <TxnDetailPanel txn={selected} onClose={() => { setSelected(null); refresh(); }} />
        </div>
      </>
    );
  }

  return (
    <>
      <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h2>HIS Transaction Simulation</h2>
          <p>Simulates automated transactions sent from connected Hospital HIS systems to the Central API Hub.</p>
        </div>
        <div style={{ display: 'flex', gap: '12px' }}>
          <button className="btn btn-secondary" onClick={exportToCSV} disabled={list.length === 0} style={{ flexShrink: 0, whiteSpace: 'nowrap' }}>
            ⭳ Export CSV
          </button>
          <button className="btn btn-secondary" onClick={handleReset} disabled={resetting} style={{ flexShrink: 0, whiteSpace: 'nowrap' }}>
            {resetting ? <><div className="spinner" style={{ width: 12, height: 12, borderWidth: 2 }} />Resetting…</> : '↺ Reset Demo'}
          </button>
        </div>
      </div>
      <div className="page-body">

        {resetMsg && <div className="alert alert-success" style={{ marginBottom: 16 }}>{resetMsg}</div>}
        {submitError && <div className="alert alert-error" style={{ marginBottom: 16 }}>{submitError}</div>}

        {/* HIS Transaction Tester */}
        <HISTransactionTester onResult={(txn) => {
          setResultTxn(txn);
          setSimulatingStages(getCompletedStages(txn.integration_events));
          refresh();
        }} />



        {/* Result panel */}
        {resultTxn && (
          <div>
            <div style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              marginBottom: 16, padding: '12px 16px',
              background: 'var(--bg-surface)', borderRadius: 'var(--radius)', border: '1px solid var(--border)',
            }}>
              <div>
                <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>Transaction complete — </span>
                <span className="td-code">{resultTxn.transaction_id}</span>
              </div>
              <div style={{ display: 'flex', gap: 10 }}>
                <StatusBadge value={resultTxn.status} />
                <button className="btn btn-secondary btn-sm" onClick={() => setResultTxn(null)}>✕</button>
              </div>
            </div>
            <TxnDetailPanel txn={resultTxn} onClose={() => setResultTxn(null)} />
          </div>
        )}

        {/* Transaction list */}
        {loading ? (
          <div className="loading"><div className="spinner" />Loading transactions…</div>
        ) : (
          <div className="card">
            <div className="card-title">All Processed Transactions ({list.length})</div>
            {list.length === 0 ? (
              <div className="empty-state">
                <div className="empty-icon">📋</div>
                <p>No transactions yet. Run a scenario above to begin.</p>
              </div>
            ) : (
              <div className="table-wrapper">
                <table>
                  <thead>
                    <tr>
                      <th>Transaction ID</th>
                      <th>Hospital</th>
                      <th>Patient</th>
                      <th style={{ textAlign: 'right' }}>Submitted ({CURRENCY_SYMBOL})</th>
                      <th style={{ textAlign: 'center' }}>Status</th>
                      <th style={{ textAlign: 'right' }}>Received At</th>
                    </tr>
                  </thead>
                  <tbody>
                    {list.map(t => (
                      <tr key={t.id} className="clickable" onClick={() => openDetail(t.transaction_id)}>
                        <td><span className="td-code" style={{ display: 'inline-block', marginTop: 8 }}>{t.transaction_id}</span></td>
                        <td>
                          <div style={{ fontWeight: 500 }}>{t.hospital_name}</div>
                          <div className="td-small">{t.hospital_code}</div>
                        </td>
                        <td className="td-muted">{t.patient_reference}</td>
                        <td style={{ fontVariantNumeric: 'tabular-nums', textAlign: 'right', fontWeight: 600 }}>{CURRENCY_SYMBOL} {fmt(t.submitted_amount)}</td>
                        <td style={{ textAlign: 'center' }}><StatusBadge value={t.status} /></td>
                        <td className="td-small" style={{ textAlign: 'right' }}>{new Date(t.created_at).toLocaleString('en-GB')}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </div>
    </>
  );
};
