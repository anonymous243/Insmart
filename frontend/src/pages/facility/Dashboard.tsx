import React, { useEffect, useState } from 'react';
import { fetchWithAuth } from '../../api/auth';

export const Dashboard: React.FC = () => {
  const [alerts, setAlerts] = useState<any[]>([]);

  useEffect(() => {
    fetchWithAuth('/facility/alerts').then(setAlerts).catch(console.error);
  }, []);

  return (
    <div>
      <h2 style={{ marginBottom: 24, fontSize: 24, fontWeight: 'bold' }}>Facility Dashboard</h2>
      
      <div style={{ background: 'white', padding: 24, borderRadius: 8, boxShadow: '0 1px 3px rgba(0,0,0,0.1)' }}>
        <h3 style={{ marginBottom: 16 }}>Recent Adjudication Alerts</h3>
        {alerts.length === 0 ? (
          <p style={{ color: 'var(--text-secondary)' }}>No recent alerts.</p>
        ) : (
          <ul style={{ listStyle: 'none', padding: 0 }}>
            {alerts.map(a => (
              <li key={a.id} style={{ 
                padding: '20px', 
                marginBottom: '16px',
                background: '#f8f9fa',
                border: '1px solid var(--border)',
                borderRadius: '8px'
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
                  <div>
                    <h4 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: 'var(--text-primary)' }}>
                      {a.transaction_id}
                    </h4>
                    <div style={{ color: 'var(--text-secondary)', fontSize: 13, marginTop: 4 }}>
                      Received {new Date(a.created_at).toLocaleString()}
                    </div>
                  </div>
                  {a.status && (
                    <span className={`status-badge ${a.status.toLowerCase()}`}>
                      {a.status}
                    </span>
                  )}
                </div>
                
                {a.payload && a.payload.delivery_status && (
                  <div style={{ 
                    display: 'flex', 
                    alignItems: 'center',
                    fontSize: 14, 
                    background: 'white', 
                    padding: '12px 16px', 
                    borderRadius: 6,
                    border: '1px solid var(--border)'
                  }}>
                    <span style={{ color: 'var(--text-secondary)', marginRight: 8 }}>Delivery Status:</span>
                    <span style={{ 
                      color: a.payload.delivery_status === 'DELIVERED' ? 'var(--success)' : 'var(--error)',
                      fontWeight: 600,
                      letterSpacing: '0.5px',
                      fontSize: 13
                    }}>
                      {a.payload.delivery_status}
                    </span>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
};
