import React, { useState } from 'react';
import { 
  Plus, 
  Search, 
  Filter, 
  ArrowUpRight, 
  DollarSign, 
  Clock, 
  CheckCircle2, 
  Layers,
  Sparkles
} from 'lucide-react';

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
      {/* ── Metric Stats Cards ──────────────────────────────────────────── */}
      <div className="stats-grid">
        <div className="glass-panel stat-card">
          <div className="stat-label">
            <DollarSign size={16} color="var(--accent-cyan)" />
            <span>Total Disputed Exposure</span>
          </div>
          <div className="stat-value">
            ${(totalDisputedCents / 100).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </div>
          <div className="stat-hint">Across {cases.length} dispute records</div>
        </div>

        <div className="glass-panel stat-card">
          <div className="stat-label">
            <Clock size={16} color="var(--accent-amber)" />
            <span>Active Investigations</span>
          </div>
          <div className="stat-value" style={{ color: 'var(--accent-amber)' }}>
            {openCasesCount}
          </div>
          <div className="stat-hint">Open or awaiting telemetry</div>
        </div>

        <div className="glass-panel stat-card">
          <div className="stat-label">
            <CheckCircle2 size={16} color="var(--accent-emerald)" />
            <span>Resolved Disputes</span>
          </div>
          <div className="stat-value" style={{ color: 'var(--accent-emerald)' }}>
            {resolvedCasesCount}
          </div>
          <div className="stat-hint">With reviewer sign-off</div>
        </div>

        <div className="glass-panel stat-card">
          <div className="stat-label">
            <Layers size={16} color="var(--accent-violet)" />
            <span>Audit Invariants</span>
          </div>
          <div className="stat-value" style={{ fontSize: '1.25rem', marginTop: '0.8rem' }}>
            Append-Only
          </div>
          <div className="stat-hint">Database trigger enforced</div>
        </div>
      </div>

      {/* ── Table Action & Filter Bar ───────────────────────────────────── */}
      <div className="glass-panel" style={{ padding: '1.25rem', marginBottom: '1.5rem', display: 'flex', flexWrap: 'wrap', gap: '1rem', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', gap: '0.75rem', flex: 1, minWidth: 280, maxWidth: 450 }}>
          <div style={{ position: 'relative', width: '100%' }}>
            <Search size={16} style={{ position: 'absolute', left: 12, top: 12, color: 'var(--text-muted)' }} />
            <input
              type="text"
              className="form-input"
              style={{ paddingLeft: '2.25rem' }}
              placeholder="Search by case ID, customer, or claim..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
            />
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
          <div className="role-pill-group">
            {['ALL', 'OPEN', 'AWAITING_INFO', 'RESOLVED', 'REOPENED'].map(st => (
              <button
                key={st}
                type="button"
                className={`role-pill-btn ${statusFilter === st ? 'active-viewer' : ''}`}
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
            <Plus size={16} />
            <span>New Dispute</span>
          </button>
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
              <th>Disputed Value</th>
              <th>Evidence</th>
              <th>Status</th>
              <th>Created</th>
              <th style={{ textAlign: 'right' }}>Action</th>
            </tr>
          </thead>
          <tbody>
            {cases.length === 0 ? (
              <tr>
                <td colSpan="8" style={{ textAlign: 'center', padding: '3.5rem 1rem', color: 'var(--text-muted)' }}>
                  <Layers size={36} style={{ margin: '0 auto 0.75rem auto', opacity: 0.4, display: 'block' }} />
                  <div style={{ fontSize: '1.05rem', fontWeight: 600, color: 'var(--text-main)', marginBottom: '0.4rem' }}>No Dispute Cases in Database</div>
                  <p style={{ fontSize: '0.85rem', maxWidth: 420, margin: '0 auto 1.25rem auto' }}>
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
                <td colSpan="8" style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-muted)' }}>
                  No dispute cases match the selected filters.
                </td>
              </tr>
            ) : (
              filteredCases.map((c) => (
                <tr 
                  key={c.id} 
                  onClick={() => onSelectCase(c.id)}
                  style={{ cursor: 'pointer' }}
                >
                  <td className="font-mono" style={{ color: 'var(--accent-cyan)', fontWeight: 600 }}>
                    {c.id}
                  </td>
                  <td style={{ fontWeight: 600 }}>
                    {c.customer_name}
                  </td>
                  <td style={{ maxWidth: 320, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {c.title}
                  </td>
                  <td className="font-mono" style={{ fontWeight: 700 }}>
                    ${(c.disputed_amount_cents / 100).toFixed(2)}
                  </td>
                  <td>
                    <span className="citation-pill">
                      v{c.evidence_version}
                    </span>
                  </td>
                  <td>
                    {getStatusBadge(c.status)}
                  </td>
                  <td style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
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
                      <ArrowUpRight size={14} />
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
