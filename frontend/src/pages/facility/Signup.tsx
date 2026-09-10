import React, { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { fetchWithAuth } from '../../api/auth';
import { PLATFORM_NAME } from '../../config';

export const Signup: React.FC = () => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [facilityName, setFacilityName] = useState('');
  const [facilityCode, setFacilityCode] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(false);
  const navigate = useNavigate();

  const handleSignup = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    try {
      await fetchWithAuth('/auth/signup', {
        method: 'POST',
        body: JSON.stringify({ email, password, facility_name: facilityName, facility_code: facilityCode }),
      });
      setSuccess(true);
      setTimeout(() => navigate('/login'), 2000);
    } catch (err: any) {
      setError(err.message);
    }
  };

  return (
    <div style={{ display: 'flex', height: '100vh', alignItems: 'center', justifyContent: 'center', background: 'var(--bg-base)' }}>
      <div style={{ background: 'white', padding: 40, borderRadius: 8, width: 450, boxShadow: '0 4px 12px rgba(0,0,0,0.1)' }}>
        <h2 style={{ textAlign: 'center', marginBottom: 8, color: 'var(--accent)' }}>{PLATFORM_NAME}</h2>
        <p style={{ textAlign: 'center', marginBottom: 24, color: 'var(--text-secondary)' }}>Register Facility</p>
        
        {error && <div style={{ color: 'red', marginBottom: 16, fontSize: 14 }}>{error}</div>}
        {success && <div style={{ color: 'green', marginBottom: 16, fontSize: 14 }}>Registration successful! Redirecting...</div>}
        
        <form onSubmit={handleSignup}>
          <div style={{ marginBottom: 16 }}>
            <label style={{ display: 'block', marginBottom: 8, fontSize: 14, fontWeight: 500 }}>Facility Name</label>
            <input value={facilityName} onChange={e => setFacilityName(e.target.value)} required style={{ width: '100%', padding: '10px', borderRadius: 4, border: '1px solid var(--border)' }} />
          </div>
          <div style={{ marginBottom: 16 }}>
            <label style={{ display: 'block', marginBottom: 8, fontSize: 14, fontWeight: 500 }}>Facility Code</label>
            <input value={facilityCode} onChange={e => setFacilityCode(e.target.value)} required style={{ width: '100%', padding: '10px', borderRadius: 4, border: '1px solid var(--border)' }} />
          </div>
          <div style={{ marginBottom: 16 }}>
            <label style={{ display: 'block', marginBottom: 8, fontSize: 14, fontWeight: 500 }}>Admin Email</label>
            <input type="email" value={email} onChange={e => setEmail(e.target.value)} required style={{ width: '100%', padding: '10px', borderRadius: 4, border: '1px solid var(--border)' }} />
          </div>
          <div style={{ marginBottom: 24 }}>
            <label style={{ display: 'block', marginBottom: 8, fontSize: 14, fontWeight: 500 }}>Password</label>
            <input type="password" value={password} onChange={e => setPassword(e.target.value)} required style={{ width: '100%', padding: '10px', borderRadius: 4, border: '1px solid var(--border)' }} />
          </div>
          <button type="submit" style={{ width: '100%', padding: '12px', background: 'var(--accent)', color: 'white', border: 'none', borderRadius: 4, fontWeight: 'bold', cursor: 'pointer' }}>
            Register
          </button>
        </form>
        <div style={{ marginTop: 16, textAlign: 'center', fontSize: 14 }}>
          Already have an account? <Link to="/login" style={{ color: 'var(--accent)' }}>Login</Link>
        </div>
      </div>
    </div>
  );
};
