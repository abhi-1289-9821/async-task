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
  const lineFinding = findings.find(f => f.calculation_line_result_id === currentLineResult?.id)
    || (findings.length === 1 && !findings[0].calculation_line_result_id ? findings[0] : null);
  const latestReview = lineFinding?.reviews && lineFinding.reviews.length > 0 ? lineFinding.reviews[0] : null;
  const isAcceptedFinding = latestReview?.action === 'ACCEPT';

  const eligibleOverchargeCents = capInfo?.eligible_cents ?? (currentLineResult && currentLineResult.difference_cents < 0 ? Math.abs(currentLineResult.difference_cents) : 0);
  const priorLineCreditsCents = capInfo?.prior_credits_cents ?? 0;
  const lineAdjustmentsCents = capInfo?.line_adjustments_cents ?? 0;
  const caseWideAdjustmentsCents = capInfo?.case_wide_adjustments_cents ?? 0;
  const remainingLineCapCents = capInfo?.remaining_cap_cents ?? Math.max(0, eligibleOverchargeCents - priorLineCreditsCents);

  const findingLineResult = calculation?.line_results?.find(lr => lr.id === lineFinding?.calculation_line_result_id);
  const targetFindingLineId = findingLineResult?.line_id;
  const isLineMismatch = Boolean(targetFindingLineId && selectedLineId && targetFindingLineId !== selectedLineId);

  let disableReason = null;
  if (!currentLineResult || currentLineResult.finding_type === 'INSUFFICIENT_DATA' || currentLineResult.difference_cents == null) {
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

  const matchingOption = (resolutionOptions || []).find(o => o.calculation_line_result_id === lineFinding?.calculation_line_result_id && o.option_type === 'RECOMMEND_CREDIT')
    || (resolutionOptions || []).find(o => o.id === selectedResolutionOptionId)
    || (resolutionOptions || [])[0];

  const isInsufficient = currentLineResult?.finding_type === 'INSUFFICIENT_DATA' || currentLineResult?.difference_cents == null;
  const unverifiedClaimCents = capInfo?.unverified_adjustments_cents ?? 0;

  return (
    <div>
      <div className="card" style={{ padding: '2rem', marginBottom: '2rem' }}>
        <div className="eyebrow">
          <span className="eyebrow-num">04</span>
          <span>·</span>
          <span>Credit Issuance & Governance</span>
        </div>
        <h3 style={{ fontSize: '1.45rem', marginBottom: '0.25rem' }}>Concurrency-Safe Credit Approval</h3>
        <p style={{ fontSize: '0.85rem', color: 'var(--ink-secondary)', marginBottom: '1.5rem', maxWidth: 650 }}>
          Enforces row-level database locking (SELECT FOR UPDATE) to guarantee atomic credit validation and zero double-crediting.
        </p>

        {isInsufficient && (
          <div style={{ padding: '0.85rem 1rem', background: 'var(--status-rust-bg)', border: '1px solid var(--status-rust-border)', borderRadius: 'var(--radius-sm)', marginBottom: '1.25rem', fontSize: '0.85rem', color: 'var(--status-rust)', display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
            <Lock size={16} />
            <span><strong>Credit Approval Locked:</strong> Telemetry usage evidence is missing. Financial safety safeguards block credit proposals until verified telemetry is uploaded and evaluated by the billing engine.</span>
          </div>
        )}

        <div style={{ background: 'var(--surface-subtle)', padding: '1.25rem 1.5rem', borderRadius: 'var(--radius-md)', marginBottom: '1.75rem', border: '1px solid var(--line)' }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '1.25rem' }}>
            <div>
              <div style={{ fontSize: '0.72rem', color: 'var(--ink-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>Latest Review ({selectedLineId})</div>
              <div style={{ fontWeight: 600, color: isAcceptedFinding ? 'var(--status-green)' : 'var(--status-rust)', marginTop: '2px' }}>
                {isAcceptedFinding ? `✓ ${latestReview.action} by ${latestReview.reviewer}` : '✗ Must be ACCEPT'}
              </div>
            </div>
            <div>
              <div style={{ fontSize: '0.72rem', color: 'var(--ink-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>Finding Status</div>
              <div style={{ fontWeight: 600, color: lineFinding?.is_stale ? 'var(--status-rust)' : 'var(--status-green)', marginTop: '2px' }}>
                {lineFinding?.is_stale ? '✗ Stale Evidence' : '✓ Fresh Non-Stale'}
              </div>
            </div>
            <div>
              <div style={{ fontSize: '0.72rem', color: 'var(--ink-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>Calculated Overcharge</div>
              <div className="font-mono" style={{ fontWeight: 700, color: isInsufficient ? 'var(--status-rust)' : 'var(--ink)', fontSize: isInsufficient ? '0.95rem' : '1.1rem', marginTop: '2px' }}>
                {isInsufficient ? 'Unavailable (Missing Evidence)' : formatCents(eligibleOverchargeCents)}
              </div>
            </div>
            <div>
              <div style={{ fontSize: '0.72rem', color: 'var(--ink-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>Prior Confirmed Credits</div>
              <div className="font-mono" style={{ fontWeight: 700, color: 'var(--ink-muted)', fontSize: '1.1rem', marginTop: '2px' }}>
                {formatCents(priorLineCreditsCents)}
              </div>
            </div>
            {lineAdjustmentsCents > 0 && (
              <div>
                <div style={{ fontSize: '0.72rem', color: 'var(--ink-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>Line Adjustments</div>
                <div className="font-mono" style={{ fontWeight: 700, color: 'var(--status-amber)', fontSize: '1.1rem', marginTop: '2px' }}>
                  {formatCents(lineAdjustmentsCents)}
                </div>
              </div>
            )}
            {caseWideAdjustmentsCents > 0 && (
              <div>
                <div style={{ fontSize: '0.72rem', color: 'var(--ink-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>Case Adjustments</div>
                <div className="font-mono" style={{ fontWeight: 700, color: 'var(--status-amber)', fontSize: '1.1rem', marginTop: '2px' }}>
                  {formatCents(caseWideAdjustmentsCents)}
                </div>
              </div>
            )}
            {unverifiedClaimCents > 0 && (
              <div>
                <div style={{ fontSize: '0.72rem', color: 'var(--ink-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>Unverified Allegations</div>
                <div className="font-mono" style={{ fontWeight: 700, color: 'var(--status-rust)', fontSize: '1.05rem', marginTop: '2px' }}>
                  {formatCents(unverifiedClaimCents)}
                  <span style={{ fontSize: '0.68rem', fontWeight: 500, color: 'var(--ink-muted)', marginLeft: 4 }}>(Not deducted)</span>
                </div>
              </div>
            )}
            <div>
              <div style={{ fontSize: '0.72rem', color: 'var(--ink-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>Remaining Credit Cap</div>
              <div className="font-mono" style={{ fontWeight: 800, color: (!isInsufficient && remainingLineCapCents > 0) ? 'var(--status-green)' : 'var(--status-rust)', fontSize: '1.25rem', marginTop: '2px' }}>
                {isInsufficient ? '$0.00' : formatCents(remainingLineCapCents)}
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
