import React, { useEffect, useState } from 'react';
import { 
  ArrowLeft, 
  Upload, 
  Play, 
  Bot, 
  ShieldCheck, 
  FileText, 
  Calculator, 
  History, 
  AlertTriangle, 
  Check, 
  Edit3, 
  XCircle, 
  Lock, 
  Hash, 
  Calendar,
  AlertCircle,
  ExternalLink,
  Layers
} from 'lucide-react';
import { 
  getCase, 
  getCaseEvents, 
  runCalculation, 
  triggerInvestigation, 
  getCaseInvestigations, 
  getCaseFindings, 
  reviewFinding, 
  approveCredit, 
  getCaseCredits,
  transitionCase,
  getActiveRole
} from '../api/client';
import EvidenceModal from './EvidenceModal';

export default function CaseDetail({ caseId, onBack, onToast }) {
  const [caseData, setCaseData] = useState(null);
  const [events, setEvents] = useState([]);
  const [calculation, setCalculation] = useState(null);
  const [investigation, setInvestigation] = useState(null);
  const [findings, setFindings] = useState([]);
  const [credits, setCredits] = useState([]);
  const [activeTab, setActiveTab] = useState('engine');
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [evidenceModalOpen, setEvidenceModalOpen] = useState(false);
  
  // Review Finding Modal State
  const [reviewModalOpen, setReviewModalOpen] = useState(false);
  const [selectedFinding, setSelectedFinding] = useState(null);
  const [reviewAction, setReviewAction] = useState('ACCEPT');
  const [reviewNote, setReviewNote] = useState('Verified against contract terms');
  const [editedText, setEditedText] = useState('');

  // Credit Approval State
  const [selectedLineId, setSelectedLineId] = useState('');
  const [creditReason, setCreditReason] = useState('RATE_CALCULATION_ERROR');
  const [creditNote, setCreditNote] = useState('Approved per confirmed calculation discrepancy');

  const role = getActiveRole();
  const isReviewer = role === 'REVIEWER';

  const loadAllCaseData = async () => {
    try {
      setLoading(true);
      const [cData, cEvents, cFindings, cCredits, cInvs] = await Promise.all([
        getCase(caseId),
        getCaseEvents(caseId).catch(() => []),
        getCaseFindings(caseId).catch(() => []),
        getCaseCredits(caseId).catch(() => []),
        getCaseInvestigations(caseId).catch(() => []),
      ]);
      setCaseData(cData);
      setEvents(cEvents);
      setFindings(cFindings);
      setCredits(cCredits);
      if (cInvs && cInvs.length > 0) {
        setInvestigation(cInvs[0]);
      }
      if (cData.invoice_lines && cData.invoice_lines.length > 0) {
        setSelectedLineId(cData.invoice_lines[0].id);
      }
    } catch (err) {
      onToast('error', err.message || 'Failed to load case data');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (caseId) {
      loadAllCaseData();
    }
  }, [caseId]);

  // Transition status handler
  const handleTransition = async (targetStatus) => {
    if (!isReviewer) {
      onToast('error', 'HTTP 403 Forbidden: Only REVIEWER role can transition case status');
      return;
    }
    try {
      setActionLoading(true);
      await transitionCase(caseId, targetStatus, `Manual transition to ${targetStatus}`);
      onToast('success', `Case status updated to ${targetStatus}`);
      await loadAllCaseData();
    } catch (err) {
      onToast('error', err.message || 'Transition rejected');
    } finally {
      setActionLoading(false);
    }
  };

  // Run calculation engine
  const handleRunCalculation = async () => {
    try {
      setActionLoading(true);
      const res = await runCalculation(caseId);
      setCalculation(res);
      onToast('success', 'Deterministic calculation executed successfully');
      await loadAllCaseData();
    } catch (err) {
      onToast('error', err.message || 'Calculation failed');
    } finally {
      setActionLoading(false);
    }
  };

  // Trigger LangGraph investigation
  const handleTriggerInvestigation = async () => {
    if (!isReviewer) {
      onToast('error', 'HTTP 403 Forbidden: Only REVIEWER role can trigger agent runs');
      return;
    }
    try {
      setActionLoading(true);
      const runRes = await triggerInvestigation(caseId);
      setInvestigation(runRes);
      onToast('success', `Investigation ${runRes.status}: LangGraph workflow finished`);
      await loadAllCaseData();
      setActiveTab('investigation');
    } catch (err) {
      onToast('error', err.message || 'Investigation run failed');
    } finally {
      setActionLoading(false);
    }
  };

  // Submit human finding review
  const handleSubmitReview = async () => {
    if (!isReviewer) {
      onToast('error', 'HTTP 403 Forbidden: Only REVIEWER role can review findings');
      return;
    }
    if (!selectedFinding) return;

    try {
      setActionLoading(true);
      await reviewFinding(selectedFinding.id, {
        action: reviewAction,
        note: reviewNote,
        edited_text: reviewAction === 'EDIT' ? editedText : null,
      });
      onToast('success', `Finding reviewed as ${reviewAction}`);
      setReviewModalOpen(false);
      await loadAllCaseData();
    } catch (err) {
      onToast('error', err.message || 'Failed to submit review');
    } finally {
      setActionLoading(false);
    }
  };

  // Approve mock credit
  const handleApproveCredit = async (findingId, optId) => {
    if (!isReviewer) {
      onToast('error', 'HTTP 403 Forbidden: Only REVIEWER role can approve credits');
      return;
    }
    try {
      setActionLoading(true);
      const payload = {
        case_id: caseId,
        invoice_line_id: selectedLineId || caseData.invoice_lines[0]?.id,
        reason_code: creditReason,
        finding_id: findingId,
        resolution_option_id: optId || null,
        reason_note: creditNote,
      };
      const res = await approveCredit(payload);
      onToast('success', `Credit approved for $${(res.amount_cents / 100).toFixed(2)} under lock`);
      await loadAllCaseData();
      setActiveTab('credits');
    } catch (err) {
      onToast('error', err.message || 'Credit approval failed');
    } finally {
      setActionLoading(false);
    }
  };

  if (loading || !caseData) {
    return (
      <div style={{ textAlign: 'center', padding: '4rem', color: 'var(--text-muted)' }}>
        <div style={{ fontSize: '1.25rem', marginBottom: '0.5rem' }}>Loading dispute case details...</div>
        <div>Connecting to append-only audit trail</div>
      </div>
    );
  }

  const primaryFinding = findings[0] || null;
  const isAcceptedFinding = primaryFinding?.reviews?.some(r => r.action === 'ACCEPT');

  return (
    <div>
      {/* ── Breadcrumb & Navigation Bar ───────────────────────────────── */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem', flexWrap: 'wrap', gap: '1rem' }}>
        <button type="button" className="btn btn-secondary btn-sm" onClick={onBack}>
          <ArrowLeft size={14} />
          <span>Back to Disputes</span>
        </button>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => setEvidenceModalOpen(true)}
          >
            <Upload size={14} />
            <span>Upload Evidence</span>
          </button>

          {caseData.status === 'OPEN' && (
            <button
              type="button"
              className="btn btn-amber btn-sm"
              onClick={() => handleTransition('AWAITING_INFO')}
              disabled={actionLoading}
            >
              Request Info
            </button>
          )}

          {caseData.status === 'AWAITING_INFO' && (
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={() => handleTransition('OPEN')}
              disabled={actionLoading}
            >
              Resume Open
            </button>
          )}

          {caseData.status !== 'RESOLVED' ? (
            <button
              type="button"
              className="btn btn-emerald btn-sm"
              onClick={() => handleTransition('RESOLVED')}
              disabled={actionLoading}
            >
              Mark Resolved
            </button>
          ) : (
            <button
              type="button"
              className="btn btn-amber btn-sm"
              onClick={() => handleTransition('REOPENED')}
              disabled={actionLoading}
            >
              Reopen Case
            </button>
          )}
        </div>
      </div>

      {/* ── Case Header Banner ─────────────────────────────────────────── */}
      <div className="glass-panel" style={{ padding: '1.75rem', marginBottom: '1.75rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '1rem' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem', marginBottom: '0.45rem' }}>
              <span className="font-mono" style={{ fontSize: '1.1rem', color: 'var(--accent-cyan)', fontWeight: 700 }}>
                {caseData.id}
              </span>
              <span className={`badge badge-${caseData.status.toLowerCase().replace('_', '')}`}>
                {caseData.status}
              </span>
              <span className="citation-pill" title="Cryptographic Evidence Snapshot Version">
                v{caseData.evidence_version}
              </span>
            </div>
            <h2 style={{ fontSize: '1.65rem', marginBottom: '0.25rem' }}>{caseData.title}</h2>
            <div style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>
              Customer: <strong style={{ color: '#fff' }}>{caseData.customer_name}</strong>
            </div>
            {caseData.dispute_description && (
              <div style={{ marginTop: '0.75rem', padding: '0.65rem 0.85rem', background: 'rgba(255, 255, 255, 0.03)', borderRadius: 'var(--radius-sm)', borderLeft: '3px solid var(--accent-cyan)', fontSize: '0.825rem', color: '#cbd5e1', lineHeight: '1.4' }}>
                <span style={{ fontWeight: 600, color: '#38bdf8', marginRight: '0.4rem' }}>Customer Statement:</span>
                "{caseData.dispute_description}"
              </div>
            )}
          </div>

          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Disputed Exposure</div>
            <div className="font-mono" style={{ fontSize: '2rem', fontWeight: 800, color: 'var(--accent-cyan)' }}>
              ${(caseData.disputed_amount_cents / 100).toFixed(2)}
            </div>
          </div>
        </div>
      </div>

      {/* ── Tab Navigation ─────────────────────────────────────────────── */}
      <div className="tabs-nav">
        <button
          type="button"
          className={`tab-btn ${activeTab === 'engine' ? 'active' : ''}`}
          onClick={() => setActiveTab('engine')}
        >
          <Calculator size={16} />
          <span>Deterministic Engine</span>
        </button>

        <button
          type="button"
          className={`tab-btn ${activeTab === 'investigation' ? 'active' : ''}`}
          onClick={() => setActiveTab('investigation')}
        >
          <Bot size={16} />
          <span>AI Investigation (LangGraph)</span>
        </button>

        <button
          type="button"
          className={`tab-btn ${activeTab === 'lines' ? 'active' : ''}`}
          onClick={() => setActiveTab('lines')}
        >
          <FileText size={16} />
          <span>Invoice Lines & Rules</span>
        </button>

        <button
          type="button"
          className={`tab-btn ${activeTab === 'credits' ? 'active' : ''}`}
          onClick={() => setActiveTab('credits')}
        >
          <ShieldCheck size={16} />
          <span>Credit Issuance ({credits.length})</span>
        </button>

        <button
          type="button"
          className={`tab-btn ${activeTab === 'timeline' ? 'active' : ''}`}
          onClick={() => setActiveTab('timeline')}
        >
          <History size={16} />
          <span>Audit Trail ({events.length})</span>
        </button>
      </div>

      {/* ── TAB 1: Deterministic Engine ────────────────────────────────── */}
      {activeTab === 'engine' && (
        <div>
          <div className="glass-panel" style={{ padding: '1.5rem', marginBottom: '1.5rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem', flexWrap: 'wrap', gap: '1rem' }}>
              <div>
                <h3 style={{ fontSize: '1.2rem' }}>Pure Python Billing Engine</h3>
                <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                  Evaluates Decimal arithmetic, graduated & volume slabs, staging exemptions, and emits cryptographic result anchors.
                </p>
              </div>
              <button
                type="button"
                className="btn btn-primary"
                onClick={handleRunCalculation}
                disabled={actionLoading}
              >
                <Play size={16} />
                <span>{actionLoading ? 'Calculating...' : 'Run Billing Engine'}</span>
              </button>
            </div>

            {calculation ? (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1rem', background: 'rgba(255, 255, 255, 0.02)', padding: '1rem', borderRadius: 'var(--radius-md)' }}>
                <div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Engine Status</div>
                  <div style={{ fontWeight: 700, color: calculation.engine_status === 'OK' ? 'var(--accent-emerald)' : 'var(--accent-amber)' }}>
                    {calculation.engine_status}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Billed Total</div>
                  <div className="font-mono" style={{ fontWeight: 700 }}>
                    ${(calculation.total_original_billed_cents / 100).toFixed(2)}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Recalculated Total</div>
                  <div className="font-mono" style={{ fontWeight: 700 }}>
                    ${(calculation.total_recalculated_cents / 100).toFixed(2)}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Total Discrepancy</div>
                  <div className="font-mono" style={{ fontWeight: 800, color: calculation.total_difference_cents < 0 ? 'var(--accent-rose)' : 'var(--accent-emerald)' }}>
                    ${(Math.abs(calculation.total_difference_cents) / 100).toFixed(2)} {calculation.total_difference_cents < 0 ? '(Overcharge)' : ''}
                  </div>
                </div>
              </div>
            ) : (
              <div style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-muted)' }}>
                Click "Run Billing Engine" to execute calculation against current evidence.
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── TAB 2: AI Investigation (LangGraph) ───────────────────────── */}
      {activeTab === 'investigation' && (
        <div>
          <div className="glass-panel" style={{ padding: '1.5rem', marginBottom: '1.5rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem', flexWrap: 'wrap', gap: '1rem' }}>
              <div>
                <h3 style={{ fontSize: '1.2rem' }}>Autonomous LangGraph Investigation</h3>
                <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                  Multi-node StateGraph synthesizing findings, verifying citation anchors, and proposing human resolution options.
                </p>
              </div>
              <button
                type="button"
                className="btn btn-primary"
                onClick={handleTriggerInvestigation}
                disabled={actionLoading}
              >
                <Bot size={16} />
                <span>{actionLoading ? 'Investigating...' : 'Trigger Investigation Run'}</span>
              </button>
            </div>

            {investigation && (
              <div style={{ display: 'flex', gap: '1rem', alignItems: 'center', marginBottom: '1.5rem', flexWrap: 'wrap' }}>
                <span className={`badge ${investigation.status === 'COMPLETED' ? 'badge-resolved' : 'badge-awaiting'}`}>
                  Run {investigation.status}
                </span>
                <span className="font-mono" style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                  Run ID: {investigation.id}
                </span>
                {investigation.token_usage && (
                  <span className="citation-pill">
                    Tokens: {investigation.token_usage.total_tokens || 0}
                  </span>
                )}
              </div>
            )}

            {findings.length > 0 ? (
              findings.map((f) => (
                <div key={f.id} className="glass-card" style={{ marginBottom: '1.25rem', borderColor: f.is_stale ? 'var(--accent-rose)' : 'var(--border-subtle)' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.75rem', flexWrap: 'wrap', gap: '0.5rem' }}>
                    <div>
                      <span className="badge badge-open" style={{ marginRight: '0.5rem' }}>
                        {f.finding_type}
                      </span>
                      {f.is_stale && (
                        <span className="badge badge-stale">STALE EVIDENCE</span>
                      )}
                    </div>

                    <div style={{ display: 'flex', gap: '0.5rem' }}>
                      <button
                        type="button"
                        className="btn btn-secondary btn-sm"
                        onClick={() => {
                          setSelectedFinding(f);
                          setEditedText(f.raw_ai_text || '');
                          setReviewModalOpen(true);
                        }}
                      >
                        <Edit3 size={13} />
                        <span>Human Review</span>
                      </button>
                    </div>
                  </div>

                  <p style={{ fontSize: '0.92rem', lineHeight: 1.6, marginBottom: '1rem', color: '#e2e8f0' }}>
                    {f.raw_ai_text}
                  </p>

                  {/* Verified Facts */}
                  {f.verified_facts && f.verified_facts.length > 0 && (
                    <div style={{ marginBottom: '0.75rem' }}>
                      <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase', marginBottom: '0.35rem' }}>
                        Verified Facts
                      </div>
                      <ul style={{ paddingLeft: '1.25rem', fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
                        {f.verified_facts.map((fact, idx) => (
                          <li key={idx}>{fact}</li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {/* Citations */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginTop: '1rem', flexWrap: 'wrap' }}>
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Citation Anchors:</span>
                    {f.citation_ids && f.citation_ids.map((cid, i) => {
                      const isResult = cid.startsWith('res_');
                      const isLine = cid.startsWith('line-');
                      const isRule = cid.startsWith('rule-');
                      const isEvent = cid.startsWith('ev-') || cid.startsWith('evt-');
                      const typeLabel = isResult ? 'Engine Result' : isLine ? 'Line' : isRule ? 'Rule' : isEvent ? 'Usage Telemetry' : 'Evidence';
                      return (
                        <span key={i} className="citation-pill" title={`${typeLabel}: ${cid}`}>
                          <Hash size={11} />
                          <span style={{ opacity: 0.7, fontSize: '0.68rem', marginRight: '3px' }}>{typeLabel}:</span>
                          {cid}
                        </span>
                      );
                    })}
                    <span style={{ fontSize: '0.72rem', color: f.citation_validation_passed ? 'var(--accent-emerald)' : 'var(--accent-rose)', fontWeight: 600 }}>
                      {f.citation_validation_passed ? '✓ Citations Verified' : '✗ Verification Failed'}
                    </span>
                  </div>

                  {/* Review History */}
                  {f.reviews && f.reviews.length > 0 && (
                    <div style={{ marginTop: '1rem', borderTop: '1px solid var(--border-subtle)', paddingTop: '0.75rem' }}>
                      <div style={{ fontSize: '0.72rem', color: 'var(--accent-emerald)', fontWeight: 600 }}>
                        ✓ Reviewed by {f.reviews[0].reviewer} ({f.reviews[0].action}): "{f.reviews[0].note || 'No note'}"
                      </div>
                    </div>
                  )}
                </div>
              ))
            ) : (
              <div style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-muted)' }}>
                No findings generated yet. Trigger an investigation to analyze this dispute.
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── TAB 3: Invoice Lines & Rules ──────────────────────────────── */}
      {activeTab === 'lines' && (
        <div className="glass-panel" style={{ padding: '1.5rem' }}>
          <h3 style={{ fontSize: '1.2rem', marginBottom: '1rem' }}>Disputed Invoice Line Items</h3>
          <div className="table-container" style={{ marginBottom: '2rem' }}>
            <table>
              <thead>
                <tr>
                  <th>Line ID</th>
                  <th>Description</th>
                  <th>Billed Amount</th>
                </tr>
              </thead>
              <tbody>
                {caseData.invoice_lines.map((l) => (
                  <tr key={l.id}>
                    <td className="font-mono">{l.id}</td>
                    <td>{l.description}</td>
                    <td className="font-mono">${(l.original_amount_cents / 100).toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <h3 style={{ fontSize: '1.2rem', marginBottom: '1rem' }}>Contractual Pricing Rules</h3>
          <div className="table-container">
            <table>
              <thead>
                <tr>
                  <th>Rule ID</th>
                  <th>Line ID</th>
                  <th>Rule Type</th>
                  <th>Rate (cents)</th>
                  <th>Commitment</th>
                </tr>
              </thead>
              <tbody>
                {caseData.contract_rules.map((r) => (
                  <tr key={r.id}>
                    <td className="font-mono">{r.id}</td>
                    <td className="font-mono">{r.line_id}</td>
                    <td><span className="badge badge-open">{r.rule_type}</span></td>
                    <td className="font-mono">{r.rate_cents}¢</td>
                    <td className="font-mono">{r.minimum_commit_cents ? `$${(r.minimum_commit_cents / 100).toFixed(2)}` : 'None'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── TAB 4: Credit Issuance ────────────────────────────────────── */}
      {activeTab === 'credits' && (
        <div>
          <div className="glass-panel" style={{ padding: '1.5rem', marginBottom: '1.5rem' }}>
            <h3 style={{ fontSize: '1.2rem', marginBottom: '0.4rem' }}>Concurrency-Safe Credit Approval</h3>
            <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '1.5rem' }}>
              Enforces PostgreSQL row-level locking (SELECT FOR UPDATE) and SQLite BEGIN IMMEDIATE to guarantee zero double-crediting.
            </p>

            <div style={{ background: 'rgba(255, 255, 255, 0.02)', padding: '1.25rem', borderRadius: 'var(--radius-md)', marginBottom: '1.5rem', border: '1px solid var(--border-subtle)' }}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1rem' }}>
                <div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Prerequisite Review</div>
                  <div style={{ fontWeight: 700, color: isAcceptedFinding ? 'var(--accent-emerald)' : 'var(--accent-rose)' }}>
                    {isAcceptedFinding ? '✓ Accepted by Reviewer' : '✗ Unreviewed (Required)'}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Finding Staleness</div>
                  <div style={{ fontWeight: 700, color: primaryFinding?.is_stale ? 'var(--accent-rose)' : 'var(--accent-emerald)' }}>
                    {primaryFinding?.is_stale ? '✗ Stale (Re-run needed)' : '✓ Fresh Non-Stale'}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Target Invoice Line</div>
                  <div className="font-mono" style={{ fontWeight: 700 }}>
                    {selectedLineId || 'line-1'}
                  </div>
                </div>
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: '1rem', marginBottom: '1.25rem' }}>
              <div>
                <label className="form-label">Credit Reason Code</label>
                <select
                  className="form-select"
                  value={creditReason}
                  onChange={(e) => setCreditReason(e.target.value)}
                >
                  <option value="RATE_CALCULATION_ERROR">RATE_CALCULATION_ERROR</option>
                  <option value="TIER_MISMATCH">TIER_MISMATCH</option>
                  <option value="EXEMPT_ENVIRONMENT_BILLED">EXEMPT_ENVIRONMENT_BILLED</option>
                  <option value="GOODWILL_ADJUSTMENT">GOODWILL_ADJUSTMENT</option>
                </select>
              </div>
              <div>
                <label className="form-label">Reviewer Reason Note</label>
                <input
                  type="text"
                  className="form-input"
                  value={creditNote}
                  onChange={(e) => setCreditNote(e.target.value)}
                  placeholder="Audit reason note..."
                />
              </div>
            </div>

            <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => handleApproveCredit(primaryFinding?.id, null)}
                disabled={!isAcceptedFinding || primaryFinding?.is_stale || actionLoading}
              >
                <Lock size={15} />
                <span>{actionLoading ? 'Locking & Approving...' : 'Approve Credit Under Row Lock'}</span>
              </button>
            </div>
          </div>

          <div className="table-container">
            <table>
              <thead>
                <tr>
                  <th>Credit ID</th>
                  <th>Amount</th>
                  <th>Reason Code</th>
                  <th>Idempotency Key</th>
                  <th>Approved By</th>
                  <th>Timestamp</th>
                </tr>
              </thead>
              <tbody>
                {credits.length === 0 ? (
                  <tr>
                    <td colSpan="6" style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-muted)' }}>
                      No credits approved yet for this case.
                    </td>
                  </tr>
                ) : (
                  credits.map((c) => (
                    <tr key={c.id}>
                      <td className="font-mono" style={{ color: 'var(--accent-cyan)' }}>{c.id}</td>
                      <td className="font-mono" style={{ fontWeight: 700, color: 'var(--accent-emerald)' }}>
                        ${(c.amount_cents / 100).toFixed(2)}
                      </td>
                      <td>{c.reason_code}</td>
                      <td className="font-mono" style={{ fontSize: '0.72rem' }}>
                        {c.idempotency_key?.slice(0, 16)}...
                      </td>
                      <td>{c.approved_by}</td>
                      <td style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                        {new Date(c.approved_at).toLocaleString()}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── TAB 5: Audit Trail ────────────────────────────────────────── */}
      {activeTab === 'timeline' && (
        <div className="glass-panel" style={{ padding: '1.5rem' }}>
          <h3 style={{ fontSize: '1.2rem', marginBottom: '0.4rem' }}>Immutable Append-Only Audit Trail</h3>
          <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '1.5rem' }}>
            Guaranteed by physical database triggers blocking UPDATE and DELETE statements on case_events.
          </p>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem' }}>
            {events.map((ev) => (
              <div 
                key={ev.id}
                className="glass-card"
                style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '1rem', borderLeft: '3px solid var(--accent-cyan)' }}
              >
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.25rem' }}>
                    <span className="badge badge-open" style={{ fontSize: '0.7rem' }}>
                      {ev.event_type}
                    </span>
                    <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                      by <strong style={{ color: '#fff' }}>{ev.actor}</strong>
                    </span>
                  </div>
                  <div className="font-mono" style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
                    {JSON.stringify(ev.details || {})}
                  </div>
                </div>
                <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
                  {new Date(ev.timestamp).toLocaleTimeString()}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Modals ────────────────────────────────────────────────────── */}
      <EvidenceModal
        isOpen={evidenceModalOpen}
        onClose={() => setEvidenceModalOpen(false)}
        caseId={caseId}
        lineId={selectedLineId}
        onEvidenceUploaded={loadAllCaseData}
      />

      {/* Human Review Modal */}
      {reviewModalOpen && (
        <div className="modal-overlay" onClick={() => setReviewModalOpen(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <h3 style={{ fontSize: '1.35rem', marginBottom: '0.5rem' }}>Human-in-the-Loop Review</h3>
            <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '1.25rem' }}>
              Accept, edit, or reject the AI finding. Raw AI text is permanently preserved for audit compliance.
            </p>

            <div className="form-group">
              <label className="form-label">Review Decision</label>
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                <button
                  type="button"
                  className={`btn btn-sm ${reviewAction === 'ACCEPT' ? 'btn-emerald' : 'btn-secondary'}`}
                  onClick={() => setReviewAction('ACCEPT')}
                >
                  <Check size={14} /> Accept
                </button>
                <button
                  type="button"
                  className={`btn btn-sm ${reviewAction === 'EDIT' ? 'btn-primary' : 'btn-secondary'}`}
                  onClick={() => setReviewAction('EDIT')}
                >
                  <Edit3 size={14} /> Edit
                </button>
                <button
                  type="button"
                  className={`btn btn-sm ${reviewAction === 'REJECT' ? 'btn-rose' : 'btn-secondary'}`}
                  onClick={() => setReviewAction('REJECT')}
                >
                  <XCircle size={14} /> Reject
                </button>
              </div>
            </div>

            {reviewAction === 'EDIT' && (
              <div className="form-group">
                <label className="form-label">Human Edited Text (Stored separately from AI text)</label>
                <textarea
                  className="form-textarea"
                  rows={4}
                  value={editedText}
                  onChange={(e) => setEditedText(e.target.value)}
                  required
                />
              </div>
            )}

            <div className="form-group">
              <label className="form-label">Reviewer Note / Justification</label>
              <input
                type="text"
                className="form-input"
                value={reviewNote}
                onChange={(e) => setReviewNote(e.target.value)}
              />
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem', marginTop: '1.5rem' }}>
              <button type="button" className="btn btn-secondary" onClick={() => setReviewModalOpen(false)}>
                Cancel
              </button>
              <button type="button" className="btn btn-primary" onClick={handleSubmitReview} disabled={actionLoading}>
                Submit Review
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
