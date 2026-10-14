import React from 'react';
import { Lock } from 'lucide-react';

export default function CreditsTab({
  calculation,
  findings,
  credits,
  capInfo,
  caseData,
  selectedLineId,
  setSelectedLineId,
  creditAmountDollars,
  setCreditAmountDollars,
  creditReason,
  setCreditReason,
  creditNote,
  setCreditNote,
  resolutionOptions,
  selectedResolutionOptionId,
  handleApproveCredit,
  actionLoading,
  formatCents,
}) {
  const currentLineResult = calculation?.line_results?.find(lr => lr.line_id === selectedLineId);
  const lineFinding = findings.find(f => (f.invoice_line_id && f.invoice_line_id === selectedLineId) || (currentLineResult?.id && f.calculation_line_result_id === currentLineResult.id))
    || findings.find(f => f.invoice_line_id === selectedLineId)
    || (findings.length === 1 && !findings[0].invoice_line_id && !findings[0].calculation_line_result_id ? findings[0] : null);
  const latestReview = lineFinding?.reviews && lineFinding.reviews.length > 0 ? lineFinding.reviews[0] : null;
  const isAcceptedFinding = latestReview?.action === 'ACCEPT';

  const originalBilledCents = capInfo?.original_billed_cents ?? currentLineResult?.original_amount_cents ?? 0;
  const recalculatedCents = capInfo?.recalculated_cents ?? currentLineResult?.recalculated_amount_cents;
  const grossDiffCents = capInfo?.gross_discrepancy_cents ?? currentLineResult?.difference_cents;
  const eligibleOverchargeCents = capInfo?.eligible_cents ?? (currentLineResult && currentLineResult.difference_cents < 0 ? Math.abs(currentLineResult.difference_cents) : 0);
  const priorLineCreditsCents = capInfo?.prior_credits_cents ?? 0;
  const lineAdjustmentsCents = capInfo?.line_adjustments_cents ?? 0;
  const caseWideAdjustmentsCents = capInfo?.case_wide_adjustments_cents ?? 0;
  const remainingLineCapCents = capInfo?.remaining_cap_cents ?? Math.max(0, eligibleOverchargeCents - priorLineCreditsCents);

  const isInsufficient = currentLineResult?.finding_type === 'INSUFFICIENT_DATA' || grossDiffCents == null;
  const unverifiedClaimCents = capInfo?.unverified_adjustments_cents ?? 0;

  const targetFindingLineId = lineFinding?.invoice_line_id || (calculation?.line_results?.find(lr => lr.id === lineFinding?.calculation_line_result_id)?.line_id);
  const isLineMismatch = Boolean(targetFindingLineId && selectedLineId && targetFindingLineId !== selectedLineId);

  let disableReason = null;
  if (isInsufficient) {
    disableReason = 'Evidence is insufficient — cannot propose or approve credit without verified telemetry and deterministic calculation.';
  } else if (!lineFinding) {
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

  const matchingOption = (resolutionOptions || []).find(o => (o.invoice_line_id === selectedLineId || o.calculation_line_result_id === lineFinding?.calculation_line_result_id) && (o.option_type === 'RECOMMEND_CREDIT' || o.option_type === 'CREDIT_UNDISPUTED_PORTION'))
    || (resolutionOptions || []).find(o => o.id === selectedResolutionOptionId)
    || (resolutionOptions || [])[0];

  return (
    <div>
      <div className="card" style={{ padding: '2rem', marginBottom: '2rem' }}>
        <div className="eyebrow">
          <span className="eyebrow-num">04</span>
          <span>·</span>
          <span>Credit Issuance & Governance</span>
        </div>
        <h3 style={{ fontSize: '1.45rem', marginBottom: '0.25rem' }}>Authoritative Credit Governance</h3>
        <p style={{ fontSize: '0.85rem', color: 'var(--ink-secondary)', marginBottom: '1.5rem', maxWidth: 650 }}>
          Enforces row-level database locking (SELECT FOR UPDATE) to guarantee atomic credit validation, ledger reconciliation, and zero double-crediting.
        </p>

        {isInsufficient && (
          <div style={{ padding: '0.85rem 1rem', background: 'var(--status-rust-bg)', border: '1px solid var(--status-rust-border)', borderRadius: 'var(--radius-sm)', marginBottom: '1.25rem', fontSize: '0.85rem', color: 'var(--status-rust)', display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
            <Lock size={16} />
            <span><strong>Credit Approval Locked:</strong> Telemetry usage evidence is missing. Financial safety safeguards block credit proposals until verified telemetry is uploaded and evaluated by the billing engine.</span>
          </div>
        )}

        {/* ── 8-Metric Authoritative Governance Ledger ───────────────────── */}
        <div style={{ background: 'var(--surface-subtle)', padding: '1.25rem 1.5rem', borderRadius: 'var(--radius-md)', marginBottom: '1.75rem', border: '1px solid var(--line)' }}>
          <div style={{ fontSize: '0.78rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--ink-secondary)', marginBottom: '1rem' }}>
            Authoritative Credit Governance Ledger ({selectedLineId || 'Case'})
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: '1.25rem' }}>
            {/* 1. Original Billed Amount */}
            <div>
              <div style={{ fontSize: '0.72rem', color: 'var(--ink-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>1. Original Billed</div>
              <div className="font-mono" style={{ fontWeight: 700, color: 'var(--ink)', fontSize: '1.1rem', marginTop: '2px' }}>
                {formatCents(originalBilledCents)}
              </div>
            </div>

            {/* 2. Deterministically Recalculated */}
            <div>
              <div style={{ fontSize: '0.72rem', color: 'var(--ink-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>2. Recalculated Amount</div>
              <div className="font-mono" style={{ fontWeight: 700, color: 'var(--ink)', fontSize: '1.1rem', marginTop: '2px' }}>
                {isInsufficient ? (
                  <span style={{ color: 'var(--status-rust)', fontSize: '0.9rem' }}>Unavailable</span>
                ) : recalculatedCents != null ? (
                  formatCents(recalculatedCents)
                ) : (
                  <span style={{ color: 'var(--status-amber)', fontSize: '0.9rem' }}>Ambiguous</span>
                )}
              </div>
            </div>

            {/* 3. Gross Calculated Discrepancy */}
            <div>
              <div style={{ fontSize: '0.72rem', color: 'var(--ink-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>3. Gross Discrepancy</div>
              <div className="font-mono" style={{ fontWeight: 700, color: isInsufficient ? 'var(--status-rust)' : grossDiffCents < 0 ? 'var(--status-rust)' : 'var(--status-green)', fontSize: '1.1rem', marginTop: '2px' }}>
                {isInsufficient ? (
                  <span style={{ fontSize: '0.9rem' }}>Uncomputed</span>
                ) : grossDiffCents != null ? (
                  `${grossDiffCents < 0 ? '-' : '+'}${formatCents(Math.abs(grossDiffCents))} ${grossDiffCents < 0 ? '(Overcharge)' : '(Undercharge)'}`
                ) : (
                  formatCents(eligibleOverchargeCents)
                )}
              </div>
            </div>

            {/* 4. Confirmed Prior Credits & Adjustments */}
            <div>
              <div style={{ fontSize: '0.72rem', color: 'var(--ink-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>4. Confirmed Adjustments</div>
              <div className="font-mono" style={{ fontWeight: 700, color: 'var(--ink-muted)', fontSize: '1.1rem', marginTop: '2px' }}>
                {formatCents(priorLineCreditsCents + lineAdjustmentsCents + caseWideAdjustmentsCents)}
              </div>
            </div>

            {/* 5. Potential Remaining Eligible Credit */}
            <div>
              <div style={{ fontSize: '0.72rem', color: 'var(--ink-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>5. Eligible Overcharge</div>
              <div className="font-mono" style={{ fontWeight: 700, color: isInsufficient ? 'var(--status-rust)' : 'var(--ink)', fontSize: '1.1rem', marginTop: '2px' }}>
                {isInsufficient ? '$0.00' : formatCents(eligibleOverchargeCents)}
              </div>
            </div>

            {/* 6. Current Approval Eligibility */}
            <div>
              <div style={{ fontSize: '0.72rem', color: 'var(--ink-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>6. Approval Eligibility</div>
              <div style={{ fontWeight: 600, color: (!disableReason && isAcceptedFinding) ? 'var(--status-green)' : 'var(--status-rust)', fontSize: '0.85rem', marginTop: '4px' }}>
                {(!disableReason && isAcceptedFinding) ? '✓ Eligible for Credit' : `✗ Blocked (${isAcceptedFinding ? 'Conditions unmet' : latestReview?.action || 'Unreviewed'})`}
              </div>
            </div>

            {/* 7. Currently Approvable Maximum (Remaining Cap) */}
            <div>
              <div style={{ fontSize: '0.72rem', color: 'var(--ink-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>7. Allowable Credit Cap</div>
              <div className="font-mono" style={{ fontWeight: 800, color: (!isInsufficient && remainingLineCapCents > 0) ? 'var(--status-green)' : 'var(--status-rust)', fontSize: '1.25rem', marginTop: '2px' }}>
                {isInsufficient ? '$0.00' : formatCents(remainingLineCapCents)}
              </div>
            </div>

            {/* 8. Final Issued Credit */}
            <div>
              <div style={{ fontSize: '0.72rem', color: 'var(--ink-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>8. Issued Credit Ledger</div>
              <div className="font-mono" style={{ fontWeight: 700, color: 'var(--ink)', fontSize: '1.1rem', marginTop: '2px' }}>
                {formatCents(priorLineCreditsCents)}
              </div>
            </div>
          </div>

          {unverifiedClaimCents > 0 && (
            <div style={{ marginTop: '1rem', paddingTop: '0.75rem', borderTop: '1px solid var(--line-subtle)', fontSize: '0.8rem', color: 'var(--status-rust)' }}>
              <strong>Note on Alleged Claims:</strong> Unverified customer allegations of {formatCents(unverifiedClaimCents)} are kept separate and not counted as confirmed credits against the cap.
            </div>
          )}
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
            <div style={{ fontSize: '0.75rem', color: 'var(--ink-muted)', marginTop: '0.25rem' }}>
              Defaults to remaining allowable cap: {formatCents(remainingLineCapCents)}
            </div>
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: '1rem', marginBottom: '1.5rem' }}>
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
              <option value="CALCULATION_OVERCHARGE">CALCULATION_OVERCHARGE</option>
              <option value="CONTRACTUAL_DISCOUNT_APPLIED">CONTRACTUAL_DISCOUNT_APPLIED</option>
              <option value="CONTRACTUAL_DISCOUNT_CORRECTION">CONTRACTUAL_DISCOUNT_CORRECTION</option>
              <option value="MINIMUM_COMMITMENT_ADJUSTMENT">MINIMUM_COMMITMENT_ADJUSTMENT</option>
              <option value="DUPLICATE_CHARGE_REFUND">DUPLICATE_CHARGE_REFUND</option>
              <option value="CREDIT_UNDISPUTED_PORTION">CREDIT_UNDISPUTED_PORTION</option>
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

        <div>
          <button
            type="button"
            className="btn btn-primary"
            data-testid="approve-credit-btn"
            onClick={() => handleApproveCredit(lineFinding?.id, matchingOption?.id || selectedResolutionOptionId)}
            disabled={Boolean(disableReason) || actionLoading}
          >
            <Lock size={14} />
            <span>{actionLoading ? 'Locking & Approving...' : 'Approve Credit Under Row Lock'}</span>
          </button>
          {disableReason && (
            <div className="disabled-reason-hint">
              <span>⚠ Disabled reason: {disableReason}</span>
            </div>
          )}
        </div>
      </div>

      <div className="table-container">
        <table>
          <thead>
            <tr>
              <th>Credit ID</th>
              <th>Target Line</th>
              <th style={{ textAlign: 'right' }}>Amount</th>
              <th>Reason Code</th>
              <th>Idempotency Key</th>
              <th>Approved By</th>
              <th>Timestamp</th>
            </tr>
          </thead>
          <tbody>
            {credits.length === 0 ? (
              <tr>
                <td colSpan="7" style={{ textAlign: 'center', padding: '3rem 1rem', color: 'var(--ink-muted)' }}>
                  No credits approved yet for this case.
                </td>
              </tr>
            ) : (
              credits.map((c) => (
                <tr key={c.id}>
                  <td className="font-mono" style={{ fontWeight: 600 }}>{c.id}</td>
                  <td className="font-mono">{c.invoice_line_id}</td>
                  <td className="table-money-cell" style={{ color: 'var(--status-green)' }}>
                    {formatCents(c.amount_cents)}
                  </td>
                  <td>{c.reason_code}</td>
                  <td className="font-mono" style={{ fontSize: '0.72rem' }}>
                    {c.idempotency_key?.slice(0, 16)}...
                  </td>
                  <td>{c.approved_by}</td>
                  <td style={{ fontSize: '0.8rem', color: 'var(--ink-muted)' }}>
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
}
