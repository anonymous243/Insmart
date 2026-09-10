import React, { useEffect, useState } from 'react';
import { api, CodeMappingRow } from '../api/client';
import { StatusBadge } from '../components/StatusBadge';

export const CodeMaster: React.FC = () => {
  const [rows, setRows] = useState<CodeMappingRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('');

  useEffect(() => {
    api.getCodeMappings().then(setRows).finally(() => setLoading(false));
  }, []);

  const filtered = rows.filter(r =>
    !filter ||
    r.local_code.toLowerCase().includes(filter.toLowerCase()) ||
    r.common_code.toLowerCase().includes(filter.toLowerCase()) ||
    r.hospital_name.toLowerCase().includes(filter.toLowerCase()) ||
    r.local_description.toLowerCase().includes(filter.toLowerCase())
  );

  // Group by common code to visually show normalization
  const groups = filtered.reduce<Record<string, CodeMappingRow[]>>((acc, r) => {
    if (!acc[r.common_code]) acc[r.common_code] = [];
    acc[r.common_code].push(r);
    return acc;
  }, {});

  if (loading) return <div className="loading"><div className="spinner" />Loading code master...</div>;

  return (
    <>
      <div className="page-header">
        <h2>Code Master</h2>
        <p>Hospital-specific procedure codes normalized to central common codes — the core of the platform</p>
      </div>
      <div className="page-body">

        <div style={{ marginBottom: 20, padding: '14px 16px', background: 'var(--blue-bg)', borderRadius: 'var(--radius)', border: '1px solid var(--border)', fontSize: 13, color: 'var(--text-secondary)' }}>
          <strong style={{ color: 'var(--blue)' }}>Key concept:</strong>{' '}
          Each hospital uses its own internal procedure codes. This platform maps all hospital-specific codes to a single
          common code master, enabling unified processing, benchmarking, and TPA routing — without requiring hospitals to
          change their systems.
        </div>

        <div style={{ marginBottom: 16 }}>
          <input
            placeholder="Filter by hospital, code, or description..."
            value={filter}
            onChange={e => setFilter(e.target.value)}
            style={{ maxWidth: 400 }}
          />
        </div>

        {Object.entries(groups).map(([commonCode, groupRows]) => {
          const first = groupRows[0];
          return (
            <div key={commonCode} style={{ marginBottom: 20 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
                <span className="common-code-group">{commonCode}</span>
                <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)' }}>
                  {first.common_description}
                </span>
                <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--text-muted)' }}>
                  {first.category}
                </span>
                {first.terminology_system && (
                  <span className="tag" style={{ background: 'var(--blue-bg)', color: 'var(--blue)', borderColor: 'var(--blue)' }}>
                    {first.terminology_system} {first.terminology_version ? `v${first.terminology_version}` : ''}
                  </span>
                )}
                <span className="tag">{groupRows.length} hospital{groupRows.length > 1 ? 's' : ''}</span>
              </div>

              <div className="table-wrapper">
                <table>
                  <thead>
                    <tr>
                      <th>Hospital</th>
                      <th>Hospital Code</th>
                      <th>Hospital Description</th>
                      <th>Common Code</th>
                      <th>Confidence</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {groupRows.map((row, i) => (
                      <tr key={i}>
                        <td>
                          <div style={{ fontWeight: 500 }}>{row.hospital_name}</div>
                          <div className="td-small">{row.hospital_code}</div>
                        </td>
                        <td><span className="td-code">{row.local_code}</span></td>
                        <td style={{ color: 'var(--text-secondary)' }}>{row.local_description}</td>
                        <td>
                          <span className="norm-arrow">
                            <span className="norm-sep">→</span>
                            <span className="norm-to">{row.common_code}</span>
                          </span>
                        </td>
                        <td>
                          <div className="benchmark-bar-wrap">
                            <div className="benchmark-bar">
                              <div
                                className="benchmark-bar-fill pass"
                                style={{ width: `${Math.round(row.confidence * 100)}%` }}
                              />
                            </div>
                            <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                              {Math.round(row.confidence * 100)}%
                            </span>
                          </div>
                        </td>
                        <td><StatusBadge value={row.mapping_status} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          );
        })}
      </div>
    </>
  );
};
