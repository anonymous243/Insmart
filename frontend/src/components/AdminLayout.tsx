import React, { useState } from 'react';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import { PLATFORM_NAME, PLATFORM_TAGLINE, IS_PROTOTYPE } from '../config';

type Page = 'overview' | 'codes' | 'transactions' | 'fwa' | 'adjudication' | 'audit';

const NAV_ITEMS: { id: Page; label: string; icon: string; path: string }[] = [
  { id: 'overview', label: 'Overview', icon: '◈', path: '/admin' },
  { id: 'codes', label: 'Code Master', icon: '⊞', path: '/admin/codes' },
  { id: 'transactions', label: 'HIS Simulation', icon: '⇅', path: '/admin/transactions' },
  { id: 'fwa', label: 'FWA & Benchmark', icon: '⚑', path: '/admin/fwa' },
  { id: 'adjudication', label: 'Adjudication', icon: '⚖', path: '/admin/adjudication' },
  { id: 'audit', label: 'Audit Logs', icon: '◷', path: '/admin/audit' },
];

export const AdminLayout: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();

  return (
    <div className="app-layout">
      <aside className="sidebar">
        <div className="sidebar-logo">
          <h1>{PLATFORM_NAME}</h1>
          <p>{PLATFORM_TAGLINE} (Admin)</p>
        </div>

        <nav className="sidebar-nav">
          {NAV_ITEMS.map(item => (
            <button
              key={item.id}
              className={`nav-item ${location.pathname === item.path ? 'active' : ''}`}
              onClick={() => navigate(item.path)}
            >
              <span className="nav-icon">{item.icon}</span>
              {item.label}
            </button>
          ))}

          <div style={{ flex: 1 }} />
        </nav>

        <div className="sidebar-footer">
          <div className="system-status">
            <div className="status-dot" />
            <span>All systems operational</span>
          </div>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 6 }}>
            API · TPA Core · HIS Callbacks
          </div>
          {IS_PROTOTYPE && (
            <div style={{ fontSize: 10, color: 'var(--accent)', marginTop: 6, fontWeight: 'bold' }}>
              PROTOTYPE
            </div>
          )}
        </div>
      </aside>

      <main className="main-content">
        {IS_PROTOTYPE && (
          <div style={{
            background: 'var(--accent)',
            color: 'white',
            padding: '8px 16px',
            fontSize: '13px',
            textAlign: 'center',
            fontWeight: 500,
            marginBottom: '16px',
            borderRadius: '4px'
          }}>
            SYNTHETIC DATASET: This environment contains only mock, synthetic Vietnam healthcare data generated for demonstration purposes.
          </div>
        )}
        <Outlet />
      </main>
    </div>
  );
};
