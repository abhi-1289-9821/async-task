import React from 'react';

function formatRuleTerms(r, formatCents) {
  if (!r) return '—';
  switch (r.rule_type) {
    case 'TIERED_GRADUATED':
    case 'TIERED_VOLUME': {
      const mode = r.rule_type === 'TIERED_GRADUATED' ? 'Graduated' : 'Volume';
      if (!Array.isArray(r.tiers) || r.tiers.length === 0) {
        return `${mode} (no tiers specified)`;
      }
      return (
        <div>
          <div style={{ fontWeight: 600, fontSize: '0.8rem', marginBottom: '0.2rem', color: 'var(--ink-secondary)' }}>
            {mode} Slabs:
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.15rem', fontSize: '0.8rem', fontFamily: 'monospace' }}>
            {r.tiers.map((t, i) => {
              const prevUpTo = i === 0 ? 0 : r.tiers[i - 1].up_to ?? 0;
              const slabLabel = t.up_to != null ? `${prevUpTo} – ${t.up_to}` : `>${prevUpTo}`;
              const rate = t.rate_cents ?? t.price_per_unit_cents ?? 0;
              return (
                <div key={i} style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem' }}>
                  <span>{slabLabel}:</span>
                  <span style={{ fontWeight: 600 }}>{rate}¢</span>
                </div>
              );
            })}
          </div>
        </div>
      );
    }
    case 'INCLUDED_UNITS': {
      return (
        <span>
          <strong>{r.included_units?.toLocaleString() ?? 0}</strong> included units, then{' '}
          <strong>{r.overage_rate_cents ?? r.rate_cents ?? 0}¢</strong>/unit
        </span>
      );
    }
    case 'DISCOUNT_PCT': {
      return <span><strong>{r.discount_pct ?? 0}%</strong> discount on line total</span>;
    }
    case 'MINIMUM_COMMIT': {
      return <span>Floor commit: <strong>{formatCents(r.minimum_commit_cents || r.rate_cents || 0)}</strong></span>;
    }
    case 'FLAT': {
      return <span>Flat fee: <strong>{formatCents(r.rate_cents || 0)}</strong></span>;
    }
    case 'PER_UNIT':
    default: {
      return <span><strong>{r.rate_cents ?? 0}¢</strong> per unit</span>;
    }
  }
}

export default function LinesTab({ caseData, formatCents }) {
  if (!caseData) return null;

  return (
    <div className="card" style={{ padding: '2rem' }}>
      <div className="eyebrow">
        <span className="eyebrow-num">03</span>
        <span>·</span>
        <span>Line Items & Pricing Rules</span>
      </div>
      <h3 style={{ fontSize: '1.45rem', marginBottom: '0.25rem' }}>Disputed Invoice Line Items</h3>
      <p style={{ fontSize: '0.85rem', color: 'var(--ink-secondary)', marginBottom: '1.25rem' }}>
        Original items billed on customer invoice subject to dispute audit.
      </p>

      <div className="table-container" style={{ marginBottom: '2.5rem' }}>
        <table>
          <thead>
            <tr>
              <th>Line ID</th>
              <th>Description</th>
              <th style={{ textAlign: 'right' }}>Billed Amount</th>
            </tr>
          </thead>
          <tbody>
            {(caseData.invoice_lines || []).map((l) => (
              <tr key={l.id}>
                <td className="font-mono" style={{ fontWeight: 600 }}>{l.id}</td>
                <td>{l.description}</td>
                <td className="table-money-cell">{formatCents(l.original_amount_cents)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3 style={{ fontSize: '1.45rem', marginBottom: '0.25rem' }}>Contractual Pricing Rules</h3>
      <p style={{ fontSize: '0.85rem', color: 'var(--ink-secondary)', marginBottom: '1.25rem' }}>
        Deterministic pricing slabs, unit tiers, commitments, exemptions, and status across all pricing types.
      </p>

      <div className="table-container">
        <table>
          <thead>
            <tr>
              <th>Rule ID</th>
              <th>Line ID</th>
              <th>Rule Type</th>
              <th>Pricing Terms / Configuration</th>
              <th style={{ textAlign: 'right' }}>Min Commit</th>
              <th>Exempt Envs</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {(caseData.contract_rules || []).map((r) => (
              <tr key={r.id} style={{ opacity: r.is_active === false ? 0.6 : 1 }}>
                <td className="font-mono" style={{ fontWeight: 600 }}>{r.id}</td>
                <td className="font-mono">{r.line_id}</td>
                <td><span className="badge badge-open">{r.rule_type}</span></td>
                <td>{formatRuleTerms(r, formatCents)}</td>
                <td className="table-money-cell">
                  {r.minimum_commit_cents ? formatCents(r.minimum_commit_cents) : '—'}
                </td>
                <td>
                  {Array.isArray(r.exempt_environments) && r.exempt_environments.length > 0 ? (
                    <span style={{ fontSize: '0.78rem', color: 'var(--ink-secondary)' }}>
                      {r.exempt_environments.join(', ')}
                    </span>
                  ) : (
                    <span style={{ color: 'var(--ink-secondary)', fontSize: '0.78rem' }}>None</span>
                  )}
                </td>
                <td>
                  {r.is_active === false ? (
                    <span className="badge badge-stale" title={r.supersedes_rule_id ? `Supersedes ${r.supersedes_rule_id}` : 'Superseded'}>
                      Superseded
                    </span>
                  ) : (
                    <span className="badge badge-resolved">Active</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
