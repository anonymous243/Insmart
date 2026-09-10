import React from 'react';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { PLATFORM_NAME } from '../config';

const NAV_ITEMS = [
  { id: 'dashboard', label: 'Dashboard', icon: '◈', path: '/facility' },
  { id: 'new', label: 'New Submission', icon: '＋', path: '/facility/new' },
  { id: 'history', label: 'History', icon: '◷', path: '/facility/history' },
  { id: 'account', label: 'Account', icon: '⚙', path: '/facility/account' },
];

export const FacilityLayout: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { user, logout } = useAuth();

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  return (
    <div className="app-layout">
      <aside className="sidebar" style={{ background: 'var(--bg-secondary)', borderRight: '1px solid var(--border)' }}>
        <div className="sidebar-logo">
          <h1>{PLATFORM_NAME}</h1>
          <p>Facility Portal</p>
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
          <div style={{ fontSize: 13, fontWeight: 500, marginBottom: 4 }}>
            {user?.email}
          </div>
          <button 
            onClick={handleLogout}
            style={{ 
              background: 'transparent', 
              border: '1px solid var(--border)', 
              color: 'var(--text-secondary)',
              padding: '6px 12px',
              borderRadius: '4px',
              cursor: 'pointer',
              width: '100%',
              fontSize: 12
            }}
          >
            Log Out
          </button>
        </div>
      </aside>

      <main className="main-content">
        <Outlet />
      </main>
    </div>
  );
};
