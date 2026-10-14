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
  Check, 
  Edit3, 
  XCircle, 
  Lock, 
  Hash,
  AlertTriangle
} from 'lucide-react';
import { 
  getCase, 
  getCaseEvents, 
  runCalculation, 
  getCaseCalculations,
  triggerInvestigation, 
  getCaseInvestigations, 
  getCaseFindings, 
  reviewFinding, 
  approveCredit, 
  getCaseCredits,
  getCreditCap,
  transitionCase,
  getActiveRole
} from '../api/client';
import { formatCents } from '../utils/money';
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
  const [refreshing, setRefreshing] = useState(false);
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
  const [creditAmountDollars, setCreditAmountDollars] = useState('');
  const [selectedResolutionOptionId, setSelectedResolutionOptionId] = useState(null);
  const [creditReason, setCreditReason] = useState('RATE_CALCULATION_ERROR');
  const [creditNote, setCreditNote] = useState('Approved per confirmed calculation discrepancy');
  // Cap breakdown from API (Task 3)
  const [capInfo, setCapInfo] = useState(null);

  // Dynamic Role State (reactive to Navbar role switch)
  const [currentRole, setCurrentRole] = useState(getActiveRole());
  const isReviewer = currentRole === 'REVIEWER';

  useEffect(() => {
    const handleRoleChanged = (e) => {
      if (e.detail?.role) {
        setCurrentRole(e.detail.role);
      }
    };
    window.addEventListener('roleChanged', handleRoleChanged);
    return () => window.removeEventListener('roleChanged', handleRoleChanged);
  }, []);

  const loadAllCaseData = async (isInitial = false) => {
    try {
      if (isInitial || !caseData) {
        setLoading(true);
      } else {
        setRefreshing(true);
      }
      const [cData, cEvents, cFindings, cCredits, cInvs, cCalcs] = await Promise.all([
        getCase(caseId),
        getCaseEvents(caseId).catch(() => []),
        getCaseFindings(caseId).catch(() => []),
        getCaseCredits(caseId).catch(() => []),
        getCaseInvestigations(caseId).catch(() => []),
        getCaseCalculations(caseId).catch(() => []),
      ]);
      setCaseData(cData);
      setEvents(cEvents);
      setFindings(cFindings);
      setCredits(cCredits);
      if (cInvs && cInvs.length > 0) {
        setInvestigation(cInvs[0]);
      }
      if (cCalcs && cCalcs.length > 0) {
        setCalculation(cCalcs[0]);
      }
      if (cData.invoice_lines && cData.invoice_lines.length > 0) {
        const firstLine = cData.invoice_lines[0];
        setSelectedLineId((prev) => prev || firstLine.id);
        if (cCalcs && cCalcs.length > 0 && cCalcs[0].line_results) {
          const lr = cCalcs[0].line_results.find(r => r.line_id === firstLine.id);
          if (lr && lr.difference_cents < 0) {
            setCreditAmountDollars((Math.abs(lr.difference_cents) / 100).toFixed(2));
          }
        }
      }
    } catch (err) {
      onToast('error', err.message || 'Failed to load case data');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    if (caseId) {
      loadAllCaseData();
    }
  }, [caseId]);

  // Fetch credit cap from backend when selected line changes or after a credit approval
  useEffect(() => {
    if (caseId && selectedLineId) {
      getCreditCap(caseId, selectedLineId)
        .then(setCapInfo)
        .catch(() => setCapInfo(null));
    } else {
      setCapInfo(null);
    }
  }, [caseId, selectedLineId, credits.length]);

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
      const reason = err.data?.reason || err.data?.status_reason || err.message || 'Investigation run failed';
      onToast('error', `Investigation Failed (${err.status || 502}): ${reason}`);
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
      const targetLine = selectedLineId || caseData.invoice_lines[0]?.id;
      const payload = {
        case_id: caseId,
        invoice_line_id: targetLine,
        reason_code: creditReason,
        finding_id: findingId,
        resolution_option_id: optId || selectedResolutionOptionId || null,
        reason_note: creditNote,
      };
      if (creditAmountDollars && !isNaN(parseFloat(creditAmountDollars))) {
        payload.requested_amount_cents = Math.round(parseFloat(creditAmountDollars) * 100);
      }
      const res = await approveCredit(payload);
      onToast('success', `Credit approved for ${formatCents(res.amount_cents)} under lock`);
      await loadAllCaseData();
      setActiveTab('credits');
    } catch (err) {
      if (err.status === 409 || (err.message && err.message.toLowerCase().includes('already approved'))) {
        onToast('error', 'Credit already approved for this finding');
      } else {
        onToast('error', err.message || 'Credit approval failed');
      }
    } finally {
      setActionLoading(false);
    }
  };

  if (loading && !caseData) {
    return (
      <div style={{ textAlign: 'center', padding: '4rem', color: 'var(--text-muted)' }}>
        <div style={{ fontSize: '1.25rem', marginBottom: '0.5rem' }}>Loading dispute case details...</div>
        <div>Connecting to append-only audit trail</div>
      </div>
    );
  }




  return (
    <div>
      {/* â”€â”€ Breadcrumb & Navigation Bar â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */}
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

      {/* â”€â”€ Case Header Banner â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */}
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
              {formatCents(caseData.disputed_amount_cents)}
            </div>
            {refreshing && (
              <div style={{ fontSize: '0.72rem', color: 'var(--accent-cyan)', marginTop: '4px' }}>
                Syncing updates...
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Failed Investigation Warning Banner (Task 9h) */}
      {investigation?.status === 'FAILED' && (
        <div 
          style={{ 
            background: 'rgba(239, 68, 68, 0.12)', 
            border: '1px solid rgba(239, 68, 68, 0.4)', 
            borderRadius: 'var(--radius-md)', 
            padding: '1rem 1.25rem', 
            marginBottom: '1.5rem', 
            display: 'flex', 
            justifyContent: 'space-between', 
            alignItems: 'center', 
            flexWrap: 'wrap', 
            gap: '1rem' 
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <AlertTriangle size={20} color="var(--accent-rose)" />
            <div>
              <div style={{ fontWeight: 600, color: 'var(--accent-rose)', fontSize: '0.92rem' }}>
                AI analysis unavailable - deterministic results below. Retry
              </div>
              {investigation.status_reason && (
                <div style={{ fontSize: '0.75rem', color: '#cbd5e1', marginTop: '2px' }}>
                  Reason: {investigation.status_reason}
                </div>
              )}
            </div>
          </div>
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={handleTriggerInvestigation}
            disabled={actionLoading}
            style={{ borderColor: 'var(--accent-rose)', color: '#fca5a5' }}
          >
            Retry
          </button>
        </div>
      )}

      {/* ── Tab Navigation ──────────────────────────────────────────────── */}
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

      {/* â”€â”€ TAB 1: Deterministic Engine â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */}
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
              <>
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
                      {formatCents(calculation.total_original_billed_cents)}
                    </div>
                  </div>
                  <div>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Recalculated Total</div>
                    <div className="font-mono" style={{ fontWeight: 700 }}>
                      {formatCents(calculation.total_recalculated_cents)}
                    </div>
                  </div>
                  <div>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Total Discrepancy</div>
                    <div className="font-mono" style={{ fontWeight: 800, color: calculation.total_difference_cents < 0 ? 'var(--accent-rose)' : 'var(--accent-emerald)' }}>
                      {formatDifference(calculation.total_difference_cents)}
                    </div>
                  </div>
                </div>

                {/* Per-Line Recalculation Breakdown Table */}
                {calculation.line_results && calculation.line_results.length > 0 && (
                  <div style={{ marginTop: '1.75rem' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.85rem' }}>
                      <h4 style={{ fontSize: '1.05rem', fontWeight: 600, color: '#f1f5f9' }}>
                        Per-Line Recalculated vs. Original Invoice Items
                      </h4>
                      <span className="font-mono" style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                        Hash: {calculation.result_hash?.slice(0, 16)}...
                      </span>
                    </div>

                    <div className="table-container">
                      <table>
                        <thead>
                          <tr>
                            <th>Line Item</th>
                            <th>Original Billed</th>
                            <th>Recalculated</th>
                            <th>Discrepancy</th>
                            <th>Classification</th>
                            <th>Billable Qty</th>
                            <th>Engine Explanation & Slabs</th>
                          </tr>
                        </thead>
                        <tbody>
                          {calculation.line_results.map((lr) => {
                            const lineMeta = caseData?.invoice_lines?.find((l) => l.id === lr.line_id);
                            const isOvercharge = lr.difference_cents < 0;
                            const isUndercharge = lr.difference_cents > 0;
                            return (
                              <tr key={lr.id || lr.line_id}>
                                <td>
                                  <div className="font-mono" style={{ fontWeight: 600, color: 'var(--accent-cyan)' }}>
                                    {lr.line_id}
                                  </div>
                                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                                    {lineMeta?.description || 'Invoice Line'}
                                  </div>
                                  <div className="font-mono" style={{ fontSize: '0.68rem', color: '#64748b' }}>
                                    Rule: {lr.rule_id} | Anchor: {lr.result_id}
                                  </div>
                                </td>
                                <td className="font-mono" style={{ fontWeight: 600 }}>
                                  {formatCents(lr.original_amount_cents)}
                                </td>
                                <td className="font-mono" style={{ fontWeight: 700, color: '#38bdf8' }}>
                                  {formatCents(lr.recalculated_amount_cents)}
                                  {(lr.finding_type === 'CONTRACT_AMBIGUITY' || (lr.interpretations && lr.interpretations.length > 0)) && (
                                    <div style={{ fontSize: '0.68rem', color: '#fbbf24', fontWeight: 600, marginTop: '2px' }}>
                                      *Not final — human review required
                                    </div>
                                  )}
                                </td>
                                <td className="font-mono" style={{ fontWeight: 800, color: isOvercharge ? 'var(--accent-rose)' : isUndercharge ? 'var(--accent-amber)' : 'var(--accent-emerald)' }}>
                                  {formatDifference(lr.difference_cents)}
                                </td>
                                <td>
                                  <span className={`badge ${lr.finding_type === 'CONFIRMED_CALCULATION_DISCREPANCY' ? 'badge-stale' : lr.finding_type === 'CONTRACT_AMBIGUITY' ? 'badge-awaiting' : lr.finding_type === 'INSUFFICIENT_DATA' ? 'badge-stale' : 'badge-resolved'}`}>
                                    {lr.finding_type}
                                  </span>
                                </td>
                                <td className="font-mono" style={{ fontSize: '0.82rem' }}>
                                  {Number(lr.quantity_used || 0).toLocaleString()}
                                  {lr.exempt_quantity > 0 && (
                                    <div style={{ fontSize: '0.68rem', color: 'var(--accent-emerald)' }}>
                                      ({Number(lr.exempt_quantity)} exempt)
                                    </div>
                                  )}
                                </td>
                                <td style={{ fontSize: '0.8rem', color: '#cbd5e1', maxWidth: '320px' }}>
                                  <div>{lr.explanation}</div>
                                  {lr.interpretations && lr.interpretations.length > 0 && (
                                    <div style={{ marginTop: '0.45rem', padding: '0.45rem', background: 'rgba(245, 158, 11, 0.08)', border: '1px solid rgba(245, 158, 11, 0.25)', borderRadius: '4px' }}>
                                      <div style={{ fontSize: '0.72rem', fontWeight: 700, color: '#fbbf24', marginBottom: '4px' }}>
                                        ⚠ Competing Interpretations — Human Review Required:
                                      </div>
                                      {lr.interpretations.map((interp, idx) => {
                                        const diff = (interp.recalculated_amount_cents != null && lr.original_amount_cents != null)
                                          ? (interp.recalculated_amount_cents - lr.original_amount_cents)
                                          : null;
                                        return (
                                          <div key={idx} style={{ fontSize: '0.72rem', color: '#fef3c7', marginBottom: '4px' }}>
                                            <strong>{interp.interpretation_id || `Interp ${idx+1}`}:</strong>{' '}
                                            <span style={{ fontWeight: 600 }}>{formatCents(interp.recalculated_amount_cents)}</span>
                                            {diff != null && (
                                              <span style={{ marginLeft: '4px', color: diff < 0 ? '#f87171' : diff > 0 ? '#fbbf24' : '#86efac' }}>
                                                ({formatDifference(diff)})
                                              </span>
                                            )}
                                            {interp.assumptions && interp.assumptions.length > 0 && (
                                              <div style={{ marginTop: '2px', paddingLeft: '0.75rem', color: '#94a3b8', fontSize: '0.68rem' }}>
                                                {interp.assumptions.map((a, ai) => <div key={ai}>• {a}</div>)}
                                              </div>
                                            )}
                                          </div>
                                        );
                                      })}
                                    </div>
                                  )}
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </>
            ) : (
              <div style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-muted)' }}>
                Click "Run Billing Engine" to execute calculation against current evidence.
              </div>
            )}
          </div>
        </div>
      )}

      {/* â”€â”€ TAB 2: AI Investigation (LangGraph) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */}
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
                {investigation.token_usage?.provider && (
                  <span
                    className="badge"
                    style={{
                      background: 'rgba(99, 102, 241, 0.15)',
                      color: '#818cf8',
                      border: '1px solid rgba(99, 102, 241, 0.35)',
                      textTransform: 'none',
                      fontSize: '0.75rem',
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '0.35rem',
                    }}
                  >
                    <span>LLM:</span>
                    <strong>{investigation.token_usage.provider}</strong>
                    {investigation.token_usage.model && (
                      <span style={{ opacity: 0.8 }}>({investigation.token_usage.model})</span>
                    )}
                  </span>
                )}
                {investigation.token_usage && (
                  <span className="citation-pill">
                    Tokens: {investigation.token_usage.total_tokens || 0}
                  </span>
                )}
              </div>
            )}

            {findings.length > 0 ? (
              <>
                {(() => {
                  const groups = {};
                  findings.forEach((f) => {
                    const matchingLr = calculation?.line_results?.find(lr => lr.id === f.calculation_line_result_id);
                    const lineKey = matchingLr?.line_id || (f.calculation_line_result_id ? `Result #${f.calculation_line_result_id}` : 'General / Case-Wide');
                    if (!groups[lineKey]) groups[lineKey] = [];
                    groups[lineKey].push(f);
                  });

                  return Object.entries(groups).map(([lineKey, groupFindings]) => (
                    <div key={lineKey} style={{ marginBottom: '2rem' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', marginBottom: '0.85rem', paddingBottom: '0.35rem', borderBottom: '1px solid var(--border-subtle)' }}>
                        <span style={{ fontSize: '0.88rem', fontWeight: 700, color: 'var(--accent-cyan)' }}>
                          Line Item: {lineKey}
                        </span>
                        <span className="badge badge-resolved" style={{ fontSize: '0.7rem' }}>
                          {groupFindings.length} {groupFindings.length === 1 ? 'Finding' : 'Findings'}
                        </span>
                      </div>
                      {groupFindings.map((f) => (
                        <div key={f.id} className="glass-card" style={{ marginBottom: '1.25rem', borderColor: f.is_stale ? 'var(--accent-rose)' : 'var(--border-subtle)' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.75rem', flexWrap: 'wrap', gap: '0.5rem' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                        <span className="badge badge-open">
                          {f.finding_type}
                        </span>
                        {f.is_stale && (
                          <span className="badge badge-stale">STALE EVIDENCE</span>
                        )}
                        {f.calculation_line_result_id && (
                          <span className="font-mono" style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                            Anchor Result #{f.calculation_line_result_id}
                          </span>
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

                    {/* Stale Finding Reason Alert */}
                    {f.is_stale && (
                      <div style={{ padding: '0.65rem 0.85rem', background: 'rgba(244, 63, 94, 0.1)', border: '1px solid var(--accent-rose)', borderRadius: 'var(--radius-sm)', marginBottom: '0.85rem', fontSize: '0.82rem', color: '#fb7185' }}>
                        <strong>Stale Finding Notice:</strong> {f.stale_reason || 'Evidence snapshot changed after this finding was generated. Rerun investigation to produce an updated finding.'}
                      </div>
                    )}

                    <div style={{ marginBottom: '1rem' }}>
                      <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase', marginBottom: '0.25rem' }}>
                        Synthesized AI Finding & Narrative
                      </div>
                      <p style={{ fontSize: '0.92rem', lineHeight: 1.6, color: '#e2e8f0', margin: 0 }}>
                        {f.narrative || f.raw_ai_text}
                      </p>
                      {f.narrative && f.raw_ai_text && f.narrative !== f.raw_ai_text && (
                        <div style={{ marginTop: '0.5rem', fontSize: '0.78rem', color: 'var(--text-muted)', fontStyle: 'italic' }}>
                          Original model text: &ldquo;{f.raw_ai_text}&rdquo;
                        </div>
                      )}
                    </div>

                    {/* Why this was downgraded / Validation Notes Box */}
                    {f.validation_notes && f.validation_notes.length > 0 && (
                      <div
                        style={{
                          padding: '0.75rem 1rem',
                          background: 'rgba(234, 179, 8, 0.1)',
                          border: '1px solid rgba(234, 179, 8, 0.3)',
                          borderRadius: 'var(--radius-sm)',
                          marginBottom: '0.85rem',
                          fontSize: '0.82rem',
                        }}
                      >
                        <div style={{ fontWeight: 700, color: '#fbbf24', marginBottom: '0.35rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                          <AlertTriangle size={14} />
                          <span>Why this was downgraded / Validation Notes</span>
                        </div>
                        <ul style={{ paddingLeft: '1.25rem', color: '#fef08a', margin: 0 }}>
                          {f.validation_notes.map((note, idx) => (
                            <li key={idx}>{note}</li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {/* Verified Facts */}
                    {f.verified_facts && f.verified_facts.length > 0 && (
                      <div style={{ marginBottom: '0.75rem' }}>
                        <div style={{ fontSize: '0.75rem', color: 'var(--accent-emerald)', fontWeight: 600, textTransform: 'uppercase', marginBottom: '0.35rem' }}>
                          Verified Facts
                        </div>
                        <ul style={{ paddingLeft: '1.25rem', fontSize: '0.82rem', color: 'var(--text-secondary)', margin: 0 }}>
                          {f.verified_facts.map((fact, idx) => (
                            <li key={idx}>{typeof fact === 'string' ? fact : JSON.stringify(fact)}</li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {/* Possible Explanations */}
                    {f.possible_explanations && f.possible_explanations.length > 0 && (
                      <div style={{ marginBottom: '0.75rem' }}>
                        <div style={{ fontSize: '0.75rem', color: '#38bdf8', fontWeight: 600, textTransform: 'uppercase', marginBottom: '0.35rem' }}>
                          Possible Root-Cause Explanations
                        </div>
                        <ul style={{ paddingLeft: '1.25rem', fontSize: '0.82rem', color: 'var(--text-secondary)', margin: 0 }}>
                          {f.possible_explanations.map((exp, idx) => (
                            <li key={idx}>{typeof exp === 'string' ? exp : JSON.stringify(exp)}</li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {/* Open Questions */}
                    {f.open_questions && f.open_questions.length > 0 && (
                      <div style={{ marginBottom: '0.75rem' }}>
                        <div style={{ fontSize: '0.75rem', color: '#fbbf24', fontWeight: 600, textTransform: 'uppercase', marginBottom: '0.35rem' }}>
                          Open Questions for Audit
                        </div>
                        <ul style={{ paddingLeft: '1.25rem', fontSize: '0.82rem', color: 'var(--text-secondary)', margin: 0 }}>
                          {f.open_questions.map((q, idx) => (
                            <li key={idx}>{typeof q === 'string' ? q : JSON.stringify(q)}</li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {/* Missing Evidence Questions */}
                    {f.missing_evidence_questions && f.missing_evidence_questions.length > 0 && (
                      <div style={{ marginBottom: '0.75rem' }}>
                        <div style={{ fontSize: '0.75rem', color: '#f43f5e', fontWeight: 600, textTransform: 'uppercase', marginBottom: '0.35rem' }}>
                          Missing Evidence Required
                        </div>
                        <ul style={{ paddingLeft: '1.25rem', fontSize: '0.82rem', color: 'var(--text-secondary)', margin: 0 }}>
                          {f.missing_evidence_questions.map((me, idx) => (
                            <li key={idx}>{typeof me === 'string' ? me : JSON.stringify(me)}</li>
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
                        {f.citation_validation_passed ? 'âœ“ Citations Verified' : 'âœ— Verification Failed'}
                      </span>
                    </div>

                    {/* Full Review History & Human Edits */}
                    {f.reviews && f.reviews.length > 0 && (
                      <div style={{ marginTop: '1.25rem', borderTop: '1px solid var(--border-subtle)', paddingTop: '0.85rem' }}>
                        <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase', marginBottom: '0.5rem' }}>
                          Audited Human Review History ({f.reviews.length})
                        </div>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
                          {f.reviews.map((rev) => (
                            <div key={rev.id} style={{ background: 'rgba(255, 255, 255, 0.02)', padding: '0.65rem 0.85rem', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
                              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.35rem', flexWrap: 'wrap', gap: '0.5rem' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                  <span className={`badge ${rev.action === 'ACCEPT' ? 'badge-resolved' : rev.action === 'EDIT' ? 'badge-open' : 'badge-stale'}`} style={{ fontSize: '0.68rem' }}>
                                    {rev.action}
                                  </span>
                                  <span style={{ fontSize: '0.78rem', fontWeight: 600, color: '#f1f5f9' }}>{rev.reviewer}</span>
                                </div>
                                <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                                  {new Date(rev.reviewed_at || rev.created_at).toLocaleString()}
                                </span>
                              </div>
                              {rev.note && (
                                <div style={{ fontSize: '0.78rem', color: '#94a3b8', fontStyle: 'italic', marginBottom: rev.edited_text ? '0.35rem' : '0' }}>
                                  Note: "{rev.note}"
                                </div>
                              )}
                              {rev.edited_text && (
                                <div style={{ marginTop: '0.45rem', padding: '0.55rem 0.75rem', background: 'rgba(56, 189, 248, 0.06)', borderLeft: '3px solid var(--accent-cyan)', borderRadius: '2px', fontSize: '0.82rem', color: '#e0f2fe', lineHeight: '1.45' }}>
                                  <strong style={{ color: '#38bdf8' }}>Reviewer Edited Text: </strong>
                                  {rev.edited_text}
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            ));
          })()}

                {/* Resolution Options Proposed by Agent */}
                {investigation?.resolution_options && investigation.resolution_options.length > 0 && (
                  <div style={{ marginTop: '1.75rem', borderTop: '1px solid var(--border-subtle)', paddingTop: '1.25rem' }}>
                    <h4 style={{ fontSize: '1.05rem', fontWeight: 600, color: '#f1f5f9', marginBottom: '0.85rem' }}>
                      Proposed Resolution Options ({investigation.resolution_options.length})
                    </h4>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '1rem' }}>
                      {investigation.resolution_options.map((opt) => (
                        <div key={opt.id} className="glass-card" style={{ padding: '1rem', display: 'flex', flexDirection: 'column', justifyContent: 'space-between', border: '1px solid var(--border-subtle)' }}>
                          <div>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                              <span className={`badge ${opt.option_type === 'RECOMMEND_CREDIT' ? 'badge-resolved' : opt.option_type === 'REQUEST_AMENDMENT' ? 'badge-awaiting' : 'badge-open'}`}>
                                {opt.option_type}
                              </span>
                              {opt.is_stale && <span className="badge badge-stale">STALE</span>}
                            </div>
                            <p style={{ fontSize: '0.85rem', color: '#cbd5e1', lineHeight: '1.45', marginBottom: '0.75rem' }}>
                              {opt.description}
                            </p>
                            {opt.calculation_line_result_id && (
                              <div className="font-mono" style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginBottom: '0.5rem' }}>
                                Linked Calculation Result #{opt.calculation_line_result_id}
                              </div>
                            )}
                          </div>
                          {opt.option_type === 'RECOMMEND_CREDIT' && (
                            <button
                              type="button"
                              className="btn btn-primary btn-sm"
                              style={{ marginTop: '0.5rem', width: '100%' }}
                              onClick={() => {
                                setSelectedResolutionOptionId(opt.id);
                                if (opt.calculation_line_result_id && calculation?.line_results) {
                                  const targetLr = calculation.line_results.find(lr => lr.id === opt.calculation_line_result_id);
                                  if (targetLr) {
                                    setSelectedLineId(targetLr.line_id);
                                    if (targetLr.difference_cents < 0) {
                                      setCreditAmountDollars((Math.abs(targetLr.difference_cents) / 100).toFixed(2));
                                    }
                                  }
                                }
                                setActiveTab('credits');
                              }}
                            >
                              Apply & Approve Credit
                            </button>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </>
            ) : (
              <div style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-muted)' }}>
                No findings generated yet. Trigger an investigation to analyze this dispute.
              </div>
            )}
          </div>
        </div>
      )}

      {/* â”€â”€ TAB 3: Invoice Lines & Rules â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */}
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
                    <td className="font-mono">{formatCents(l.original_amount_cents)}</td>
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
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {caseData.contract_rules.map((r) => (
                  <tr key={r.id} style={{ opacity: r.is_active === false ? 0.6 : 1 }}>
                    <td className="font-mono">{r.id}</td>
                    <td className="font-mono">{r.line_id}</td>
                    <td><span className="badge badge-open">{r.rule_type}</span></td>
                    <td className="font-mono">{r.rate_cents}¢</td>
                    <td className="font-mono">{r.minimum_commit_cents ? formatCents(r.minimum_commit_cents) : 'None'}</td>
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
      )}

      {/* ── TAB 4: Credit Issuance ────────────────────────────────────── */}
      {activeTab === 'credits' && (() => {
        const currentLineResult = calculation?.line_results?.find(lr => lr.line_id === selectedLineId);
        // Find finding that matches the selected line
        const lineFinding = findings.find(f => f.calculation_line_result_id === currentLineResult?.id)
          || (findings.length === 1 && !findings[0].calculation_line_result_id ? findings[0] : null);
        const latestReview = lineFinding?.reviews && lineFinding.reviews.length > 0 ? lineFinding.reviews[0] : null;
        const isAcceptedFinding = latestReview?.action === 'ACCEPT';

        // Cap comes from the backend API (compute_remaining_cap) so it matches enforcement exactly
        const eligibleOverchargeCents = capInfo?.eligible_cents ?? (currentLineResult && currentLineResult.difference_cents < 0 ? Math.abs(currentLineResult.difference_cents) : 0);
        const priorLineCreditsCents = capInfo?.prior_credits_cents ?? 0;
        const lineAdjustmentsCents = capInfo?.line_adjustments_cents ?? 0;
        const caseWideAdjustmentsCents = capInfo?.case_wide_adjustments_cents ?? 0;
        const remainingLineCapCents = capInfo?.remaining_cap_cents ?? Math.max(0, eligibleOverchargeCents - priorLineCreditsCents);

        return (
          <div>
            <div className="glass-panel" style={{ padding: '1.5rem', marginBottom: '1.5rem' }}>
              <h3 style={{ fontSize: '1.2rem', marginBottom: '0.4rem' }}>Concurrency-Safe Credit Approval</h3>
              <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '1.5rem' }}>
                Enforces PostgreSQL row-level locking (SELECT FOR UPDATE) and SQLite BEGIN IMMEDIATE to guarantee zero double-crediting.
              </p>

              <div style={{ background: 'rgba(255, 255, 255, 0.02)', padding: '1.25rem', borderRadius: 'var(--radius-md)', marginBottom: '1.5rem', border: '1px solid var(--border-subtle)' }}>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: '1rem' }}>
                  <div>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Latest Review Decision ({selectedLineId})</div>
                    <div style={{ fontWeight: 700, color: isAcceptedFinding ? 'var(--accent-emerald)' : 'var(--accent-rose)' }}>
                      {isAcceptedFinding ? `✓ ${latestReview.action} by ${latestReview.reviewer}` : '✗ Must be ACCEPT'}
                    </div>
                  </div>
                  <div>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Finding Staleness</div>
                    <div style={{ fontWeight: 700, color: lineFinding?.is_stale ? 'var(--accent-rose)' : 'var(--accent-emerald)' }}>
                      {lineFinding?.is_stale ? '✗ Stale (Re-run needed)' : '✓ Fresh Non-Stale'}
                    </div>
                  </div>
                  <div>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Eligible Overcharge</div>
                    <div className="font-mono" style={{ fontWeight: 700, color: 'var(--accent-cyan)' }}>
                      {formatCents(eligibleOverchargeCents)}
                    </div>
                  </div>
                  <div>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Prior Approved Credits</div>
                    <div className="font-mono" style={{ fontWeight: 700, color: priorLineCreditsCents > 0 ? 'var(--accent-amber)' : 'var(--text-muted)' }}>
                      {formatCents(priorLineCreditsCents)}
                    </div>
                  </div>
                  <div>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Prior Line Adjustments</div>
                    <div className="font-mono" style={{ fontWeight: 700, color: lineAdjustmentsCents > 0 ? 'var(--accent-amber)' : 'var(--text-muted)' }}>
                      {formatCents(lineAdjustmentsCents)}
                    </div>
                  </div>
                  {caseWideAdjustmentsCents > 0 && (
                    <div>
                      <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Case-Wide Adjustments</div>
                      <div className="font-mono" style={{ fontWeight: 700, color: 'var(--accent-amber)' }}>
                        {formatCents(caseWideAdjustmentsCents)}
                      </div>
                    </div>
                  )}
                  <div>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Remaining Line Cap</div>
                    <div className="font-mono" style={{ fontWeight: 800, color: remainingLineCapCents > 0 ? 'var(--accent-emerald)' : 'var(--accent-rose)' }}>
                      {formatCents(remainingLineCapCents)}
                    </div>
                  </div>
                </div>
              </div>

              {/* Line picker & Amount Input */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '1rem', marginBottom: '1.25rem' }}>
                <div>
                  <label className="form-label">Target Disputed Invoice Line</label>
                  <select
                    className="form-select"
                    value={selectedLineId}
                    onChange={(e) => {
                      const newLineId = e.target.value;
                      setSelectedLineId(newLineId);
                      const targetLr = calculation?.line_results?.find(r => r.line_id === newLineId);
                      if (targetLr && targetLr.difference_cents < 0) {
                        const prior = credits.filter(c => c.invoice_line_id === newLineId).reduce((s, c) => s + (c.amount_cents || 0), 0);
                        const rem = Math.max(0, Math.abs(targetLr.difference_cents) - prior);
                        setCreditAmountDollars((rem / 100).toFixed(2));
                      }
                    }}
                  >
                    {caseData?.invoice_lines?.map((line) => (
                      <option key={line.id} value={line.id}>
                        {line.id} — {line.description} ({formatCents(line.original_amount_cents)})
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="form-label">Approved Credit Amount ($ USD)</label>
                  <input
                    type="number"
                    step="0.01"
                    min="0.01"
                    className="form-input"
                    value={creditAmountDollars}
                    onChange={(e) => setCreditAmountDollars(e.target.value)}
                    placeholder="e.g. 25.00"
                  />
                  <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>
                    Defaults to remaining cap: {formatCents(remainingLineCapCents)}
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

              {(() => {
                const findingLineResult = calculation?.line_results?.find(lr => lr.id === lineFinding?.calculation_line_result_id);
                const targetFindingLineId = findingLineResult?.line_id;
                const isLineMismatch = Boolean(targetFindingLineId && selectedLineId && targetFindingLineId !== selectedLineId);

                let disableReason = null;
                if (!lineFinding) {
                  disableReason = `No finding available for line ${selectedLineId}`;
                } else if (lineFinding.is_stale) {
                  disableReason = 'Finding is stale — run billing engine and investigation first';
                } else if (!isAcceptedFinding) {
                  disableReason = `Latest review decision for ${selectedLineId} must be ACCEPT (currently: ${latestReview?.action || 'unreviewed'})`;
                } else if (isLineMismatch) {
                  disableReason = `Selected line (${selectedLineId}) does not match finding line (${targetFindingLineId})`;
                } else if (remainingLineCapCents <= 0) {
                  disableReason = 'Remaining allowable credit cap is $0.00';
                }

                const matchingOption = resolutionOptions.find(o => o.calculation_line_result_id === lineFinding?.calculation_line_result_id && o.option_type === 'RECOMMEND_CREDIT')
                  || resolutionOptions.find(o => o.id === selectedResolutionOptionId)
                  || resolutionOptions[0];

                return (
                  <div style={{ display: 'flex', gap: '1rem', alignItems: 'center', flexWrap: 'wrap' }}>
                    <button
                      type="button"
                      className="btn btn-primary"
                      onClick={() => handleApproveCredit(lineFinding?.id, matchingOption?.id || selectedResolutionOptionId)}
                      disabled={Boolean(disableReason) || actionLoading}
                    >
                      <Lock size={15} />
                      <span>{actionLoading ? 'Locking & Approving...' : 'Approve Credit Under Row Lock'}</span>
                    </button>
                    {disableReason && (
                      <span style={{ fontSize: '0.8rem', color: '#f87171', fontWeight: 600 }}>
                        ⚠ {disableReason}
                      </span>
                    )}
                  </div>
                );
              })()}
            </div>

            <div className="table-container">
              <table>
                <thead>
                  <tr>
                    <th>Credit ID</th>
                    <th>Target Line</th>
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
                      <td colSpan="7" style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-muted)' }}>
                        No credits approved yet for this case.
                      </td>
                    </tr>
                  ) : (
                    credits.map((c) => (
                      <tr key={c.id}>
                        <td className="font-mono" style={{ color: 'var(--accent-cyan)' }}>{c.id}</td>
                        <td className="font-mono">{c.invoice_line_id}</td>
                        <td className="font-mono" style={{ fontWeight: 700, color: 'var(--accent-emerald)' }}>
                          {formatCents(c.amount_cents)}
                        </td>
                        <td>{c.reason_code}</td>
                        <td className="font-mono" style={{ fontSize: '0.72rem' }}>
                          {c.idempotency_key?.slice(0, 16)}...
                        </td>
                        <td>{c.approved_by}</td>
                        <td style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                          {new Date(c.approved_at || c.created_at).toLocaleString()}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        );
      })()}

      {/* â”€â”€ TAB 5: Audit Trail â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */}
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
                  {new Date(ev.created_at || ev.timestamp).toLocaleString()}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* â”€â”€ Modals â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */}
      <EvidenceModal
        isOpen={evidenceModalOpen}
        onClose={() => setEvidenceModalOpen(false)}
        caseId={caseId}
        lineId={selectedLineId}
        contractRules={caseData?.contract_rules || []}
        invoiceLines={caseData?.invoice_lines || []}
        onEvidenceUploaded={loadAllCaseData}
      />

      {/* Human Review Modal */}
      {reviewModalOpen && (
        <div
          className="modal-overlay"
          onClick={() => setReviewModalOpen(false)}
          onKeyDown={(e) => { if (e.key === 'Escape') setReviewModalOpen(false); }}
        >
          <div
            className="modal-content"
            role="dialog"
            aria-modal="true"
            aria-labelledby="review-modal-title"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 id="review-modal-title" style={{ fontSize: '1.35rem', marginBottom: '0.5rem' }}>Human-in-the-Loop Review</h3>
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

