import React from 'react';
import { formatCents, formatDifference } from '../../utils/money';
import { Clock, ShieldCheck, Calculator, Bot, FileText, CheckCircle2, RefreshCw } from 'lucide-react';

function getEventIcon(eventType) {
  switch (eventType) {
    case 'CALCULATION_RUN':
      return <Calculator size={14} style={{ color: 'var(--accent)' }} />;
    case 'INVESTIGATION_RUN_COMPLETED':
      return <Bot size={14} style={{ color: 'var(--status-teal)' }} />;
    case 'CREDIT_ISSUED':
      return <ShieldCheck size={14} style={{ color: 'var(--status-green)' }} />;
    case 'FINDING_REVIEWED':
      return <CheckCircle2 size={14} style={{ color: 'var(--status-green)' }} />;
    case 'CASE_TRANSITIONED':
      return <RefreshCw size={14} style={{ color: 'var(--status-amber)' }} />;
    case 'CASE_CREATED':
    case 'EVIDENCE_UPLOADED':
    default:
      return <FileText size={14} style={{ color: 'var(--ink-secondary)' }} />;
  }
}

function getEventBadgeClass(eventType, details) {
  if (eventType === 'CALCULATION_RUN') {
    if (details?.engine_status === 'OK') return 'badge-resolved';
    if (details?.engine_status === 'INSUFFICIENT_DATA') return 'badge-stale';
    if (details?.engine_status === 'AMBIGUOUS') return 'badge-awaiting';
  }
  if (eventType === 'CREDIT_ISSUED' || eventType === 'FINDING_REVIEWED') {
    return 'badge-resolved';
  }
  if (eventType === 'CASE_TRANSITIONED') {
    return 'badge-awaiting';
  }
  return 'badge-open';
}

function renderEventHighlights(ev) {
  const d = ev.details || {};
  const highlights = [];

  if (d.engine_status) {
    highlights.push(
      <span 
        key="status" 
        className={`badge ${d.engine_status === 'OK' ? 'badge-resolved' : d.engine_status === 'INSUFFICIENT_DATA' ? 'badge-stale' : 'badge-awaiting'}`}
      >
        Status: {d.engine_status}
      </span>
    );
  }

  if (d.total_difference_cents !== undefined && d.total_difference_cents !== null) {
    highlights.push(
      <span 
        key="diff" 
        className={`badge ${d.total_difference_cents < 0 ? 'badge-stale' : d.total_difference_cents > 0 ? 'badge-awaiting' : 'badge-resolved'}`}
      >
        Diff: {formatDifference(d.total_difference_cents)}
      </span>
    );
  }

  if (d.amount_cents !== undefined && d.amount_cents !== null) {
    highlights.push(
      <span key="amount" className="badge badge-resolved">
        Amount: {formatCents(d.amount_cents)}
      </span>
    );
  }

  if (d.scenario) {
    highlights.push(
      <span key="scenario" className="badge badge-open">
        {d.scenario}
      </span>
    );
  }

  if (d.findings_count !== undefined) {
    highlights.push(
      <span key="findings" className="badge badge-open">
        Findings: {d.findings_count}
      </span>
    );
  }

  if (d.options_count !== undefined) {
    highlights.push(
      <span key="options" className="badge badge-open">
        Options: {d.options_count}
      </span>
    );
  }

  if (d.decision) {
    highlights.push(
      <span key="decision" className={`badge ${d.decision === 'ACCEPT' ? 'badge-resolved' : 'badge-stale'}`}>
        Decision: {d.decision}
      </span>
    );
  }

  if (d.evidence_version !== undefined) {
    highlights.push(
      <span key="ev-ver" className="citation-pill" style={{ fontSize: '0.68rem', padding: '0.15rem 0.45rem' }}>
        v{d.evidence_version}
      </span>
    );
  }

  return highlights;
}

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

      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem' }}>
        {(events || []).map((ev) => {
          const highlights = renderEventHighlights(ev);
          const detailsStr = typeof ev.details === 'string' ? ev.details : JSON.stringify(ev.details || {}, null, 2);

          return (
            <div 
              key={ev.id}
              className="card"
              style={{ 
                display: 'flex', 
                justifyContent: 'space-between', 
                alignItems: 'flex-start', 
                padding: '1.15rem 1.35rem', 
                borderLeft: '4px solid var(--ink)',
                background: 'var(--surface-subtle)',
                gap: '1.5rem',
                overflow: 'hidden'
              }}
            >
              {/* Left Column: Event info and details (flex: 1 with minWidth: 0 to prevent expanding) */}
              <div style={{ flex: 1, minWidth: 0 }}>
                {/* Header Row */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', marginBottom: '0.45rem', flexWrap: 'wrap' }}>
                  {getEventIcon(ev.event_type)}
                  <span className={`badge ${getEventBadgeClass(ev.event_type, ev.details)}`} style={{ fontSize: '0.72rem' }}>
                    {ev.event_type}
                  </span>
                  <span style={{ fontSize: '0.82rem', color: 'var(--ink-secondary)' }}>
                    by <strong style={{ color: 'var(--ink)' }}>{ev.actor}</strong>
                  </span>
                </div>

                {/* Highlights row if applicable */}
                {highlights.length > 0 && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', marginBottom: '0.55rem', flexWrap: 'wrap' }}>
                    {highlights}
                  </div>
                )}

                {/* Structured Payload Container - Safe wrapping prevents breaking layout */}
                <div 
                  className="font-mono" 
                  style={{ 
                    fontSize: '0.72rem', 
                    color: 'var(--ink-muted)',
                    background: 'var(--surface)',
                    padding: '0.55rem 0.75rem',
                    borderRadius: 'var(--radius-sm)',
                    border: '1px solid var(--line-subtle)',
                    wordBreak: 'break-all',
                    overflowWrap: 'anywhere',
                    whiteSpace: 'pre-wrap',
                    maxHeight: '180px',
                    overflowY: 'auto',
                    lineHeight: 1.45
                  }}
                >
                  {detailsStr}
                </div>
              </div>

              {/* Right Column: Always pinned, never pushed off */}
              <div style={{ flexShrink: 0, textAlign: 'right', minWidth: '130px' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: '0.35rem', fontSize: '0.75rem', color: 'var(--ink-secondary)', fontWeight: 600, whiteSpace: 'nowrap' }}>
                  <Clock size={12} style={{ color: 'var(--ink-muted)' }} />
                  <span>{new Date(ev.created_at || ev.timestamp).toLocaleDateString()}</span>
                </div>
                <div style={{ fontSize: '0.72rem', color: 'var(--ink-muted)', whiteSpace: 'nowrap', marginTop: '3px' }}>
                  {new Date(ev.created_at || ev.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
