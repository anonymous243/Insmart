import React, { useEffect, useState } from 'react';
import { fetchWithAuth } from '../../api/auth';

export const History: React.FC = () => {
  const [history, setHistory] = useState<any[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);

  const loadHistory = (cursor?: string) => {
    setLoading(true);
    const url = cursor ? `/facility/history?cursor=${cursor}` : '/facility/history';
    fetchWithAuth(url)
      .then(res => {
        if (cursor) {
          setHistory(prev => [...prev, ...res.items]);
        } else {
          setHistory(res.items);
        }
        setNextCursor(res.next_cursor);
        setHasMore(res.has_more);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadHistory();
  }, []);

  return (
    <div>
      <h2 style={{ marginBottom: 24, fontSize: 24, fontWeight: 'bold' }}>Transaction History</h2>
      
      <div className="table-container">
        <table>
          <thead>
            <tr>
              <th style={{ width: '15%' }}>ID</th>
              <th style={{ width: '20%' }}>Patient Ref</th>
              <th style={{ width: '15%', textAlign: 'right' }}>Amount</th>
              <th style={{ width: '25%', textAlign: 'center' }}>Status</th>
              <th style={{ width: '25%', textAlign: 'right' }}>Date</th>
            </tr>
          </thead>
          <tbody>
            {history.map(t => (
              <tr key={t.id}>
                <td className="td-code" style={{ display: 'inline-block', marginTop: 8 }}>{t.transaction_id}</td>
                <td className="td-muted">{t.patient_reference}</td>
                <td style={{ textAlign: 'right', fontWeight: 600 }}>₫{t.submitted_amount.toLocaleString()}</td>
                <td style={{ textAlign: 'center' }}>
                  <span className={`badge badge-${t.status.toLowerCase()}`}>
                    <span className="badge-dot"></span>
                    {t.status.replace('ADJUDICATED_', '').replace('_', ' ')}
                  </span>
                </td>
                <td style={{ textAlign: 'right' }} className="td-small">{new Date(t.created_at).toLocaleString()}</td>
              </tr>
            ))}
            {history.length === 0 && !loading && (
              <tr>
                <td colSpan={5} style={{ textAlign: 'center', padding: 24, color: 'var(--text-secondary)' }}>
                  No transactions found.
                </td>
              </tr>
            )}
          </tbody>
        </table>
        
        {hasMore && (
          <div style={{ textAlign: 'center', padding: '16px 0', borderTop: '1px solid var(--border)' }}>
            <button 
              onClick={() => loadHistory(nextCursor!)} 
              disabled={loading}
              className="btn btn-secondary"
            >
              {loading ? 'Loading...' : 'Load More'}
            </button>
          </div>
        )}
      </div>
    </div>
  );
};
