import React, { useEffect, useState } from 'react';
import { api, Transaction, TransactionListItem } from '../api/client';
import { StatusBadge } from '../components/StatusBadge';
import { CURRENCY_SYMBOL, CURRENCY_LOCALE } from '../config';

function fmt(n: number) {
  return new Intl.NumberFormat(CURRENCY_LOCALE, { minimumFractionDigits: 2 }).format(n);
}

export const Adjudication: React.FC = () => {
  const [list, setList] = useState<TransactionListItem[]>([]);
  const [selected, setSelected] = useState<Transaction | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.getTransactions().then(t => {
      setList(t.filter(tx => tx.status.startsWith('ADJUDICATED')));
    }).finally(() => setLoading(false));
  }, []);

  const open = (id: string) => {
    api.getTransaction(id).then(setSelected);
  };

  return (
    <>
      <div className="page-header">
        <h2>Adjudication</h2>
        <p>TPA decisions and HIS delivery status for all adjudicated claims</p>
      </div>
      <div className="page-body">

        {loading ? (
          <div className="loading"><div className="spinner" />Loading...</div>
        ) : (
          <div className="card" style={{ marginBottom: 24 }}>
            <div className="card-title">Adjudicated Transactions ({list.length})</div>
            {list.length === 0 ? (
              <div className="empty-state">
                <div className="empty-icon">⚖️</div>
                <p>No adjudicated transactions yet.</p>
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
                      <th>TPA Decision</th>
                      <th>Submitted At</th>
                    </tr>
                  </thead>
                  <tbody>
                    {list.map(t => (
                      <tr key={t.id} className="clickable" onClick={() => open(t.transaction_id)}>
                        <td><span className="td-code">{t.transaction_id}</span></td>
                        <td>{t.hospital_name}</td>
                        <td className="td-muted">{t.patient_reference}</td>
                        <td>{fmt(t.submitted_amount)}</td>
                        <td><StatusBadge value={t.status} /></td>
                        <td className="td-small">{new Date(t.created_at).toLocaleString('en-GB')}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {selected && selected.adjudication && (
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 16, fontWeight: 700, color: 'var(--text-code)' }}>
                {selected.transaction_id}
              </div>
              <button className="btn btn-secondary btn-sm" onClick={() => setSelected(null)}>✕ Close</button>
            </div>

            <div className="three-col">
              {/* Transaction summary */}
              <div className="card">
                <div className="card-title">Transaction</div>
                <div className="kv-list">
                  <div className="kv-row"><span className="kv-key">Hospital</span><span className="kv-val">{selected.hospital.hospital_name}</span></div>
                  <div className="kv-row"><span className="kv-key">Code</span><span className="kv-val mono">{selected.hospital.hospital_code}</span></div>
                  <div className="kv-row"><span className="kv-key">Patient</span><span className="kv-val">{selected.patient_reference}</span></div>
                  <div className="kv-row"><span className="kv-key">Submitted</span><span className="kv-val">{CURRENCY_SYMBOL} {fmt(selected.submitted_amount)}</span></div>
                  <div className="kv-row"><span className="kv-key">Normalized</span><span className="kv-val">{CURRENCY_SYMBOL} {fmt(selected.normalized_amount)}</span></div>
                  <div className="kv-row"><span className="kv-key">Items</span><span className="kv-val">{selected.items.length}</span></div>
                </div>
              </div>

              {/* FWA Summary */}
              <div className="card">
                <div className="card-title">FWA Result</div>
                <div className="kv-list">
                  {selected.fwa_results.map(r => (
                    <div key={r.id} className="kv-row">
                      <span className="kv-key">{r.rule_name}</span>
                      <span className="kv-val"><StatusBadge value={r.result} /></span>
                    </div>
                  ))}
                </div>
                <div style={{ marginTop: 12 }}>
                  {selected.fwa_results.some(r => r.result !== 'PASS') ? (
                    <div className="alert alert-error" style={{ margin: 0, fontSize: 12 }}>
                      FWA flags detected — claim requires review
                    </div>
                  ) : (
                    <div className="alert alert-success" style={{ margin: 0, fontSize: 12 }}>
                      All FWA rules passed
                    </div>
                  )}
                </div>
              </div>

              {/* TPA Decision */}
              <div className="card" style={{
                borderColor: 'var(--border)',
              }}>
                <div className="card-title">TPA Decision</div>
                <div style={{ textAlign: 'center', padding: '16px 0' }}>
                  <div style={{
                    fontSize: 28,
                    fontWeight: 900,
                    letterSpacing: '0.04em',
                    color: selected.adjudication.status === 'APPROVED'
                      ? 'var(--green)'
                      : selected.adjudication.status === 'REJECTED'
                      ? 'var(--red)'
                      : 'var(--yellow)',
                    marginBottom: 8,
                  }}>
                    {selected.adjudication.status}
                  </div>
                  <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text-primary)' }}>
                    {CURRENCY_SYMBOL} {fmt(selected.adjudication.approved_amount)}
                  </div>
                  {selected.adjudication.reference && (
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', marginTop: 6 }}>
                      Ref: {selected.adjudication.reference}
                    </div>
                  )}
                </div>
                {selected.adjudication.reason && (
                  <div style={{ fontSize: 12, color: 'var(--text-secondary)', padding: '8px 10px', background: 'var(--yellow-bg)', borderRadius: 6, marginTop: 4 }}>
                    {selected.adjudication.reason}
                  </div>
                )}
                <div className="kv-row" style={{ marginTop: 12 }}>
                  <span className="kv-key">HIS Delivery</span>
                  <StatusBadge value={selected.adjudication.his_delivery_status || 'PENDING'} />
                </div>
              </div>
            </div>

            {/* Items */}
            <div style={{ marginTop: 20 }}>
              <div className="section-title">Claim Line Items</div>
              <div className="table-wrapper">
                <table>
                  <thead>
                    <tr>
                      <th>Hospital Code</th>
                      <th>Common Code</th>
                      <th>Description</th>
                      <th>Qty</th>
                      <th>Submitted</th>
                      <th>Benchmark</th>
                      <th>Allowed Max</th>
                      <th>Variance</th>
                      <th>Benchmark Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {selected.items.map(item => (
                      <tr key={item.id}>
                        <td><span className="td-code">{item.hospital_code}</span></td>
                        <td><span className="common-code-group" style={{ fontSize: 11 }}>{item.common_code}</span></td>
                        <td className="td-muted">{item.description}</td>
                        <td>{item.quantity}</td>
                        <td>{CURRENCY_SYMBOL} {item.unit_price.toFixed(2)}</td>
                        <td>{item.benchmark_price ? `${CURRENCY_SYMBOL} ${item.benchmark_price.toFixed(2)}` : '—'}</td>
                        <td>{item.allowed_maximum ? `${CURRENCY_SYMBOL} ${item.allowed_maximum.toFixed(2)}` : '—'}</td>
                        <td style={{ color: (item.variance_percent || 0) > 20 ? 'var(--red)' : (item.variance_percent || 0) > 0 ? 'var(--yellow)' : 'var(--green)' }}>
                          {item.variance_percent != null ? `${item.variance_percent > 0 ? '+' : ''}${item.variance_percent.toFixed(1)}%` : '—'}
                        </td>
                        <td><StatusBadge value={item.benchmark_status || 'NO_BENCHMARK'} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}
      </div>
    </>
  );
};
