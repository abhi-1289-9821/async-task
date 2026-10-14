import React, { useState } from 'react';
import { 
  Plus, 
  Search, 
  ArrowUpRight, 
  DollarSign, 
  Clock, 
  CheckCircle2, 
  ShieldCheck,
  Layers
} from 'lucide-react';
import { formatCents } from '../utils/money';

export default function CaseList({ cases, onSelectCase, onOpenCreateModal }) {
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState('ALL');

  // Compute summary stats
  const totalDisputedCents = cases.reduce((acc, c) => acc + (c.disputed_amount_cents || 0), 0);
  const openCasesCount = cases.filter(c => c.status === 'OPEN' || c.status === 'AWAITING_INFO' || c.status === 'REOPENED').length;
  const resolvedCasesCount = cases.filter(c => c.status === 'RESOLVED').length;

  // Filter cases
  const filteredCases = cases.filter(c => {
    const matchesStatus = statusFilter === 'ALL' || c.status === statusFilter;
    const matchesSearch = 
      c.id.toLowerCase().includes(searchTerm.toLowerCase()) ||
      c.customer_name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      c.title.toLowerCase().includes(searchTerm.toLowerCase());
    return matchesStatus && matchesSearch;
  });

  const getStatusBadge = (status) => {
    switch (status) {
      case 'OPEN':
        return <span className="badge badge-open">Open</span>;
      case 'AWAITING_INFO':
        return <span className="badge badge-awaiting">Awaiting Info</span>;
      case 'RESOLVED':
        return <span className="badge badge-resolved">Resolved</span>;
      case 'REOPENED':
        return <span className="badge badge-reopened">Reopened</span>;
      default:
        return <span className="badge">{status}</span>;
    }
  };

  return (
    <div>
      {/* ── Top Hero Strip ──────────────────────────────────────────────── */}
      <section className="editorial-hero" aria-labelledby="landing-hero-title">
        <div className="eyebrow">
          <span className="eyebrow-num">01</span>
          <span>·</span>
          <span>SaaS & Cloud Billing Dispute Resolution</span>
        </div>
        <h1 id="landing-hero-title" className="editorial-hero-title">
          Billing disputes, <em>investigated with evidence.</em>
        </h1>
        <p className="editorial-hero-dek">
          Deterministic financial recalculation paired with autonomous audit workflows, cryptographic source citations, and human-governed credit resolution.
        </p>

        <div className="hero-steps" role="list" aria-label="Resolution sequence">
          <div className="hero-step" role="listitem">
            <span className="hero-step-num">01</span>
            <span>Capture evidence</span>
          </div>
          <span className="hero-step-divider" aria-hidden="true">·</span>
          <div className="hero-step" role="listitem">
            <span className="hero-step-num">02</span>
            <span>Recalculate deterministically</span>
          </div>
          <span className="hero-step-divider" aria-hidden="true">·</span>
          <div className="hero-step" role="listitem">
            <span className="hero-step-num">03</span>
            <span>Keep people in control</span>
          </div>
        </div>

        <div className="hero-trust">
          <ShieldCheck size={14} color="var(--ink-muted)" aria-hidden="true" />
          <span>Human review · permissions · traceability</span>
        </div>
      </section>

      {/* ── Metric Stats Cards ──────────────────────────────────────────── */}
      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-label">
            <DollarSign size={14} color="var(--accent)" />
            <span>Total Disputed Exposure</span>
          </div>
          <div className="stat-value">
            ${(totalDisputedCents / 100).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </div>
          <div className="stat-hint">Across {cases.length} dispute records</div>
        </div>

        <div className="stat-card">
          <div className="stat-label">
            <Clock size={14} color="var(--status-amber)" />
            <span>Active Investigations</span>
          </div>
          <div className="stat-value">
            {openCasesCount}
          </div>
          <div className="stat-hint">Open or awaiting telemetry</div>
        </div>

        <div className="stat-card">
          <div className="stat-label">
            <CheckCircle2 size={14} color="var(--status-green)" />
            <span>Resolved Disputes</span>
          </div>
          <div className="stat-value">
            {resolvedCasesCount}
          </div>
          <div className="stat-hint">With reviewer sign-off</div>
        </div>

        <div className="stat-card">
          <div className="stat-label">
            <Layers size={14} color="var(--ink-muted)" />
            <span>Audit Invariants</span>
          </div>
          <div className="stat-value" style={{ fontSize: '1.4rem', marginTop: '0.75rem' }}>
            Append-Only
          </div>
          <div className="stat-hint">Database trigger enforced</div>
        </div>
      </div>

      {/* ── Table Action & Filter Bar ───────────────────────────────────── */}
      <div style={{ marginBottom: '1rem', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', flexWrap: 'wrap', gap: '1rem' }}>
        <div>
          <div className="eyebrow" style={{ marginBottom: '0.25rem' }}>
            <span className="eyebrow-num">02</span>
            <span>·</span>
            <span>Dispute Portfolio</span>
          </div>
          <h2 style={{ fontSize: '1.5rem' }}>Dispute Cases</h2>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
          <div className="role-pill-group">
            {['ALL', 'OPEN', 'AWAITING_INFO', 'RESOLVED', 'REOPENED'].map(st => (
              <button
                key={st}
                type="button"
                className={`role-pill-btn ${statusFilter === st ? 'active-reviewer' : ''}`}
                onClick={() => setStatusFilter(st)}
              >
                {st === 'ALL' ? 'All' : st.replace('_', ' ')}
              </button>
            ))}
          </div>

          <button
            type="button"
            className="btn btn-primary"
            onClick={onOpenCreateModal}
          >
            <Plus size={15} />
            <span>New Dispute</span>
          </button>
        </div>
      </div>

      <div className="card" style={{ padding: '0.85rem 1rem', marginBottom: '1.5rem' }}>
        <div style={{ position: 'relative', width: '100%' }}>
          <Search size={15} style={{ position: 'absolute', left: 12, top: 11, color: 'var(--ink-faint)' }} />
          <input
            type="text"
            className="form-input"
            style={{ paddingLeft: '2.25rem', border: 'none', background: 'transparent', padding: '0.5rem 0.5rem 0.5rem 2.25rem' }}
            placeholder="Search by case ID, customer, or dispute summary..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
        </div>
      </div>

      {/* ── Cases Table ─────────────────────────────────────────────────── */}
      <div className="table-container">
        <table>
          <thead>
            <tr>
              <th>Case ID</th>
              <th>Customer</th>
              <th>Dispute Description</th>
              <th style={{ textAlign: 'right' }}>Disputed Value</th>
              <th>Evidence</th>
              <th>Status</th>
              <th>Created</th>
              <th style={{ textAlign: 'right' }}>Action</th>
            </tr>
          </thead>
          <tbody>
            {cases.length === 0 ? (
              <tr>
                <td colSpan="8" style={{ textAlign: 'center', padding: '4rem 1.5rem', color: 'var(--ink-muted)' }}>
                  <Layers size={36} style={{ margin: '0 auto 0.75rem auto', opacity: 0.4, display: 'block' }} />
                  <h3 style={{ fontSize: '1.2rem', marginBottom: '0.4rem', color: 'var(--ink)' }}>
                    No Dispute Cases in Database
                  </h3>
                  <p style={{ fontSize: '0.85rem', maxWidth: 440, margin: '0 auto 1.5rem auto', color: 'var(--ink-secondary)', lineHeight: 1.5 }}>
                    Create your first dispute or load pre-configured scenario presets to test deterministic billing and AI resolution.
                  </p>
                  <button type="button" className="btn btn-primary btn-sm" onClick={onOpenCreateModal} aria-label="Create First Dispute Case">
                    <Plus size={14} />
                    <span>Create Dispute Case</span>
                  </button>
                </td>
              </tr>
            ) : filteredCases.length === 0 ? (
              <tr>
                <td colSpan="8" style={{ textAlign: 'center', padding: '3.5rem', color: 'var(--ink-muted)' }}>
                  No dispute cases match the selected filter query "{searchTerm}".
                </td>
              </tr>
            ) : (
              filteredCases.map((c) => (
                <tr 
                  key={c.id} 
                  onClick={() => onSelectCase(c.id)}
                  style={{ cursor: 'pointer' }}
                >
                  <td className="font-mono" style={{ fontWeight: 600, color: 'var(--ink)' }}>
                    {c.id}
                  </td>
                  <td style={{ fontWeight: 600 }}>
                    {c.customer_name}
                  </td>
                  <td style={{ maxWidth: 320, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--ink-secondary)' }}>
                    {c.title}
                  </td>
                  <td className="table-money-cell">
                    {formatCents(c.disputed_amount_cents)}
                  </td>
                  <td>
                    <span className="citation-pill" title={`Cryptographic evidence version ${c.evidence_version}`}>
                      v{c.evidence_version}
                    </span>
                  </td>
                  <td>
                    {getStatusBadge(c.status)}
                  </td>
                  <td style={{ fontSize: '0.8rem', color: 'var(--ink-muted)' }}>
                    {new Date(c.created_at).toLocaleDateString()}
                  </td>
                  <td style={{ textAlign: 'right' }}>
                    <button 
                      type="button" 
                      className="btn btn-secondary btn-sm"
                      onClick={(e) => {
                        e.stopPropagation();
                        onSelectCase(c.id);
                      }}
                    >
                      <span>Audit</span>
                      <ArrowUpRight size={13} />
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
