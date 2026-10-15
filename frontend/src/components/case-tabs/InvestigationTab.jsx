import React from 'react';
import { Bot, AlertTriangle, Edit3, Hash, CheckCircle2, Database, ShieldAlert } from 'lucide-react';

export default function InvestigationTab({
  investigation,
  findings,
  calculation,
  caseData,
  actionLoading,
  handleTriggerInvestigation,
  setSelectedFinding,
  setEditedText,
  setReviewModalOpen,
  setSelectedResolutionOptionId,
  setSelectedLineId,
  setCreditAmountDollars,
  setActiveTab,
  onRequestInfo,
}) {
  const renderFindingCard = (f, isActive = true) => {
    const matchingLr = calculation?.line_results?.find((lr) => (f.invoice_line_id && lr.line_id === f.invoice_line_id) || (f.calculation_line_result_id && lr.id === f.calculation_line_result_id));
    const hasReviews = f.reviews && f.reviews.length > 0;
    const latestReview = hasReviews ? f.reviews[0] : null;

    return (
      <div
        key={f.id}
        className="card"
        style={{
          padding: '1.5rem',
          marginBottom: '1.25rem',
          borderColor: f.is_stale ? 'var(--status-rust-border)' : isActive ? 'var(--line)' : 'var(--line-subtle)',
          background: f.is_stale ? 'var(--status-rust-bg)' : 'var(--surface)',
          opacity: f.is_stale ? 0.9 : 1,
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.85rem', flexWrap: 'wrap', gap: '0.5rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
            <span className="badge badge-open">{f.finding_type}</span>
            {f.is_stale ? (
              <span className="badge badge-stale" data-testid="stale-finding-badge">
                STALE EVIDENCE / SUPERSEDED
              </span>
            ) : (
              <span className="badge badge-resolved" style={{ fontSize: '0.7rem' }}>
                ✓ ACTIONABLE FINDING
              </span>
            )}
            {f.invoice_line_id && (
              <span className="font-mono" style={{ fontSize: '0.75rem', color: 'var(--ink)' }}>
                Line: <strong>{f.invoice_line_id}</strong>
              </span>
            )}
            {f.calculation_line_result_id && (
              <span className="font-mono" style={{ fontSize: '0.75rem', color: 'var(--ink-muted)' }}>
                Anchor Result #{f.calculation_line_result_id}
              </span>
            )}
            <span className="font-mono" style={{ fontSize: '0.72rem', color: 'var(--ink-muted)' }}>
              Finding ID: #{f.id}
            </span>
          </div>

          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              disabled={f.is_stale}
              onClick={() => {
                setSelectedFinding(f);
                setEditedText(f.raw_ai_text || '');
                setReviewModalOpen(true);
              }}
              title={f.is_stale ? 'Finding is superseded by a newer run' : 'Review or edit finding'}
            >
              <Edit3 size={13} />
              <span>{hasReviews ? `Reviewed (${latestReview?.action})` : 'Human Review'}</span>
            </button>
          </div>
        </div>

        {/* Stale Finding Reason Alert */}
        {f.is_stale && (
          <div
            style={{
              padding: '0.65rem 0.85rem',
              background: 'var(--status-rust-bg)',
              border: '1px solid var(--status-rust-border)',
              borderRadius: 'var(--radius-sm)',
              marginBottom: '1rem',
              fontSize: '0.82rem',
              color: 'var(--status-rust)',
            }}
          >
            <strong>Superseded / Stale Finding Notice:</strong>{' '}
            {f.stale_reason || 'Evidence or calculation changed after this finding was generated. Rerun investigation to produce an updated finding.'}
          </div>
        )}

        {/* ── 6 Explicit Facets ────────────────────────────────────────────── */}
        
        {/* Facet 1: Deterministic Engine Math Anchor */}
        {matchingLr && (
          <div
            style={{
              padding: '0.75rem 1rem',
              background: 'var(--surface-subtle)',
              border: '1px solid var(--line)',
              borderRadius: 'var(--radius-sm)',
              marginBottom: '1rem',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              flexWrap: 'wrap',
              gap: '0.75rem',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <Database size={15} style={{ color: 'var(--accent)' }} />
              <span style={{ fontSize: '0.78rem', fontWeight: 600, color: 'var(--ink)' }}>
                Deterministic Engine Result:
              </span>
              <span className="font-mono" style={{ fontSize: '0.75rem', color: 'var(--ink-secondary)' }}>
                Billed: ${(matchingLr.original_amount_cents / 100).toFixed(2)} → Recalculated:{' '}
                {matchingLr.recalculated_amount_cents != null
                  ? `$${(matchingLr.recalculated_amount_cents / 100).toFixed(2)}`
                  : 'Unavailable (Insufficient Data)'}
              </span>
            </div>
            {matchingLr.difference_cents != null && (
              <span
                className="font-mono"
                style={{
                  fontSize: '0.85rem',
                  fontWeight: 700,
                  color: matchingLr.difference_cents < 0 ? 'var(--status-rust)' : 'var(--status-green)',
                }}
              >
                Discrepancy: ${(Math.abs(matchingLr.difference_cents) / 100).toFixed(2)}{' '}
                {matchingLr.difference_cents < 0 ? '(Overcharge)' : ''}
              </span>
            )}
          </div>
        )}

        {/* Facet 2: Synthesized Narrative */}
        <div style={{ marginBottom: '1.25rem' }}>
          <div style={{ fontSize: '0.72rem', color: 'var(--ink-muted)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '0.35rem' }}>
            Synthesized Finding Narrative
          </div>
          <p style={{ fontSize: '0.92rem', lineHeight: 1.6, color: 'var(--ink)', margin: 0 }}>
            {f.narrative || f.raw_ai_text}
          </p>
          {f.narrative && f.raw_ai_text && f.narrative !== f.raw_ai_text && (
            <div style={{ marginTop: '0.5rem', fontSize: '0.78rem', color: 'var(--ink-muted)', fontStyle: 'italic' }}>
              Original model formulation: &ldquo;{f.raw_ai_text}&rdquo;
            </div>
          )}
        </div>

        {/* Facet 3: Customer Claims (Audited as Untrusted User Input) */}
        {caseData?.dispute_description && (
          <div style={{ marginBottom: '0.85rem', padding: '0.65rem 0.85rem', background: 'var(--surface-subtle)', borderRadius: 'var(--radius-xs)', borderLeft: '3px solid var(--ink-faint)' }}>
            <div style={{ fontSize: '0.72rem', color: 'var(--ink-muted)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: '0.2rem' }}>
              Customer Claim (Subject to Verification)
            </div>
            <div style={{ fontSize: '0.82rem', color: 'var(--ink-secondary)', fontStyle: 'italic' }}>
              &ldquo;{caseData.dispute_description}&rdquo;
            </div>
            {caseData.claimed_usage_quantity != null && (
              <div style={{ fontSize: '0.75rem', color: 'var(--ink)', fontWeight: 600, marginTop: '4px' }}>
                Claimed Units: {caseData.claimed_usage_quantity} {caseData.claimed_usage_uom || ''}
              </div>
            )}
          </div>
        )}

        {/* Facet 4: Verified Facts */}
        {f.verified_facts && f.verified_facts.length > 0 && (
          <div style={{ marginBottom: '0.85rem' }}>
            <div style={{ fontSize: '0.72rem', color: 'var(--status-green)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: '0.35rem', display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
              <CheckCircle2 size={12} />
              <span>Verified Contract & Telemetry Facts</span>
            </div>
            <ul style={{ paddingLeft: '1.25rem', fontSize: '0.82rem', color: 'var(--ink-secondary)', margin: 0 }}>
              {f.verified_facts.map((fact, idx) => (
                <li key={idx}>{typeof fact === 'string' ? fact : JSON.stringify(fact)}</li>
              ))}
            </ul>
          </div>
        )}

        {/* Facet 5: Missing Evidence Questions */}
        {f.missing_evidence_questions && f.missing_evidence_questions.length > 0 && (
          <div style={{ marginBottom: '0.85rem', padding: '0.75rem 0.95rem', background: 'var(--status-rust-bg)', border: '1px solid var(--status-rust-border)', borderRadius: 'var(--radius-xs)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.35rem', flexWrap: 'wrap', gap: '0.5rem' }}>
              <div style={{ fontSize: '0.72rem', color: 'var(--status-rust)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.04em', display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                <ShieldAlert size={13} />
                <span>Missing Evidence Required for Verification</span>
              </div>
              {onRequestInfo && (
                <button
                  type="button"
                  className="btn btn-amber btn-sm"
                  style={{ fontSize: '0.72rem', padding: '0.2rem 0.5rem' }}
                  onClick={onRequestInfo}
                  data-testid="request-from-customer-facet-btn"
                >
                  Request from Customer
                </button>
              )}
            </div>
            <ul style={{ paddingLeft: '1.25rem', fontSize: '0.82rem', color: 'var(--ink)', margin: 0 }}>
              {f.missing_evidence_questions.map((me, idx) => (
                <li key={idx}>{typeof me === 'string' ? me : JSON.stringify(me)}</li>
              ))}
            </ul>
          </div>
        )}

        {/* Facet 6: AI-Generated Root-Cause Hypotheses */}
        {f.possible_explanations && f.possible_explanations.length > 0 && (
          <div style={{ marginBottom: '0.85rem' }}>
            <div style={{ fontSize: '0.72rem', color: 'var(--accent)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: '0.35rem' }}>
              AI Root-Cause Hypotheses
            </div>
            <ul style={{ paddingLeft: '1.25rem', fontSize: '0.82rem', color: 'var(--ink-secondary)', margin: 0 }}>
              {f.possible_explanations.map((exp, idx) => (
                <li key={idx}>{typeof exp === 'string' ? exp : JSON.stringify(exp)}</li>
              ))}
            </ul>
          </div>
        )}

        {/* Citations & Anchors */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginTop: '1rem', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '0.75rem', color: 'var(--ink-muted)' }}>Citation Anchors:</span>
          {f.citation_ids &&
            f.citation_ids.map((cid, i) => {
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
          <span
            style={{
              fontSize: '0.75rem',
              color: f.citation_validation_passed ? 'var(--status-green)' : 'var(--status-rust)',
              fontWeight: 600,
            }}
          >
            {f.citation_validation_passed ? '✓ Citations Verified' : '✗ Verification Failed'}
          </span>
        </div>

        {/* Audited Human Review History */}
        {hasReviews && (
          <div style={{ marginTop: '1.25rem', borderTop: '1px solid var(--line)', paddingTop: '1rem' }}>
            <div style={{ fontSize: '0.72rem', color: 'var(--ink-muted)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: '0.65rem' }}>
              Audited Human Review History ({f.reviews.length})
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem' }}>
              {f.reviews.map((rev) => (
                <div
                  key={rev.id}
                  style={{
                    background: 'var(--surface-subtle)',
                    padding: '0.75rem 1rem',
                    borderRadius: 'var(--radius-sm)',
                    border: '1px solid var(--line)',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.35rem', flexWrap: 'wrap', gap: '0.5rem' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      <span
                        className={`badge ${rev.action === 'ACCEPT' ? 'badge-resolved' : rev.action === 'EDIT' ? 'badge-open' : 'badge-stale'}`}
                        style={{ fontSize: '0.68rem' }}
                      >
                        {rev.action}
                      </span>
                      <span style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--ink)' }}>{rev.reviewer}</span>
                    </div>
                    <span style={{ fontSize: '0.75rem', color: 'var(--ink-muted)' }}>
                      {new Date(rev.reviewed_at || rev.created_at).toLocaleString()}
                    </span>
                  </div>
                  {rev.note && (
                    <div style={{ fontSize: '0.8rem', color: 'var(--ink-secondary)', fontStyle: 'italic', marginBottom: rev.edited_text ? '0.35rem' : '0' }}>
                      Note: "{rev.note}"
                    </div>
                  )}
                  {rev.edited_text && (
                    <div style={{ marginTop: '0.45rem', padding: '0.55rem 0.85rem', background: 'var(--surface)', borderLeft: '3px solid var(--ink)', borderRadius: '2px', fontSize: '0.82rem', color: 'var(--ink)', lineHeight: '1.5' }}>
                      <strong>Reviewer Edited Text: </strong>
                      {rev.edited_text}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    );
  };

  return (
    <div>
      <div className="card" style={{ padding: '2rem', marginBottom: '2rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '1.5rem', flexWrap: 'wrap', gap: '1rem' }}>
          <div>
            <div className="eyebrow">
              <span className="eyebrow-num">02</span>
              <span>·</span>
              <span>AI Investigation (LangGraph)</span>
            </div>
            <h3 style={{ fontSize: '1.45rem', marginBottom: '0.25rem' }}>Autonomous Multi-Node Investigation</h3>
            <p style={{ fontSize: '0.85rem', color: 'var(--ink-secondary)', maxWidth: 650 }}>
              Multi-node StateGraph synthesizing line-by-line findings, verifying cryptographic citation anchors, and proposing human resolution options.
            </p>
          </div>
          <button
            type="button"
            className="btn btn-primary"
            onClick={handleTriggerInvestigation}
            disabled={actionLoading}
          >
            <Bot size={15} />
            <span>{actionLoading ? 'Investigating...' : 'Trigger Investigation Run'}</span>
          </button>
        </div>

        {investigation && (
          <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', marginBottom: '1.75rem', flexWrap: 'wrap', paddingBottom: '1rem', borderBottom: '1px solid var(--line-subtle)' }}>
            <span className={`badge ${investigation.status === 'COMPLETED' ? 'badge-resolved' : 'badge-awaiting'}`}>
              Run {investigation.status}
            </span>
            <span className="font-mono" style={{ fontSize: '0.75rem', color: 'var(--ink-muted)' }}>
              Run ID: {investigation.id}
            </span>
            {investigation.token_usage?.provider && (
              <span
                className="badge"
                style={{
                  background: 'var(--surface-subtle)',
                  color: 'var(--ink-secondary)',
                  border: '1px solid var(--line)',
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
            {investigation.token_usage?.provider === 'fallback_mock' && (
              <div
                style={{
                  width: '100%',
                  padding: '0.75rem 1rem',
                  borderRadius: '8px',
                  background: 'rgba(234, 179, 8, 0.1)',
                  border: '1px solid rgba(234, 179, 8, 0.35)',
                  color: 'var(--amber, #f59e0b)',
                  fontSize: '0.825rem',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.5rem',
                  marginTop: '0.5rem',
                }}
              >
                <span style={{ fontSize: '1.1rem' }}>⚠️</span>
                <span>
                  <strong>Deterministic Reference Template (Not Live AI)</strong>: External LLM providers were unavailable or unconfigured. This run was synthesized using FairBill&apos;s deterministic rule engine reference template to guarantee 100% financial calculation accuracy.
                </span>
              </div>
            )}
          </div>
        )}

        {findings.length > 0 ? (
          <>
            {(() => {
              const activeFindingsList = findings.filter((f) => !f.is_stale);
              const confirmedCount = activeFindingsList.filter((f) => f.finding_type === 'CONFIRMED_CALCULATION_DISCREPANCY').length;
              const ambiguityCount = activeFindingsList.filter((f) => f.finding_type === 'AMBIGUITY_DETECTED').length;
              const gapCount = activeFindingsList.filter(
                (f) => f.finding_type === 'EVIDENCE_GAP' || (f.missing_evidence_questions && f.missing_evidence_questions.length > 0)
              ).length;

              const lineResults = calculation?.line_results || [];
              let totalBilled = 0;
              let totalOvercharge = 0;
              let totalUndisputed = 0;

              lineResults.forEach((lr) => {
                totalBilled += (lr.original_amount_cents || 0);
                if (lr.difference_cents != null && lr.difference_cents < 0) {
                  totalOvercharge += Math.abs(lr.difference_cents);
                }
                if (lr.undisputed_overcharge_cents != null && lr.undisputed_overcharge_cents > 0) {
                  totalUndisputed += lr.undisputed_overcharge_cents;
                }
              });

              const effectiveCap = totalOvercharge > 0 ? totalOvercharge : totalUndisputed;

              const allQuestions = [];
              activeFindingsList.forEach((f) => {
                if (Array.isArray(f.missing_evidence_questions)) allQuestions.push(...f.missing_evidence_questions);
                if (Array.isArray(f.open_questions)) allQuestions.push(...f.open_questions);
              });

              return (
                <div
                  className="card"
                  data-testid="case-investigation-summary"
                  style={{
                    background: 'var(--surface-subtle)',
                    border: '1px solid var(--line)',
                    borderRadius: 'var(--radius-md)',
                    padding: '1.5rem',
                    marginBottom: '2rem',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.15rem', flexWrap: 'wrap', gap: '0.75rem' }}>
                    <div>
                      <div style={{ fontSize: '0.72rem', color: 'var(--accent)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '0.2rem' }}>
                        Executive Synthesis
                      </div>
                      <h4 style={{ margin: 0, fontSize: '1.2rem', color: 'var(--ink)' }}>
                        Case Investigation Summary & Root-Cause Analysis
                      </h4>
                    </div>
                    <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                      {confirmedCount > 0 && (
                        <span className="badge badge-resolved">
                          {confirmedCount} Confirmed Discrepanc{confirmedCount === 1 ? 'y' : 'ies'}
                        </span>
                      )}
                      {ambiguityCount > 0 && (
                        <span className="badge badge-awaiting">
                          {ambiguityCount} Ambiguous Option{ambiguityCount === 1 ? '' : 's'}
                        </span>
                      )}
                      {gapCount > 0 && (
                        <span className="badge badge-stale">
                          {gapCount} Evidence Gap{gapCount === 1 ? '' : 's'}
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Financial & Status Metrics */}
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '0.85rem', marginBottom: '1.25rem' }}>
                    <div style={{ background: 'var(--surface)', padding: '0.85rem 1rem', borderRadius: 'var(--radius-sm)', border: '1px solid var(--line)' }}>
                      <div style={{ fontSize: '0.72rem', color: 'var(--ink-muted)', textTransform: 'uppercase' }}>Original Billed</div>
                      <div className="font-mono" style={{ fontSize: '1.15rem', fontWeight: 700, color: 'var(--ink)' }}>
                        ${(totalBilled / 100).toFixed(2)}
                      </div>
                    </div>
                    <div style={{ background: 'var(--surface)', padding: '0.85rem 1rem', borderRadius: 'var(--radius-sm)', border: '1px solid var(--line)' }}>
                      <div style={{ fontSize: '0.72rem', color: 'var(--ink-muted)', textTransform: 'uppercase' }}>Allowable Recovery Cap</div>
                      <div className="font-mono" style={{ fontSize: '1.15rem', fontWeight: 700, color: effectiveCap > 0 ? 'var(--status-rust)' : 'var(--ink)' }}>
                        ${(effectiveCap / 100).toFixed(2)}
                      </div>
                      {totalUndisputed > 0 && totalOvercharge === 0 && (
                        <div style={{ fontSize: '0.68rem', color: 'var(--ink-muted)', marginTop: '2px' }}>Undisputed portion of ambiguous lines</div>
                      )}
                    </div>
                    <div style={{ background: 'var(--surface)', padding: '0.85rem 1rem', borderRadius: 'var(--radius-sm)', border: '1px solid var(--line)' }}>
                      <div style={{ fontSize: '0.72rem', color: 'var(--ink-muted)', textTransform: 'uppercase' }}>Active Findings</div>
                      <div className="font-mono" style={{ fontSize: '1.15rem', fontWeight: 700, color: 'var(--ink)' }}>
                        {activeFindingsList.length} / {findings.length}
                      </div>
                    </div>
                    <div style={{ background: 'var(--surface)', padding: '0.85rem 1rem', borderRadius: 'var(--radius-sm)', border: '1px solid var(--line)' }}>
                      <div style={{ fontSize: '0.72rem', color: 'var(--ink-muted)', textTransform: 'uppercase' }}>Evidence Status</div>
                      <div style={{ fontSize: '0.92rem', fontWeight: 600, color: allQuestions.length > 0 ? 'var(--status-amber)' : 'var(--status-green)', marginTop: '3px' }}>
                        {allQuestions.length > 0 ? `${allQuestions.length} Missing Items` : '✓ Complete'}
                      </div>
                    </div>
                  </div>

                  {/* Root Cause Synthesis Paragraph */}
                  <div style={{ background: 'var(--surface)', padding: '1rem', borderRadius: 'var(--radius-sm)', border: '1px solid var(--line)', marginBottom: allQuestions.length > 0 ? '1rem' : 0 }}>
                    <div style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--ink)', marginBottom: '0.4rem', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                      Root-Cause Synthesis & Operator Directive
                    </div>
                    <p style={{ fontSize: '0.86rem', lineHeight: 1.6, color: 'var(--ink-secondary)', margin: 0 }}>
                      {confirmedCount > 0 && ambiguityCount === 0 && gapCount === 0 &&
                        'Deterministic billing engine calculation confirmed a rate/tier overcharge against verified usage telemetry. Findings are actionable for credit issuance up to the remaining allowable cap in the Credits tab.'}
                      {ambiguityCount > 0 &&
                        'Contractual pricing ambiguity detected across valid interpretations. The deterministic engine has verified and reserved the undisputed portion. Select a resolution option below or review findings to finalize approval.'}
                      {gapCount > 0 &&
                        'Telemetry logs or contractual rules are missing or unverified. Financial credits cannot be calculated or approved from customer dispute assertions alone. Operator should request clarifying telemetry using the action below.'}
                      {confirmedCount === 0 && ambiguityCount === 0 && gapCount === 0 &&
                        'All invoice line items match contractual pricing and telemetry. No calculation discrepancy or unauthorized billing was identified.'}
                    </p>
                  </div>

                  {/* Missing Evidence Questions Action Banner */}
                  {allQuestions.length > 0 && (
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: 'var(--status-rust-bg)', border: '1px solid var(--status-rust-border)', borderRadius: 'var(--radius-sm)', padding: '0.75rem 1rem', flexWrap: 'wrap', gap: '0.75rem' }}>
                      <div style={{ fontSize: '0.82rem', color: 'var(--status-rust)', fontWeight: 600 }}>
                        Missing telemetry or evidence items flagged by AI investigation ({allQuestions.length} questions).
                      </div>
                      {onRequestInfo && (
                        <button
                          type="button"
                          className="btn btn-amber btn-sm"
                          onClick={onRequestInfo}
                          data-testid="request-missing-evidence-btn"
                        >
                          Request Missing Evidence from Customer
                        </button>
                      )}
                    </div>
                  )}
                </div>
              );
            })()}

            {(() => {
              const groups = {};
              findings.forEach((f) => {
                const matchingLr = calculation?.line_results?.find((lr) => lr.id === f.calculation_line_result_id);
                const lineKey = matchingLr?.line_id || (f.calculation_line_result_id ? `Result #${f.calculation_line_result_id}` : 'General / Case-Wide');
                if (!groups[lineKey]) groups[lineKey] = [];
                groups[lineKey].push(f);
              });

              return Object.entries(groups).map(([lineKey, groupFindings]) => {
                const activeFindings = groupFindings.filter((f) => !f.is_stale);
                const staleFindings = groupFindings.filter((f) => f.is_stale);

                return (
                  <div key={lineKey} style={{ marginBottom: '2.5rem' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem', marginBottom: '1rem', paddingBottom: '0.5rem', borderBottom: '1px solid var(--line)' }}>
                      <span style={{ fontSize: '0.9rem', fontWeight: 700, color: 'var(--ink)' }}>
                        Line Item: {lineKey}
                      </span>
                      {activeFindings.length > 0 ? (
                        <span className="badge badge-resolved" style={{ fontSize: '0.7rem' }}>
                          {activeFindings.length} Active Finding{activeFindings.length === 1 ? '' : 's'}
                        </span>
                      ) : (
                        <span className="badge badge-stale" style={{ fontSize: '0.7rem' }}>
                          All Findings Stale (Awaiting Re-Investigation)
                        </span>
                      )}
                    </div>

                    {/* Active Actionable Findings */}
                    {activeFindings.length > 0 ? (
                      activeFindings.map((f) => renderFindingCard(f, true))
                    ) : (
                      <div
                        style={{
                          padding: '0.85rem 1rem',
                          background: 'var(--status-rust-bg)',
                          border: '1px solid var(--status-rust-border)',
                          borderRadius: 'var(--radius-sm)',
                          marginBottom: '1rem',
                          fontSize: '0.82rem',
                          color: 'var(--status-rust)',
                        }}
                      >
                        All previous findings for this line are STALE because new evidence or calculation was processed. Trigger an investigation run to evaluate current telemetry.
                      </div>
                    )}

                    {/* Historical / Superseded Findings Archive */}
                    {staleFindings.length > 0 && (
                      <div style={{ marginTop: '1.25rem', paddingTop: '0.75rem', borderTop: '1px dashed var(--line)' }}>
                        <details style={{ background: 'var(--surface-subtle)', border: '1px solid var(--line)', borderRadius: 'var(--radius-md)', padding: '0.85rem 1.15rem' }}>
                          <summary style={{ cursor: 'pointer', fontWeight: 600, fontSize: '0.82rem', color: 'var(--ink-secondary)' }}>
                            📁 Historical Findings Archive ({staleFindings.length} Superseded {staleFindings.length === 1 ? 'Finding' : 'Findings'}) — Click to inspect previous runs
                          </summary>
                          <div style={{ marginTop: '1rem' }}>
                            {staleFindings.map((f) => renderFindingCard(f, false))}
                          </div>
                        </details>
                      </div>
                    )}
                  </div>
                );
              });
            })()}

            {/* Proposed Resolution Options */}
            {investigation?.resolution_options && investigation.resolution_options.length > 0 && (
              <div style={{ marginTop: '2rem', borderTop: '1px solid var(--line)', paddingTop: '1.5rem' }}>
                <h4 style={{ fontSize: '1.15rem', marginBottom: '1rem' }}>
                  Proposed Resolution Options ({investigation.resolution_options.length})
                </h4>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '1rem' }}>
                  {investigation.resolution_options.map((opt) => (
                    <div key={opt.id} className="card" style={{ padding: '1.25rem', display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
                      <div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                          <span className={`badge ${opt.option_type === 'RECOMMEND_CREDIT' ? 'badge-resolved' : opt.option_type === 'REQUEST_AMENDMENT' ? 'badge-awaiting' : 'badge-open'}`}>
                            {opt.option_type}
                          </span>
                          {opt.is_stale && <span className="badge badge-stale">STALE</span>}
                        </div>
                        <p style={{ fontSize: '0.85rem', color: 'var(--ink-secondary)', lineHeight: 1.5, marginBottom: '0.75rem' }}>
                          {opt.description}
                        </p>
                        {opt.calculation_line_result_id && (
                          <div className="font-mono" style={{ fontSize: '0.72rem', color: 'var(--ink-muted)', marginBottom: '0.75rem' }}>
                            Linked Calculation Result #{opt.calculation_line_result_id}
                          </div>
                        )}
                      </div>
                      {(opt.option_type === 'RECOMMEND_CREDIT' || opt.option_type === 'CREDIT_UNDISPUTED_PORTION') && (
                        <button
                          type="button"
                          className="btn btn-primary btn-sm"
                          style={{ marginTop: '0.5rem', width: '100%' }}
                          onClick={() => {
                            setSelectedResolutionOptionId(opt.id);
                            if (opt.calculation_line_result_id && calculation?.line_results) {
                              const targetLr = calculation.line_results.find((lr) => lr.id === opt.calculation_line_result_id);
                              if (targetLr) {
                                setSelectedLineId(targetLr.line_id);
                                if (opt.option_type === 'CREDIT_UNDISPUTED_PORTION' && targetLr.undisputed_overcharge_cents > 0) {
                                  setCreditAmountDollars((targetLr.undisputed_overcharge_cents / 100).toFixed(2));
                                } else if (targetLr.difference_cents < 0) {
                                  setCreditAmountDollars((Math.abs(targetLr.difference_cents) / 100).toFixed(2));
                                }
                              }
                            }
                            setActiveTab('credits');
                          }}
                        >
                          {opt.option_type === 'CREDIT_UNDISPUTED_PORTION' ? 'Credit Undisputed Portion' : 'Apply & Approve Credit'}
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        ) : investigation?.status === 'FAILED' ? (
          <div style={{ textAlign: 'center', padding: '3rem 1rem' }}>
            <AlertTriangle size={32} color="var(--status-rust)" style={{ marginBottom: '0.75rem' }} />
            <h4 style={{ color: 'var(--status-rust)', marginBottom: '0.5rem' }}>
              Calculation completed — AI investigation unavailable, retry
            </h4>
            <p style={{ color: 'var(--ink-secondary)', fontSize: '0.88rem', maxWidth: '480px', margin: '0 auto 1.5rem' }}>
              {investigation.status_reason || 'The deterministic billing calculation succeeded, but all AI investigation providers were unavailable or timed out.'}
            </p>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={handleTriggerInvestigation}
              disabled={actionLoading}
              style={{ borderColor: 'var(--status-rust-border)', color: 'var(--status-rust)' }}
            >
              <Bot size={15} />
              <span>Retry Investigation</span>
            </button>
          </div>
        ) : (
          <div style={{ textAlign: 'center', padding: '3.5rem 1rem', color: 'var(--ink-muted)' }}>
            <p style={{ fontSize: '0.9rem', marginBottom: '1.25rem' }}>
              No findings generated yet. Trigger an investigation to analyze this dispute.
            </p>
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={handleTriggerInvestigation}
              disabled={actionLoading}
            >
              <Bot size={14} />
              <span>Trigger Investigation Run</span>
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
