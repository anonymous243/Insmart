import React, { useEffect, useState } from 'react';
import { api, Transaction, TransactionListItem } from '../api/client';
import { StatusBadge } from '../components/StatusBadge';
import { CURRENCY_SYMBOL, CURRENCY_LOCALE } from '../config';

function fmt(n: number) {
  return new Intl.NumberFormat(CURRENCY_LOCALE, { minimumFractionDigits: 2 }).format(n);
}

export const FWABenchmark: React.FC = () => {
  const [list, setList] = useState<TransactionListItem[]>([]);
  const [selected, setSelected] = useState<Transaction | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.getTransactions().then(res => setList(res.items)).finally(() => setLoading(false));
  }, []);

  const open = (id: string) => {
    api.getTransaction(id).then(setSelected);
  };

  // Only show transactions that have FWA flags or price issues
  const flagged = list.filter(t =>
    t.status.includes('REVIEW') || t.status.includes('REJECT') || t.status.includes('FWA')
  );

  return (
    <>
      <div className="page-header">
        <h2>FWA &amp; Benchmark Analysis</h2>
        <p>Fraud, Waste &amp; Abuse engine results and price benchmark analysis</p>
      </div>
      <div className="page-body">

        <div className="two-col" style={{ marginBottom: 24 }}>
          <div className="card">
            <div className="card-title">FWA Rules Active</div>
            {[
              { code: 'FWA-001', name: 'Duplicate Service', type: 'DUPLICATE', action: 'FWA_FLAG', sev: 'HIGH' },
              { code: 'FWA-002', name: 'Frequency Check', type: 'FREQUENCY', action: 'FWA_REVIEW', sev: 'MEDIUM' },
              { code: 'FWA-003', name: 'Price Anomaly', type: 'PRICE', action: 'PRICE_FLAG', sev: 'MEDIUM' },
              { code: 'FWA-004', name: 'Unusual Quantity', type: 'QUANTITY', action: 'FWA_REVIEW', sev: 'MEDIUM' },
              { code: 'FWA-005', name: 'Unusual Same-Day Combination', type: 'COMBINATION', action: 'FWA_REVIEW', sev: 'MEDIUM' },
            ].map(rule => (
              <div key={rule.code} style={{ padding: '10px 0', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  <span className="tag" style={{ marginRight: 8 }}>{rule.code}</span>
                  <span style={{ fontWeight: 600, fontSize: 13 }}>{rule.name}</span>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 3 }}>Type: {rule.type}</div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <StatusBadge value={rule.action} />
                  <div style={{ fontSize: 11, color: rule.sev === 'HIGH' ? 'var(--red)' : 'var(--yellow)', marginTop: 3 }}>{rule.sev}</div>
                </div>
              </div>
            ))}
          </div>

          <div className="card">
            <div className="card-title">Benchmark Reference</div>
            {[
              { code: 'CONS-CARD', name: 'Cardiology Consultation', bench: 750, variance: 20 },
              { code: 'LAB-CBC', name: 'Complete Blood Count', bench: 300, variance: 15 },
              { code: 'XR-CHEST', name: 'Chest X-Ray', bench: 500, variance: 20 },
            ].map(b => (
              <div key={b.code} style={{ padding: '10px 0', borderBottom: '1px solid var(--border)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                  <span className="common-code-group" style={{ fontSize: 11 }}>{b.code}</span>
                  <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>±{b.variance}%</span>
                </div>
                <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginBottom: 6 }}>{b.name}</div>
                <div style={{ display: 'flex', gap: 16, fontSize: 12 }}>
                  <span>Benchmark: <strong style={{ color: 'var(--text-primary)' }}>{CURRENCY_SYMBOL} {b.bench}</strong></span>
                  <span>Max: <strong style={{ color: 'var(--green)' }}>{CURRENCY_SYMBOL} {(b.bench * (1 + b.variance / 100)).toFixed(0)}</strong></span>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="card" style={{ marginBottom: 20 }}>
          <div className="card-title">Flagged &amp; Under Review Transactions</div>
          {loading ? (
            <div className="loading"><div className="spinner" />Loading...</div>
          ) : flagged.length === 0 ? (
            <div className="empty-state">
              <div className="empty-icon">✅</div>
              <p>No flagged transactions. All claims are within benchmark.</p>
            </div>
          ) : (
            <div className="table-wrapper">
              <table>
                <thead>
                  <tr>
                    <th>Transaction</th>
                    <th>Hospital</th>
                    <th>Patient</th>
                    <th>Submitted ({CURRENCY_SYMBOL})</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {flagged.map(t => (
                    <tr key={t.id} className="clickable" onClick={() => open(t.transaction_id)}>
                      <td><span className="td-code">{t.transaction_id}</span></td>
                      <td>{t.hospital_name}</td>
                      <td className="td-muted">{t.patient_reference}</td>
                      <td>{fmt(t.submitted_amount)}</td>
                      <td><StatusBadge value={t.status} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Transaction FWA Detail */}
        {selected && (
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
              <div className="section-title" style={{ margin: 0 }}>
                FWA Detail — {selected.transaction_id}
              </div>
              <button className="btn btn-secondary btn-sm" onClick={() => setSelected(null)}>✕ Close</button>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {selected.items.map(item => (
                <div key={item.id} className="card" style={{
                  borderColor: item.benchmark_status === 'REVIEW' ? 'var(--border-light)' : 'var(--border)',
                }}>
                  <div style={{ fontWeight: 700, marginBottom: 12, fontSize: 14, display: 'flex', justifyContent: 'space-between' }}>
                    <div className="norm-arrow">
                      <span className="norm-from">{item.hospital_code}</span>
                      <span className="norm-sep">→</span>
                      <span className="norm-to">{item.common_code}</span>
                    </div>
                    <StatusBadge value={item.benchmark_status || 'NO_BENCHMARK'} />
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 16, marginBottom: 12 }}>
                    {[
                      { label: 'Submitted', value: `${CURRENCY_SYMBOL} ${item.unit_price.toFixed(2)}`, color: 'var(--text-primary)' },
                      { label: 'Benchmark', value: item.benchmark_price ? `${CURRENCY_SYMBOL} ${item.benchmark_price.toFixed(2)}` : '—', color: 'var(--text-secondary)' },
                      { label: 'Allowed Max', value: item.allowed_maximum ? `${CURRENCY_SYMBOL} ${item.allowed_maximum.toFixed(2)}` : '—', color: 'var(--green)' },
                      { label: 'Variance', value: item.variance_percent != null ? `${item.variance_percent > 0 ? '+' : ''}${item.variance_percent.toFixed(1)}%` : '—', color: (item.variance_percent || 0) > 20 ? 'var(--red)' : 'var(--yellow)' },
                    ].map(f => (
                      <div key={f.label}>
                        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.06em' }}>{f.label}</div>
                        <div style={{ fontSize: 18, fontWeight: 700, color: f.color }}>{f.value}</div>
                      </div>
                    ))}
                  </div>
                  {item.benchmark_price && item.allowed_maximum && (
                    <div className="benchmark-bar-wrap">
                      <div className="benchmark-bar" style={{ height: 10 }}>
                        <div
                          className={`benchmark-bar-fill ${item.benchmark_status?.toLowerCase() || 'pass'}`}
                          style={{ width: `${Math.min(100, (item.unit_price / (item.allowed_maximum * 1.2)) * 100)}%` }}
                        />
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
                        <span>{CURRENCY_SYMBOL} 0</span>
                        <span style={{ color: 'var(--green)' }}>Max {CURRENCY_SYMBOL} {item.allowed_maximum.toFixed(0)}</span>
                        <span>{CURRENCY_SYMBOL} {(item.allowed_maximum * 1.2).toFixed(0)}</span>
                      </div>
                    </div>
                  )}
                </div>
              ))}

              <div className="card">
                <div className="card-title">FWA Rule Results</div>
                {selected.fwa_results.map(r => (
                  <div key={r.id} style={{ padding: '10px 0', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                    <div>
                      <span className="tag" style={{ marginRight: 8 }}>{r.rule_code}</span>
                      <span style={{ fontWeight: 600 }}>{r.rule_name}</span>
                      {r.reason && <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 4, maxWidth: 500 }}>{r.reason}</div>}
                    </div>
                    <StatusBadge value={r.result} />
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </>
  );
};
