import React from 'react';
import type { IntegrationEvent } from '../api/client';
import { CURRENCY_SYMBOL } from '../config';

interface ProcessingTimelineProps {
  events: IntegrationEvent[];
}

const EVENT_CONFIG: Record<string, { icon: string; label: string; cls: string }> = {
  TRANSACTION_RECEIVED:       { icon: '📥', label: 'Transaction Received',    cls: 'info' },
  VALIDATED:                  { icon: '✅', label: 'Validated',               cls: 'ok' },
  CODE_MAPPED:                { icon: '🔄', label: 'Codes Normalized',        cls: 'ok' },
  BENCHMARK_COMPLETED:        { icon: '📊', label: 'Benchmark Calculated',     cls: 'ok' },
  FWA_COMPLETED:              { icon: '🛡️',  label: 'FWA Checked',            cls: 'ok' },
  TPA_SUBMITTED:              { icon: '📤', label: 'Sent to TPA Core',             cls: 'info' },
  TPA_RESPONSE_RECEIVED:      { icon: '📩', label: 'TPA Response Received',   cls: 'ok' },
  TPA_ERROR:                  { icon: '❌', label: 'TPA Error',               cls: 'error' },
  HIS_CALLBACK_SENT:          { icon: '🔔', label: 'HIS Callback Sent',       cls: 'info' },
  HIS_CALLBACK_DELIVERED:     { icon: '✅', label: 'HIS Callback Delivered',  cls: 'ok' },
  HIS_CALLBACK_ACKNOWLEDGED:  { icon: '🏥', label: 'HIS Acknowledged',        cls: 'ok' },
  HIS_CALLBACK_FAILED:        { icon: '⚠️',  label: 'HIS Callback Failed',    cls: 'warn' },
  VALIDATION_FAILED:          { icon: '❌', label: 'Validation Failed',        cls: 'error' },
};

function fmtTime(iso: string) {
  const d = new Date(iso);
  return d.toLocaleTimeString('en-GB', { hour12: false }) + '.' + String(d.getMilliseconds()).padStart(3, '0');
}

export const ProcessingTimeline: React.FC<ProcessingTimelineProps> = ({ events }) => {
  const sorted = [...events].sort(
    (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
  );

  return (
    <div className="timeline">
      {sorted.map((ev) => {
        const cfg = EVENT_CONFIG[ev.event_type] || { icon: '◦', label: ev.event_type, cls: '' };
        return (
          <div key={ev.id} className="timeline-item">
            <div className={`timeline-icon ${cfg.cls}`}>{cfg.icon}</div>
            <div className="timeline-content">
              <div className="timeline-label">{cfg.label}</div>
              <div className="timeline-time">{fmtTime(ev.created_at)}</div>
              {ev.payload && Object.keys(ev.payload).length > 0 && (
                <div className="timeline-detail">
                  {ev.event_type === 'CODE_MAPPED' && Array.isArray((ev.payload as any).mappings) && (
                    <span>
                      {(ev.payload as any).mappings.map((m: any) => (
                        <span key={m.hospital_code} className="norm-arrow" style={{ marginRight: 12 }}>
                          <span className="norm-from">{m.hospital_code}</span>
                          <span className="norm-sep">→</span>
                          <span className="norm-to">{m.common_code}</span>
                        </span>
                      ))}
                    </span>
                  )}
                  {ev.event_type === 'FWA_COMPLETED' && (
                    <span>Overall: <strong style={{ color: (ev.payload as any).overall_status === 'PASS' ? 'var(--green)' : 'var(--red)' }}>
                      {(ev.payload as any).overall_status}
                    </strong>
                    {(ev.payload as any).flags?.length > 0 && (
                      <span style={{ color: 'var(--text-muted)', marginLeft: 8 }}>
                        Flags: {(ev.payload as any).flags.join(', ')}
                      </span>
                    )}
                    </span>
                  )}
                  {ev.event_type === 'TPA_RESPONSE_RECEIVED' && (
                    <span>
                      Decision: <strong style={{ color: (ev.payload as any).status === 'APPROVED' ? 'var(--green)' : 'var(--yellow)' }}>
                        {(ev.payload as any).status}
                      </strong>
                      {(ev.payload as any).approved_amount > 0 && (
                        <span style={{ color: 'var(--text-muted)', marginLeft: 8 }}>
                          {CURRENCY_SYMBOL} {Number((ev.payload as any).approved_amount).toFixed(2)}
                        </span>
                      )}
                    </span>
                  )}
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
};
