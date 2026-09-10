import React, { useEffect, useState } from 'react';
import { api, IntegrationEvent } from '../api/client';
import { StatusBadge } from '../components/StatusBadge';

export const AuditLogs: React.FC = () => {
  const [logs, setLogs] = useState<IntegrationEvent[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.getAuditLogs()
      .then(setLogs)
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="loading">Loading audit logs...</div>;

  return (
    <div className="page-container">
      <header className="page-header">
        <div>
          <h2>Compliance & Audit Logs</h2>
          <p>Immutable record of all system integrations and actions.</p>
        </div>
      </header>

      <div className="card">
        <table className="data-table">
          <thead>
            <tr>
              <th>Timestamp</th>
              <th>Transaction ID</th>
              <th>Event Type</th>
              <th>Source</th>
              <th>Status</th>
              <th>Payload Summary</th>
            </tr>
          </thead>
          <tbody>
            {logs.map((log) => (
              <tr key={log.id}>
                <td className="mono">{new Date(log.created_at).toLocaleString()}</td>
                <td className="mono" style={{ color: 'var(--accent)' }}>
                  {/* Note: In this quick iteration, we just show the transaction DB id for simplicity 
                      Wait, the backend returns transaction_id as the string ID from the join! */}
                  {log.transaction_id || '-'}
                </td>
                <td style={{ fontWeight: 500 }}>{log.event_type}</td>
                <td>{log.source || '-'}</td>
                <td>
                  {log.status ? <StatusBadge value={log.status} /> : '-'}
                </td>
                <td style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>
                  {log.payload ? JSON.stringify(log.payload).substring(0, 50) + '...' : '-'}
                </td>
              </tr>
            ))}
            {logs.length === 0 && (
              <tr>
                <td colSpan={6} style={{ textAlign: 'center', padding: '32px', color: 'var(--text-muted)' }}>
                  No audit logs found.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};
