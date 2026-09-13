import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { fetchWithAuth } from '../../api/auth';
import { FacilityCode } from '../../api/client';

export const NewSubmission: React.FC = () => {
  const [patientRef, setPatientRef] = useState(`PAT-${Math.floor(Math.random() * 10000)}`);
  const [amount, setAmount] = useState<number | ''>('');
  const [selectedCode, setSelectedCode] = useState<FacilityCode | null>(null);
  const [codes, setCodes] = useState<FacilityCode[]>([]);
  const [codesLoading, setCodesLoading] = useState(true);
  const [codesError, setCodesError] = useState('');
  const [submitError, setSubmitError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const navigate = useNavigate();

  // Fetch facility codes from backend on mount
  useEffect(() => {
    fetchWithAuth('/facility/codes')
      .then((data: FacilityCode[]) => {
        const mapped = data.filter((c) => c.mapped);
        setCodes(mapped);
        if (mapped.length > 0) {
          setSelectedCode(mapped[0]);
        }
      })
      .catch((err: any) => {
        setCodesError(err.message || 'Failed to load facility codes');
      })
      .finally(() => setCodesLoading(false));
  }, []);

  const handleCodeChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const found = codes.find((c) => c.local_code === e.target.value) || null;
    setSelectedCode(found);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedCode) {
      setSubmitError('Please select a service code.');
      return;
    }
    if (amount === '' || Number(amount) <= 0) {
      setSubmitError('Please enter a valid submitted amount.');
      return;
    }
    setSubmitError('');
    setSubmitting(true);

    const payload = {
      transaction_id: `TXN-FAC-${Date.now()}`,
      hospital_id: 'DUMMY',  // Will be overridden server-side from JWT — not trusted, but needed for schema min_length=1
      patient_reference: patientRef,
      items: [
        {
          hospital_code: selectedCode.local_code,
          description: selectedCode.description,
          quantity: 1,
          unit_price: Number(amount),
        },
      ],
    };

    try {
      await fetchWithAuth('/transactions', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      navigate('/facility/history');
    } catch (err: any) {
      setSubmitError(err.message || 'Submission failed. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div>
      <h2 style={{ marginBottom: 24, fontSize: 24, fontWeight: 'bold' }}>New Claim Submission</h2>

      <div
        style={{
          background: 'white',
          padding: 28,
          borderRadius: 8,
          boxShadow: '0 1px 3px rgba(0,0,0,0.1)',
          maxWidth: 600,
        }}
      >
        {/* Codes loading state */}
        {codesLoading && (
          <div style={{ color: 'var(--text-secondary)', marginBottom: 16, fontSize: 14 }}>
            Loading your facility codes...
          </div>
        )}

        {/* No codes configured */}
        {!codesLoading && !codesError && codes.length === 0 && (
          <div
            style={{
              padding: '16px 20px',
              background: 'var(--bg-surface)',
              border: '1px solid var(--border)',
              borderRadius: 6,
              marginBottom: 20,
              fontSize: 14,
              color: 'var(--text-secondary)',
            }}
          >
            No facility service codes are configured yet. Please contact your administrator
            to register local codes before submitting claims.
          </div>
        )}

        {/* Codes load error */}
        {codesError && (
          <div style={{ color: 'red', marginBottom: 16, fontSize: 14 }}>
            Error loading codes: {codesError}
          </div>
        )}

        {/* Main form — only rendered when codes are available */}
        {!codesLoading && codes.length > 0 && (
          <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
            {/* Patient Reference */}
            <div>
              <label
                style={{
                  display: 'block',
                  marginBottom: 6,
                  fontSize: 13,
                  fontWeight: 600,
                  color: 'var(--text-secondary)',
                  textTransform: 'uppercase',
                  letterSpacing: '0.05em',
                }}
              >
                Patient Reference
              </label>
              <input
                value={patientRef}
                onChange={(e) => setPatientRef(e.target.value)}
                required
                style={{
                  width: '100%',
                  padding: '10px 12px',
                  borderRadius: 4,
                  border: '1px solid var(--border)',
                  fontSize: 14,
                  boxSizing: 'border-box',
                }}
              />
            </div>

            {/* Service Code Dropdown */}
            <div>
              <label
                style={{
                  display: 'block',
                  marginBottom: 6,
                  fontSize: 13,
                  fontWeight: 600,
                  color: 'var(--text-secondary)',
                  textTransform: 'uppercase',
                  letterSpacing: '0.05em',
                }}
              >
                Service Code (Facility Local Code)
              </label>
              <select
                value={selectedCode?.local_code || ''}
                onChange={handleCodeChange}
                required
                style={{
                  width: '100%',
                  padding: '10px 12px',
                  borderRadius: 4,
                  border: '1px solid var(--border)',
                  fontSize: 14,
                  background: 'white',
                  cursor: 'pointer',
                  boxSizing: 'border-box',
                }}
              >
                {codes.map((c) => (
                  <option key={c.local_code} value={c.local_code}>
                    {c.local_code} — {c.description}
                  </option>
                ))}
              </select>
            </div>

            {/* Normalization Preview */}
            {selectedCode && (
              <div
                style={{
                  padding: '14px 16px',
                  background: 'var(--bg-surface)',
                  border: '1px solid var(--border)',
                  borderRadius: 6,
                  fontSize: 13,
                }}
              >
                <div
                  style={{
                    fontSize: 11,
                    fontWeight: 700,
                    color: 'var(--text-muted)',
                    textTransform: 'uppercase',
                    letterSpacing: '0.08em',
                    marginBottom: 10,
                  }}
                >
                  Code Normalization Preview
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <div style={{ textAlign: 'center' }}>
                    <div
                      style={{
                        fontFamily: 'monospace',
                        fontWeight: 700,
                        fontSize: 14,
                        color: 'var(--accent)',
                      }}
                    >
                      {selectedCode.local_code}
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                      Facility Local Code
                    </div>
                  </div>

                  <div style={{ fontSize: 18, color: 'var(--text-muted)', flexShrink: 0 }}>→</div>

                  <div style={{ textAlign: 'center' }}>
                    <div
                      style={{
                        fontFamily: 'monospace',
                        fontWeight: 700,
                        fontSize: 14,
                        color: selectedCode.mapped ? 'var(--green, #16a34a)' : 'var(--red, #dc2626)',
                      }}
                    >
                      {selectedCode.common_code || 'UNMAPPED'}
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                      Central Common Code
                    </div>
                  </div>
                </div>

                {selectedCode.common_description && (
                  <div
                    style={{
                      marginTop: 10,
                      fontSize: 12,
                      color: 'var(--text-secondary)',
                      borderTop: '1px solid var(--border)',
                      paddingTop: 8,
                    }}
                  >
                    {selectedCode.common_description}
                  </div>
                )}
              </div>
            )}

            {/* Submitted Amount */}
            <div>
              <label
                style={{
                  display: 'block',
                  marginBottom: 6,
                  fontSize: 13,
                  fontWeight: 600,
                  color: 'var(--text-secondary)',
                  textTransform: 'uppercase',
                  letterSpacing: '0.05em',
                }}
              >
                Submitted Amount (VND)
              </label>
              <input
                type="number"
                value={amount}
                min={1}
                onChange={(e) => setAmount(e.target.value === '' ? '' : Number(e.target.value))}
                required
                style={{
                  width: '100%',
                  padding: '10px 12px',
                  borderRadius: 4,
                  border: '1px solid var(--border)',
                  fontSize: 14,
                  boxSizing: 'border-box',
                }}
              />
            </div>

            {/* Submit Error */}
            {submitError && (
              <div style={{ color: 'red', fontSize: 13, marginTop: -8 }}>{submitError}</div>
            )}

            {/* Submit Button */}
            <button
              type="submit"
              disabled={submitting || !selectedCode}
              style={{
                padding: '13px 0',
                background: submitting ? 'var(--text-muted)' : 'var(--accent)',
                color: 'white',
                border: 'none',
                borderRadius: 4,
                fontWeight: 700,
                fontSize: 15,
                cursor: submitting ? 'not-allowed' : 'pointer',
                transition: 'background 0.2s',
              }}
            >
              {submitting ? 'Submitting...' : 'Submit Claim to Central Hub'}
            </button>
          </form>
        )}
      </div>
    </div>
  );
};
