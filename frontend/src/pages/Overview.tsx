import React, { useEffect, useState } from 'react';
import { api, DashboardMetrics, TransactionListItem } from '../api/client';
import { StatusBadge } from '../components/StatusBadge';
import { CURRENCY_SYMBOL, CURRENCY_LOCALE, IS_PROTOTYPE } from '../config';
import { useAuth } from '../context/AuthContext';

function fmt(n: number) {
  return new Intl.NumberFormat(CURRENCY_LOCALE, { minimumFractionDigits: 2 }).format(n);
}



export const Overview: React.FC = () => {
  const [metrics, setMetrics] = useState<DashboardMetrics | null>(null);
  const [txns, setTxns] = useState<TransactionListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const { logout } = useAuth();

  useEffect(() => {
    Promise.all([api.getDashboardMetrics(), api.getTransactions()])
      .then(([m, t]) => { setMetrics(m); setTxns(t.items.slice(0, 8)); })
      .catch((err: any) => {
        setError(err.message || 'Failed to load dashboard data');
        if (err.message && (err.message.toLowerCase().includes('unauthorized') || err.message.toLowerCase().includes('expired'))) {
          logout();
        }
      })
      .finally(() => setLoading(false));
  }, [logout]);

  if (loading) return <div className="loading"><div className="spinner" />Loading dashboard...</div>;
  if (error) return <div className="alert alert-error" style={{ margin: 24 }}>{error}</div>;

  return (
    <>
      <div className="page-header">
        <h2>Central Platform Operations Console</h2>
        <p>
          Visibility into all claim transactions flowing through the central integration hub.
          {IS_PROTOTYPE && <span style={{ marginLeft: 10, fontSize: 11, color: 'var(--text-muted)', background: 'var(--bg-surface)', padding: '2px 8px', borderRadius: 10, border: '1px solid var(--border)' }}>PROTOTYPE — REPRESENTATIVE DATA</span>}
        </p>
      </div>
      <div className="page-body">

        {/* Metrics */}
        <div className="metrics-grid" style={{ marginBottom: 24 }}>
          <div className="metric-card blue">
            <div className="metric-label">Connected Hospitals</div>
            <div className="metric-value">{metrics?.connected_hospitals ?? 0}</div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>Via existing HIS API</div>
          </div>
          <div className="metric-card purple">
            <div className="metric-label">Transactions</div>
            <div className="metric-value">{metrics?.total_transactions ?? 0}</div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>Auto-processed</div>
          </div>
          <div className="metric-card green">
            <div className="metric-label">Approved</div>
            <div className="metric-value">{metrics?.approved ?? 0}</div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>Within benchmark, FWA clear</div>
          </div>
          <div className="metric-card yellow">
            <div className="metric-label">Under Review</div>
            <div className="metric-value">{metrics?.review ?? 0}</div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>Price or frequency flag</div>
          </div>
          <div className="metric-card orange">
            <div className="metric-label">FWA Flagged</div>
            <div className="metric-value">{metrics?.fwa_flagged ?? 0}</div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>Triggered FWA rules</div>
          </div>
          <div className="metric-card red">
            <div className="metric-label">Rejected</div>
            <div className="metric-value">{metrics?.rejected ?? 0}</div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>High-severity flags</div>
          </div>
        </div>

        {/* Recent Transactions */}
        <div className="card">
          <div className="card-title">Recent Transactions</div>
          {txns.length === 0 ? (
            <div className="empty-state">
              <div className="empty-icon">📋</div>
              <p>No transactions yet. Use the HIS Simulation tool to submit transactions.</p>
            </div>
          ) : (
            <div className="table-wrapper">
              <table>
                <thead>
                  <tr>
                    <th>Transaction ID</th>
                    <th>Hospital</th>
                    <th>Patient Ref</th>
                    <th>Submitted ({CURRENCY_SYMBOL})</th>
                    <th>Status</th>
                    <th>Received</th>
                  </tr>
                </thead>
                <tbody>
                  {txns.map(t => (
                    <tr key={t.id}>
                      <td><span className="td-code">{t.transaction_id}</span></td>
                      <td>
                        <div style={{ fontWeight: 500 }}>{t.hospital_name}</div>
                        <div className="td-small">{t.hospital_code}</div>
                      </td>
                      <td className="td-muted">{t.patient_reference}</td>
                      <td style={{ fontVariantNumeric: 'tabular-nums' }}>{CURRENCY_SYMBOL} {fmt(t.submitted_amount)}</td>
                      <td><StatusBadge value={t.status} /></td>
                      <td className="td-small">{new Date(t.created_at).toLocaleString('en-GB')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

      </div>
    </>
  );
};
