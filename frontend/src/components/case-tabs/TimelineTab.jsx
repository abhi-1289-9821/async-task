import React from 'react';

export default function TimelineTab({ events }) {
  return (
    <div className="card" style={{ padding: '2rem' }}>
      <div className="eyebrow">
        <span className="eyebrow-num">05</span>
        <span>·</span>
        <span>Append-Only Governance</span>
      </div>
      <h3 style={{ fontSize: '1.45rem', marginBottom: '0.25rem' }}>Immutable Append-Only Audit Trail</h3>
      <p style={{ fontSize: '0.85rem', color: 'var(--ink-secondary)', marginBottom: '1.5rem', maxWidth: 650 }}>
        Enforced by physical database triggers blocking UPDATE and DELETE statements on case_events.
      </p>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
        {(events || []).map((ev) => (
          <div 
            key={ev.id}
            className="card"
            style={{ 
              display: 'flex', 
              justifyContent: 'space-between', 
              alignItems: 'center', 
              padding: '1rem 1.25rem', 
              borderLeft: '3px solid var(--ink)',
              background: 'var(--surface-subtle)'
            }}
          >
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.35rem' }}>
                <span className="badge badge-open" style={{ fontSize: '0.68rem' }}>
                  {ev.event_type}
                </span>
                <span style={{ fontSize: '0.8rem', color: 'var(--ink-secondary)' }}>
                  by <strong style={{ color: 'var(--ink)' }}>{ev.actor}</strong>
                </span>
              </div>
              <div className="font-mono" style={{ fontSize: '0.75rem', color: 'var(--ink-muted)' }}>
                {JSON.stringify(ev.details || {})}
              </div>
            </div>
            <div style={{ fontSize: '0.75rem', color: 'var(--ink-muted)', whiteSpace: 'nowrap', marginLeft: '1rem' }}>
              {new Date(ev.created_at || ev.timestamp).toLocaleString()}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
