import React from 'react';
import { Play, AlertCircle } from 'lucide-react';

export default function EngineTab({
  calculation,
  caseData,
  handleRunCalculation,
  actionLoading,
  formatCents,
  formatDifference,
}) {
  return (
    <div>
      <div className="card" style={{ padding: '2rem', marginBottom: '2rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '1.5rem', flexWrap: 'wrap', gap: '1rem' }}>
          <div>
            <div className="eyebrow">
              <span className="eyebrow-num">01</span>
              <span>·</span>
              <span>Deterministic Financial Math</span>
            </div>
            <h3 style={{ fontSize: '1.45rem', marginBottom: '0.25rem' }}>Pure Python Billing Engine</h3>
            <p style={{ fontSize: '0.85rem', color: 'var(--ink-secondary)', maxWidth: 650 }}>
              Evaluates standard library Decimal arithmetic, graduated and volume tier slabs, staging exemptions, and emits cryptographic result anchors.
            </p>
          </div>
          <button
            type="button"
            className="btn btn-primary"
            onClick={handleRunCalculation}
            disabled={actionLoading}
          >
            <Play size={15} />
            <span>{actionLoading ? 'Calculating...' : 'Run Billing Engine'}</span>
          </button>
        </div>

        {calculation ? (
          <>
            {/* ── Two-Column Billed vs Recalculated Comparison ─────────────── */}
            <div className="recalc-comparison-grid">
              <div>
                <div className="recalc-col-label">Original Billed Amount</div>
                <div className="recalc-col-value">
                  {formatCents(calculation.total_original_billed_cents)}
                </div>
              </div>
              <div>
                <div className="recalc-col-label">Recalculated Amount</div>
                <div className="recalc-col-value">
                  {calculation.engine_status === 'INSUFFICIENT_DATA' ? (
                    <span style={{ color: 'var(--status-rust)', fontSize: '1.35rem' }}>
                      Uncomputed
                    </span>
                  ) : calculation.engine_status === 'AMBIGUOUS' ? (
                    <span style={{ color: 'var(--status-amber)', fontSize: '1.35rem' }}>
                      Ambiguous
                    </span>
                  ) : (
                    formatCents(calculation.total_recalculated_cents)
                  )}
                </div>
              </div>
              <div className="recalc-diff-row">
                <div>
                  <span style={{ fontSize: '0.8rem', color: 'var(--ink-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                    Calculated Discrepancy:
                  </span>{' '}
                  {calculation.engine_status === 'INSUFFICIENT_DATA' ? (
                    <>
                      <strong style={{ 
                        fontSize: '1.15rem', 
                        fontFamily: 'var(--font-serif)', 
                        color: 'var(--status-rust)',
                        marginRight: '0.4rem'
                      }}>
                        Awaiting Evidence
                      </strong>
                      <span style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--status-rust)' }}>
                        (Telemetry events required)
                      </span>
                    </>
                  ) : calculation.engine_status === 'AMBIGUOUS' ? (
                    <>
                      <strong style={{ 
                        fontSize: '1.15rem', 
                        fontFamily: 'var(--font-serif)', 
                        color: 'var(--status-amber)',
                        marginRight: '0.4rem'
                      }}>
                        Multiple Interpretations
                      </strong>
                      <span style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--status-amber)' }}>
                        (Contract clauses conflict)
                      </span>
                    </>
                  ) : (
                    <>
                      <strong style={{ 
                        fontSize: '1.25rem', 
                        fontFamily: 'var(--font-serif)', 
                        fontVariantNumeric: 'tabular-nums', 
                        color: calculation.total_difference_cents < 0 ? 'var(--status-rust)' : calculation.total_difference_cents > 0 ? 'var(--status-amber)' : 'var(--status-green)',
                        marginRight: '0.4rem'
                      }}>
                        {formatDifference(calculation.total_difference_cents)}
                      </strong>
                      <span style={{ fontSize: '0.8rem', fontWeight: 600, color: calculation.total_difference_cents < 0 ? 'var(--status-rust)' : 'var(--status-green)' }}>
                        {calculation.total_difference_cents < 0 ? '(Overcharge)' : calculation.total_difference_cents > 0 ? '(Undercharge)' : '(Exact match)'}
                      </span>
                    </>
                  )}
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                  <span className={`badge ${calculation.engine_status === 'OK' ? 'badge-resolved' : calculation.engine_status === 'INSUFFICIENT_DATA' ? 'badge-stale' : 'badge-awaiting'}`}>
                    Engine Status: {calculation.engine_status}
                  </span>
                </div>
              </div>
            </div>

            {/* Insufficient Data notice */}
            {calculation.engine_status === 'INSUFFICIENT_DATA' && (
              <div style={{ 
                background: 'var(--status-rust-bg)', 
                border: '1px solid var(--status-rust-border)', 
                borderRadius: 'var(--radius-md)', 
                padding: '0.9rem 1.25rem', 
                marginTop: '1.25rem',
                display: 'flex',
                alignItems: 'center',
                gap: '0.75rem'
              }}>
                <AlertCircle size={18} style={{ color: 'var(--status-rust)', flexShrink: 0 }} />
                <div style={{ fontSize: '0.85rem', color: 'var(--ink)', lineHeight: 1.45 }}>
                  <strong style={{ color: 'var(--status-rust)' }}>Metered pricing rule requires usage events:</strong> No usage telemetry has been uploaded for this dispute line yet. Upload the customer's usage logs via the "Upload Evidence" button above to recalculate the true billable amount.
                </div>
              </div>
            )}

            {/* Per-Line Recalculation Breakdown Table */}
            {calculation.line_results && calculation.line_results.length > 0 && (
              <div style={{ marginTop: '2rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem', flexWrap: 'wrap', gap: '0.5rem' }}>
                  <h4 style={{ fontSize: '1.15rem' }}>
                    Per-Line Recalculated vs. Original Invoice Items
                  </h4>
                  <span className="font-mono" style={{ fontSize: '0.75rem', color: 'var(--ink-muted)' }}>
                    Anchor Hash: {calculation.result_hash?.slice(0, 16)}...
                  </span>
                </div>

                <div className="table-container">
                  <table>
                    <thead>
                      <tr>
                        <th style={{ minWidth: 180 }}>Line Item</th>
                        <th style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>Original Billed</th>
                        <th style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>Recalculated</th>
                        <th style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>Difference</th>
                        <th style={{ textAlign: 'center', whiteSpace: 'nowrap' }}>Classification</th>
                        <th style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>Billable Units</th>
                        <th style={{ minWidth: 260 }}>Engine Explanation & Slabs</th>
                      </tr>
                    </thead>
                    <tbody>
                      {calculation.line_results.map((lr) => {
                        const lineMeta = caseData?.invoice_lines?.find((l) => l.id === lr.line_id);
                        const isOvercharge = lr.difference_cents < 0;
                        const isUndercharge = lr.difference_cents > 0;
                        const isInsufficient = lr.finding_type === 'INSUFFICIENT_DATA';
                        const isAmbiguous = lr.finding_type === 'CONTRACT_AMBIGUITY' || (lr.interpretations && lr.interpretations.length > 0);
                        
                        const interpAmounts = (lr.interpretations || [])
                          .map((i) => i.recalculated_amount_cents)
                          .filter((v) => v != null);
                        const minInterp = interpAmounts.length > 0 ? Math.min(...interpAmounts) : null;
                        const maxInterp = interpAmounts.length > 0 ? Math.max(...interpAmounts) : null;

                        return (
                          <tr key={lr.id || lr.line_id}>
                            <td style={{ minWidth: 180 }}>
                              <div className="font-mono" style={{ fontWeight: 600, color: 'var(--ink)' }}>
                                {lr.line_id}
                              </div>
                              <div style={{ fontSize: '0.78rem', color: 'var(--ink-secondary)', marginTop: '1px' }}>
                                {lineMeta?.description || 'Invoice Line'}
                              </div>
                              <div className="font-mono" style={{ fontSize: '0.68rem', color: 'var(--ink-faint)', marginTop: '2px' }}>
                                Rule: {lr.rule_id} · Anchor: {lr.result_id}
                              </div>
                            </td>
                            <td className="table-money-cell" style={{ whiteSpace: 'nowrap', textAlign: 'right' }}>
                              {formatCents(lr.original_amount_cents)}
                            </td>
                            <td className="table-money-cell" style={{ whiteSpace: 'nowrap', textAlign: 'right', color: 'var(--ink)' }}>
                              {isInsufficient ? (
                                <span style={{ color: 'var(--ink-muted)', fontStyle: 'italic', fontSize: '0.82rem' }}>
                                  — (Uncomputed)
                                </span>
                              ) : isAmbiguous ? (
                                <div>
                                  <span style={{ color: 'var(--status-amber)', fontWeight: 600 }}>
                                    {minInterp != null && maxInterp != null && minInterp !== maxInterp
                                      ? `${formatCents(minInterp)} – ${formatCents(maxInterp)}`
                                      : 'Ambiguous'}
                                  </span>
                                  <div style={{ fontSize: '0.68rem', color: 'var(--status-amber)', fontWeight: 600, marginTop: '1px' }}>
                                    *Human review required
                                  </div>
                                </div>
                              ) : (
                                formatCents(lr.recalculated_amount_cents)
                              )}
                            </td>
                            <td className="table-money-cell" style={{ whiteSpace: 'nowrap', textAlign: 'right' }}>
                              {isInsufficient ? (
                                <span style={{ color: 'var(--status-rust)', fontSize: '0.82rem', fontWeight: 600 }}>
                                  Awaiting Events
                                </span>
                              ) : isAmbiguous ? (
                                <div>
                                  {lr.undisputed_overcharge_cents > 0 ? (
                                    <>
                                      <span style={{ color: 'var(--status-amber)', fontWeight: 600, fontSize: '0.85rem' }}>
                                        {formatDifference(-lr.undisputed_overcharge_cents)}
                                      </span>
                                      <div style={{ fontSize: '0.68rem', color: 'var(--status-amber)', fontWeight: 600, marginTop: '1px' }}>
                                        (Undisputed min overcharge)
                                      </div>
                                    </>
                                  ) : (
                                    <>
                                      <span style={{ color: 'var(--status-amber)', fontWeight: 600, fontSize: '0.82rem' }}>
                                        Ambiguous
                                      </span>
                                      <div style={{ fontSize: '0.68rem', color: 'var(--status-amber)', marginTop: '1px' }}>
                                        Pending review
                                      </div>
                                    </>
                                  )}
                                </div>
                              ) : (
                                <span style={{ color: isOvercharge ? 'var(--status-rust)' : isUndercharge ? 'var(--status-amber)' : 'var(--status-green)', fontWeight: 600 }}>
                                  {formatDifference(lr.difference_cents)}
                                </span>
                              )}
                            </td>
                            <td style={{ textAlign: 'center', whiteSpace: 'nowrap' }}>
                              <span className={`badge ${lr.finding_type === 'CONFIRMED_CALCULATION_DISCREPANCY' ? 'badge-stale' : lr.finding_type === 'CONTRACT_AMBIGUITY' ? 'badge-awaiting' : lr.finding_type === 'INSUFFICIENT_DATA' ? 'badge-stale' : 'badge-resolved'}`}>
                                {lr.finding_type}
                              </span>
                            </td>
                            <td className="font-mono" style={{ fontSize: '0.82rem', whiteSpace: 'nowrap', textAlign: 'right' }}>
                              {Number(lr.quantity_used || 0).toLocaleString()}
                              {lr.exempt_quantity > 0 && (
                                <div style={{ fontSize: '0.68rem', color: 'var(--status-green)', marginTop: '1px' }}>
                                  ({Number(lr.exempt_quantity)} exempt)
                                </div>
                              )}
                            </td>
                            <td style={{ fontSize: '0.8rem', color: 'var(--ink-secondary)', lineHeight: 1.4, minWidth: 260 }}>
                              <div style={{ marginBottom: lr.interpretations?.length ? '0.35rem' : 0 }}>{lr.explanation}</div>
                              {lr.interpretations && lr.interpretations.length > 0 && (
                                <div style={{ padding: '0.5rem 0.65rem', background: 'var(--status-amber-bg)', border: '1px solid var(--status-amber-border)', borderRadius: 'var(--radius-sm)' }}>
                                  <div style={{ fontSize: '0.72rem', fontWeight: 700, color: 'var(--status-amber)', marginBottom: '0.25rem' }}>
                                    ⚠ Competing Interpretations:
                                  </div>
                                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.2rem' }}>
                                    {lr.interpretations.map((interp, idx) => {
                                      const diff = (interp.recalculated_amount_cents != null && lr.original_amount_cents != null)
                                        ? (interp.recalculated_amount_cents - lr.original_amount_cents)
                                        : null;
                                      return (
                                        <div key={idx} style={{ fontSize: '0.72rem', color: 'var(--ink)' }}>
                                          <strong>{interp.interpretation_id || `Option ${idx+1}`}:</strong>{' '}
                                          <span style={{ fontWeight: 600 }}>{formatCents(interp.recalculated_amount_cents)}</span>
                                          {diff != null && (
                                            <span style={{ marginLeft: '4px', color: diff < 0 ? 'var(--status-rust)' : 'var(--status-green)' }}>
                                              ({formatDifference(diff)})
                                            </span>
                                          )}
                                        </div>
                                      );
                                    })}
                                  </div>
                                  {lr.undisputed_overcharge_cents > 0 && (
                                    <div style={{ marginTop: '0.35rem', padding: '0.3rem 0.45rem', background: 'var(--status-teal-bg)', border: '1px solid var(--status-teal-border)', borderRadius: 'var(--radius-xs)', fontSize: '0.7rem' }}>
                                      <strong style={{ color: 'var(--status-teal)' }}>
                                        ✓ Undisputed Min Overcharge: {formatCents(lr.undisputed_overcharge_cents)}
                                      </strong>
                                      <span style={{ color: 'var(--ink-secondary)', marginLeft: '4px' }}>
                                        (Eligible for credit)
                                      </span>
                                    </div>
                                  )}
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
          <div style={{ textAlign: 'center', padding: '3.5rem 1rem', color: 'var(--ink-muted)' }}>
            <p style={{ fontSize: '0.9rem', marginBottom: '1.25rem' }}>
              Click "Run Billing Engine" to execute calculation against current evidence.
            </p>
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={handleRunCalculation}
              disabled={actionLoading}
            >
              <Play size={14} />
              <span>Run Billing Engine</span>
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
