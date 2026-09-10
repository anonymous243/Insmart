import React, { useEffect, useState } from 'react';
import { fetchWithAuth } from '../../api/auth';
import { useAuth } from '../../context/AuthContext';

export const Account: React.FC = () => {
  const { user } = useAuth();
  const [me, setMe] = useState<any>(null);

  useEffect(() => {
    fetchWithAuth('/auth/me').then(setMe).catch(console.error);
  }, []);

  return (
    <div>
      <h2 style={{ marginBottom: 24, fontSize: 24, fontWeight: 'bold' }}>Facility Account</h2>
      
      {me && (
        <div style={{ background: 'white', padding: 24, borderRadius: 8, boxShadow: '0 1px 3px rgba(0,0,0,0.1)', maxWidth: 600 }}>
          <div style={{ marginBottom: 16 }}>
            <label style={{ color: 'var(--text-secondary)', fontSize: 12, textTransform: 'uppercase', letterSpacing: '0.05em' }}>User Email</label>
            <div style={{ fontSize: 16, fontWeight: 500 }}>{me.email}</div>
          </div>
          
          <div style={{ marginBottom: 16 }}>
            <label style={{ color: 'var(--text-secondary)', fontSize: 12, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Facility Code</label>
            <div style={{ fontSize: 16, fontWeight: 500 }}>{me.facility?.code}</div>
          </div>

          <div style={{ marginBottom: 16 }}>
            <label style={{ color: 'var(--text-secondary)', fontSize: 12, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Facility Name</label>
            <div style={{ fontSize: 16, fontWeight: 500 }}>{me.facility?.name}</div>
          </div>

          <div style={{ marginBottom: 16 }}>
            <label style={{ color: 'var(--text-secondary)', fontSize: 12, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Role</label>
            <div style={{ fontSize: 16, fontWeight: 500 }}>{me.role}</div>
          </div>
        </div>
      )}
    </div>
  );
};
