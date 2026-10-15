import React, { useEffect, useState, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { 
  ArrowLeft, 
  Upload, 
  Bot, 
  ShieldCheck, 
  FileText, 
  Calculator, 
  History, 
  Check, 
  Edit3, 
  XCircle, 
  AlertTriangle,
  RefreshCw,
  X
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
import { formatCents, formatDifference, centsToDollarString } from '../utils/money';
import EvidenceModal from './EvidenceModal';
import EngineTab from './case-tabs/EngineTab';
import InvestigationTab from './case-tabs/InvestigationTab';
import LinesTab from './case-tabs/LinesTab';
import CreditsTab from './case-tabs/CreditsTab';
import TimelineTab from './case-tabs/TimelineTab';

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

  // Request Information Modal State
  const [requestInfoModalOpen, setRequestInfoModalOpen] = useState(false);
  const [requestInfoNote, setRequestInfoNote] = useState('');

  // Credit Approval State
  const [selectedLineId, setSelectedLineId] = useState('');
  const [creditAmountDollars, setCreditAmountDollars] = useState('');
  const [selectedResolutionOptionId, setSelectedResolutionOptionId] = useState(null);
  const [creditReason, setCreditReason] = useState('RATE_CALCULATION_ERROR');
  const [creditNote, setCreditNote] = useState('Approved per confirmed calculation discrepancy');
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

  const loadAllCaseData = useCallback(async (isInitial = false) => {
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
      }
    } catch (err) {
      onToast('error', err.message || 'Failed to load case data');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [caseId, onToast]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    let ignore = false;
    if (caseId) {
      Promise.resolve().then(() => {
        if (!ignore) {
          loadAllCaseData(true);
        }
      });
    }
    return () => {
      ignore = true;
    };
  }, [caseId, loadAllCaseData]);

  // Fetch credit cap from backend when selected line changes or after a credit approval
  useEffect(() => {
    if (caseId && selectedLineId) {
      getCreditCap(caseId, selectedLineId)
        .then((cap) => {
          setCapInfo(cap);
          if (cap && cap.approval_eligibility === 'ELIGIBLE' && (cap.remaining_cap > 0 || cap.remaining_cap_cents > 0)) {
            setCreditAmountDollars(centsToDollarString(cap.remaining_cap ?? cap.remaining_cap_cents));
          } else {
            setCreditAmountDollars('');
          }
        })
        .catch(() => {
          setCapInfo(null);
          setCreditAmountDollars('');
        });
    } else {
      Promise.resolve().then(() => {
        setCapInfo(null);
        setCreditAmountDollars('');
      });
    }
  }, [caseId, selectedLineId, credits.length]);

  // Transition status handler
  const handleTransition = async (targetStatus, customNote) => {
    if (!isReviewer) {
      onToast('error', 'HTTP 403 Forbidden: Only REVIEWER role can transition case status');
      return;
    }
    try {
      setActionLoading(true);
      await transitionCase(caseId, targetStatus, customNote || `Manual transition to ${targetStatus}`);
      onToast('success', `Case status updated to ${targetStatus}`);
      await loadAllCaseData();
    } catch (err) {
      onToast('error', err.message || 'Transition rejected');
    } finally {
      setActionLoading(false);
    }
  };

  // Request Info Modal Handlers
  const handleOpenRequestInfo = () => {
    if (!isReviewer) {
      onToast('error', 'HTTP 403 Forbidden: Only REVIEWER role can request information');
      return;
    }
    const questions = [];
    findings.forEach((f) => {
      if (Array.isArray(f.missing_evidence_questions)) {
        questions.push(...f.missing_evidence_questions);
      }
      if (Array.isArray(f.open_questions)) {
        questions.push(...f.open_questions);
      }
    });

    if (questions.length > 0) {
      setRequestInfoNote(
        `Requesting customer / internal telemetry clarifications:\n\n${questions
          .map((q, i) => `${i + 1}. ${typeof q === 'string' ? q : JSON.stringify(q)}`)
          .join('\n')}`
      );
    } else {
      setRequestInfoNote(
        `Please provide verified production telemetry logs and contractual documentation for billing period ${caseData?.billing_period_start || ''} to ${caseData?.billing_period_end || ''}.`
      );
    }
    setRequestInfoModalOpen(true);
  };

  const handleSubmitRequestInfo = async () => {
    if (!isReviewer) {
      onToast('error', 'HTTP 403 Forbidden: Only REVIEWER role can request information');
      return;
    }
    try {
      setActionLoading(true);
      await transitionCase(caseId, 'AWAITING_INFO', requestInfoNote);
      onToast('success', 'Case transitioned to AWAITING_INFO with evidence questions recorded');
      setRequestInfoModalOpen(false);
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
    } catch (err) {
      const reason = err.data?.reason || err.data?.status_reason || err.message || 'Investigation run failed';
      onToast('error', `Investigation Failed (${err.status || 502}): ${reason}`);
      await loadAllCaseData();
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
      <div style={{ maxWidth: 1200, margin: '0 auto' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.75rem' }}>
          <div className="skeleton" style={{ width: 140, height: 34, borderRadius: 'var(--radius-full)' }} />
          <div className="skeleton" style={{ width: 220, height: 34, borderRadius: 'var(--radius-full)' }} />
        </div>
        <div className="card" style={{ padding: '2rem', marginBottom: '1.75rem' }}>
          <div className="skeleton" style={{ width: 120, height: 14, marginBottom: '1rem' }} />
          <div className="skeleton" style={{ width: '55%', height: 28, marginBottom: '0.75rem' }} />
          <div className="skeleton" style={{ width: '35%', height: 18, marginBottom: '1.5rem' }} />
          <div className="recalc-comparison-grid" style={{ marginTop: '1.5rem' }}>
            <div className="skeleton" style={{ height: 100 }} />
            <div className="skeleton" style={{ height: 100 }} />
            <div className="skeleton" style={{ height: 100 }} />
          </div>
        </div>
      </div>
    );
  }

  if (!caseData) {
    return (
      <div className="card" style={{ textAlign: 'center', padding: '4rem 1.5rem', maxWidth: 580, margin: '3rem auto' }}>
        <div className="eyebrow" style={{ justifyContent: 'center', marginBottom: '0.5rem', color: 'var(--status-rust)' }}>
          Dispute Record Unavailable
        </div>
        <h2 style={{ fontSize: '1.4rem', marginBottom: '0.5rem', color: 'var(--ink)' }}>
          Unable to Load Case Details
        </h2>
        <p style={{ fontSize: '0.85rem', color: 'var(--ink-secondary)', marginBottom: '1.5rem', lineHeight: 1.5 }}>
          Could not retrieve dispute record for <code className="font-mono">{caseId}</code>. Check API connectivity or verify your session token permissions.
        </p>
        <div style={{ display: 'flex', justifyContent: 'center', gap: '0.75rem' }}>
          <button type="button" className="btn btn-secondary" onClick={onBack}>
            Back to Disputes
          </button>
          <button type="button" className="btn btn-primary" onClick={() => loadAllCaseData(true)}>
            <RefreshCw size={14} />
            <span>Retry Connection</span>
          </button>
        </div>
      </div>
    );
  }

  return (
    <div>
      {/* ── Breadcrumb & Action Bar ────────────────────────────────────────── */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.75rem', flexWrap: 'wrap', gap: '1rem' }}>
        <button type="button" className="btn btn-secondary btn-sm" onClick={onBack}>
          <ArrowLeft size={14} />
          <span>Back to Disputes</span>
        </button>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
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
              onClick={handleOpenRequestInfo}
              disabled={actionLoading}
              data-testid="request-info-btn"
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

      {/* ── Case Header Banner ─────────────────────────────────────────────────── */}
      <div className="card" style={{ padding: '2rem', marginBottom: '2rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '1.5rem' }}>
          <div style={{ flex: 1, minWidth: 280 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem', marginBottom: '0.6rem', flexWrap: 'wrap' }}>
              <span className="font-mono" style={{ fontSize: '0.95rem', fontWeight: 700, color: 'var(--ink)' }}>
                {caseData.id}
              </span>
              <span className={`badge badge-${caseData.status.toLowerCase().replace('_', '')}`}>
                {caseData.status}
              </span>
              <span className="citation-pill" title="Cryptographic Evidence Snapshot Version">
                Snapshot v{caseData.evidence_version}
              </span>
            </div>
            <h1 style={{ fontSize: '1.85rem', marginBottom: '0.35rem', color: 'var(--ink)' }}>{caseData.title}</h1>
            <div style={{ fontSize: '0.9rem', color: 'var(--ink-secondary)' }}>
              Customer: <strong style={{ color: 'var(--ink)', fontWeight: 600 }}>{caseData.customer_name}</strong>
            </div>
            {caseData.dispute_description && (
              <div style={{ marginTop: '1rem', padding: '0.85rem 1.15rem', background: 'var(--surface-subtle)', borderRadius: 'var(--radius-sm)', borderLeft: '3px solid var(--ink)', fontSize: '0.85rem', color: 'var(--ink-secondary)', lineHeight: '1.5' }}>
                <span style={{ fontWeight: 600, color: 'var(--ink)', marginRight: '0.5rem' }}>Customer Statement:</span>
                "{caseData.dispute_description}"
              </div>
            )}
          </div>

          <div style={{ textAlign: 'right', minWidth: 180 }}>
            <div style={{ fontSize: '0.75rem', textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--ink-muted)', marginBottom: '0.25rem' }}>
              Disputed Exposure
            </div>
            <div style={{ fontSize: '2.4rem', fontWeight: 700, fontFamily: 'var(--font-serif)', color: 'var(--ink)', fontVariantNumeric: 'tabular-nums', lineHeight: 1.1 }}>
              {formatCents(caseData.disputed_amount_cents)}
            </div>
            {refreshing && (
              <div style={{ fontSize: '0.75rem', color: 'var(--accent)', marginTop: '6px' }}>
                Syncing audit state...
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Failed Investigation Warning Banner */}
      {investigation?.status === 'FAILED' && (
        <div 
          style={{ 
            background: 'var(--status-rust-bg)', 
            border: '1px solid var(--status-rust-border)', 
            borderRadius: 'var(--radius-md)', 
            padding: '1rem 1.25rem', 
            marginBottom: '1.75rem', 
            display: 'flex', 
            justifyContent: 'space-between', 
            alignItems: 'center', 
            flexWrap: 'wrap', 
            gap: '1rem' 
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <AlertTriangle size={18} color="var(--status-rust)" />
            <div>
              <div style={{ fontWeight: 600, color: 'var(--status-rust)', fontSize: '0.9rem' }}>
                Calculation completed — AI investigation unavailable, retry
              </div>
              {investigation.status_reason && (
                <div style={{ fontSize: '0.78rem', color: 'var(--ink-secondary)', marginTop: '2px' }}>
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
            style={{ borderColor: 'var(--status-rust-border)', color: 'var(--status-rust)' }}
          >
            Retry
          </button>
        </div>
      )}

      {/* ── Underline-Style Numbered Tabs ─────────────────────────────────── */}
      <div className="tabs-nav" role="tablist" aria-label="Dispute Investigation Sections">
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === 'engine'}
          className={`tab-btn ${activeTab === 'engine' ? 'active' : ''}`}
          onClick={() => setActiveTab('engine')}
        >
          <span className="tab-index">01</span>
          <Calculator size={15} />
          <span>Deterministic Engine</span>
        </button>

        <button
          type="button"
          role="tab"
          aria-selected={activeTab === 'investigation'}
          className={`tab-btn ${activeTab === 'investigation' ? 'active' : ''}`}
          onClick={() => setActiveTab('investigation')}
        >
          <span className="tab-index">02</span>
          <Bot size={15} />
          <span>AI Investigation</span>
        </button>

        <button
          type="button"
          role="tab"
          aria-selected={activeTab === 'lines'}
          className={`tab-btn ${activeTab === 'lines' ? 'active' : ''}`}
          onClick={() => setActiveTab('lines')}
        >
          <span className="tab-index">03</span>
          <FileText size={15} />
          <span>Line Items</span>
        </button>

        <button
          type="button"
          role="tab"
          aria-selected={activeTab === 'credits'}
          className={`tab-btn ${activeTab === 'credits' ? 'active' : ''}`}
          onClick={() => setActiveTab('credits')}
        >
          <span className="tab-index">04</span>
          <ShieldCheck size={15} />
          <span>Credit Issuance ({credits.length})</span>
        </button>

        <button
          type="button"
          role="tab"
          aria-selected={activeTab === 'timeline'}
          className={`tab-btn ${activeTab === 'timeline' ? 'active' : ''}`}
          onClick={() => setActiveTab('timeline')}
        >
          <span className="tab-index">05</span>
          <History size={15} />
          <span>Audit Trail ({events.length})</span>
        </button>
      </div>

      {/* ── TAB 1: Deterministic Engine ─────────────────────────────────── */}
      {activeTab === 'engine' && (
        <EngineTab
          calculation={calculation}
          caseData={caseData}
          currency={caseData?.currency || 'USD'}
          capLedger={capInfo}
          handleRunCalculation={handleRunCalculation}
          actionLoading={actionLoading}
          formatCents={formatCents}
          formatDifference={formatDifference}
        />
      )}

      {/* ── TAB 2: AI Investigation (LangGraph) ─────────────────────────── */}
      {activeTab === 'investigation' && (
        <InvestigationTab
          investigation={investigation}
          findings={findings}
          calculation={calculation}
          caseData={caseData}
          currency={caseData?.currency || 'USD'}
          capLedger={capInfo}
          actionLoading={actionLoading}
          handleTriggerInvestigation={handleTriggerInvestigation}
          setSelectedFinding={setSelectedFinding}
          setEditedText={setEditedText}
          setReviewModalOpen={setReviewModalOpen}
          setSelectedResolutionOptionId={setSelectedResolutionOptionId}
          setSelectedLineId={setSelectedLineId}
          setCreditAmountDollars={setCreditAmountDollars}
          setActiveTab={setActiveTab}
          onRequestInfo={handleOpenRequestInfo}
        />
      )}

      {/* ── TAB 3: Invoice Lines & Rules ────────────────────────────────── */}
      {activeTab === 'lines' && (
        <LinesTab
          caseData={caseData}
          formatCents={formatCents}
        />
      )}

      {/* ── TAB 4: Credit Issuance ──────────────────────────────────────── */}
      {activeTab === 'credits' && (
        <CreditsTab
          calculation={calculation}
          findings={findings}
          credits={credits}
          capInfo={capInfo}
          caseData={caseData}
          currency={caseData?.currency || 'USD'}
          selectedLineId={selectedLineId}
          setSelectedLineId={setSelectedLineId}
          creditAmountDollars={creditAmountDollars}
          setCreditAmountDollars={setCreditAmountDollars}
          creditReason={creditReason}
          setCreditReason={setCreditReason}
          creditNote={creditNote}
          setCreditNote={setCreditNote}
          resolutionOptions={investigation?.resolution_options || []}
          selectedResolutionOptionId={selectedResolutionOptionId}
          handleApproveCredit={handleApproveCredit}
          actionLoading={actionLoading}
          formatCents={formatCents}
        />
      )}

      {/* ── TAB 5: Audit Trail ──────────────────────────────────────────── */}
      {activeTab === 'timeline' && (
        <TimelineTab events={events} />
      )}

      {/* ── Modals ──────────────────────────────────────────────────────── */}
      <EvidenceModal
        isOpen={evidenceModalOpen}
        onClose={() => setEvidenceModalOpen(false)}
        caseId={caseId}
        lineId={selectedLineId}
        currency={caseData?.currency || 'USD'}
        contractRules={caseData?.contract_rules || []}
        invoiceLines={caseData?.invoice_lines || []}
        onEvidenceUploaded={loadAllCaseData}
      />

      {/* Human Review Modal */}
      {reviewModalOpen && typeof document !== 'undefined' && createPortal(
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
            <div className="modal-header">
              <h3 id="review-modal-title" className="modal-title">Human-in-the-Loop Review</h3>
              <button
                type="button"
                onClick={() => setReviewModalOpen(false)}
                className="btn btn-secondary btn-sm"
                aria-label="Close dialog"
                style={{ borderRadius: '50%', width: 30, height: 30, padding: 0 }}
              >
                <X size={15} />
              </button>
            </div>

            <div className="modal-body">
              <p style={{ fontSize: '0.85rem', color: 'var(--ink-secondary)', marginBottom: '1.25rem', lineHeight: 1.5 }}>
                Accept, edit, or reject the AI finding. Raw AI text is permanently preserved for audit compliance.
              </p>

              <div className="form-group">
                <label className="form-label">Review Decision</label>
                <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
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
                    className={`btn btn-sm ${reviewAction === 'REJECT' ? 'btn-destructive' : 'btn-secondary'}`}
                    onClick={() => setReviewAction('REJECT')}
                  >
                    <XCircle size={14} /> Reject
                  </button>
                </div>
              </div>

              {reviewAction === 'EDIT' && (
                <div className="form-group">
                  <label className="form-label" htmlFor="review-edited-text">Human Edited Text (Stored separately from AI text)</label>
                  <textarea
                    id="review-edited-text"
                    className="form-textarea"
                    rows={4}
                    value={editedText}
                    onChange={(e) => setEditedText(e.target.value)}
                    required
                  />
                </div>
              )}

              <div className="form-group" style={{ marginBottom: 0 }}>
                <label className="form-label" htmlFor="reviewer-note-input">Reviewer Note / Justification</label>
                <input
                  id="reviewer-note-input"
                  type="text"
                  className="form-input"
                  value={reviewNote}
                  onChange={(e) => setReviewNote(e.target.value)}
                />
              </div>
            </div>

            <div className="modal-footer">
              <button type="button" className="btn btn-secondary" onClick={() => setReviewModalOpen(false)}>
                Cancel
              </button>
              <button type="button" className="btn btn-primary" onClick={handleSubmitReview} disabled={actionLoading}>
                Submit Review
              </button>
            </div>
          </div>
        </div>,
        document.body
      )}

      {/* Request Information Modal */}
      {requestInfoModalOpen && typeof document !== 'undefined' && createPortal(
        <div
          className="modal-overlay"
          onClick={() => setRequestInfoModalOpen(false)}
          onKeyDown={(e) => { if (e.key === 'Escape') setRequestInfoModalOpen(false); }}
        >
          <div
            className="modal-content"
            role="dialog"
            aria-modal="true"
            aria-labelledby="request-info-modal-title"
            onClick={(e) => e.stopPropagation()}
            style={{ maxWidth: 580 }}
          >
            <div className="modal-header">
              <h3 id="request-info-modal-title" className="modal-title">Request Additional Information</h3>
              <button
                type="button"
                onClick={() => setRequestInfoModalOpen(false)}
                className="btn btn-secondary btn-sm"
                aria-label="Close dialog"
                style={{ borderRadius: '50%', width: 30, height: 30, padding: 0 }}
              >
                <X size={15} />
              </button>
            </div>

            <div className="modal-body">
              <p style={{ fontSize: '0.85rem', color: 'var(--ink-secondary)', marginBottom: '1.25rem', lineHeight: 1.5 }}>
                Transition case to <strong>AWAITING_INFO</strong> and record missing telemetry or contract questions into the immutable audit trail.
              </p>

              <div className="form-group" style={{ marginBottom: 0 }}>
                <label className="form-label" htmlFor="request-info-textarea-input">Questions & Required Information</label>
                <textarea
                  id="request-info-textarea-input"
                  className="form-textarea"
                  rows={6}
                  value={requestInfoNote}
                  onChange={(e) => setRequestInfoNote(e.target.value)}
                  placeholder="Detail the specific telemetry logs or contract amendments required..."
                  data-testid="request-info-textarea"
                  required
                />
              </div>
            </div>

            <div className="modal-footer">
              <button type="button" className="btn btn-secondary" onClick={() => setRequestInfoModalOpen(false)}>
                Cancel
              </button>
              <button
                type="button"
                className="btn btn-amber"
                onClick={handleSubmitRequestInfo}
                disabled={actionLoading || !requestInfoNote.trim()}
                data-testid="submit-request-info-btn"
              >
                Submit Request (Awaiting Info)
              </button>
            </div>
          </div>
        </div>,
        document.body
      )}
    </div>
  );
}
