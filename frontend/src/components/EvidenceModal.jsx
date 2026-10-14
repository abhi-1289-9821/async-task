import React, { useState, useEffect, useRef } from 'react';
import { X, Upload, Sparkles, AlertCircle, FileText, Activity } from 'lucide-react';
import { uploadEvidence, uploadRulesEvidence } from '../api/client';

export default function EvidenceModal({
  isOpen,
  onClose,
  caseId,
  lineId,
  contractRules = [],
  invoiceLines = [],
  onEvidenceUploaded,
}) {
  const [activeTab, setActiveTab] = useState('telemetry'); // 'telemetry' | 'contract'

  // Telemetry Tab state
  const [sourceNote, setSourceNote] = useState('Production telemetry batch ingestion');
  const [quantity, setQuantity] = useState('250');
  const [environment, setEnvironment] = useState('production');
  const [selectedTelemetryLine, setSelectedTelemetryLine] = useState(lineId || '');

  // Contract / Adjustment Tab state
  const [evidenceKind, setEvidenceKind] = useState('rule'); // 'rule' | 'adjustment'
  const [ruleLineId, setRuleLineId] = useState(lineId || '');
  const [ruleType, setRuleType] = useState('TIERED_GRADUATED');
  const [rateCents, setRateCents] = useState('10');
  const [supersedesRuleId, setSupersedesRuleId] = useState('');
  const [ruleSourceNote, setRuleSourceNote] = useState('Contract Amendment Addendum #1');
  const [tiers, setTiers] = useState([
    { up_to: 100, rate_cents: 15 },
    { up_to: null, rate_cents: 10 },
  ]);

  // Adjustment state
  const [adjLineId, setAdjLineId] = useState('');
  const [adjAmountDollars, setAdjAmountDollars] = useState('5.00');
  const [adjDescription, setAdjDescription] = useState('Prior goodwill credit adjustment');

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const modalRef = useRef(null);

  useEffect(() => {
    if (lineId) {
      setSelectedTelemetryLine(lineId);
      setRuleLineId(lineId);
    } else if (invoiceLines.length > 0) {
      setSelectedTelemetryLine(invoiceLines[0].id);
      setRuleLineId(invoiceLines[0].id);
    }
  }, [lineId, invoiceLines]);

  // Accessibility: Escape key listener and focus management
  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e) => {
      if (e.key === 'Escape') {
        onClose();
        return;
      }
      if (e.key === 'Tab' && modalRef.current) {
        const focusableElements = modalRef.current.querySelectorAll(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
        );
        const firstElement = focusableElements[0];
        const lastElement = focusableElements[focusableElements.length - 1];

        if (e.shiftKey) {
          if (document.activeElement === firstElement) {
            lastElement.focus();
            e.preventDefault();
          }
        } else {
          if (document.activeElement === lastElement) {
            firstElement.focus();
            e.preventDefault();
          }
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const generateEventId = () => {
    if (typeof crypto !== 'undefined' && crypto.randomUUID) {
      return `ev-${crypto.randomUUID()}`;
    }
    return `ev-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  };

  const loadPreset = (type) => {
    if (type === 'prod') {
      setSourceNote('Production API telemetry log batch');
      setQuantity('250');
      setEnvironment('production');
    } else if (type === 'staging') {
      setSourceNote('Staging test run logs (contract exempt)');
      setQuantity('100');
      setEnvironment('staging');
    } else if (type === 'reopen') {
      setSourceNote('Late-arriving customer usage reconciliation logs');
      setQuantity('400');
      setEnvironment('production');
    }
  };

  const handleTelemetrySubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    const parsedQty = Number(quantity);
    if (isNaN(parsedQty) || parsedQty < 0) {
      setError('Quantity must be a valid non-negative number');
      setLoading(false);
      return;
    }

    try {
      const eventId = generateEventId();
      const targetLine = selectedTelemetryLine || (invoiceLines[0] ? invoiceLines[0].id : `line-${caseId}-1`);

      const payload = {
        source_note: sourceNote,
        events: [
          {
            event_id: eventId,
            line_id: targetLine,
            timestamp: new Date().toISOString(),
            quantity: parsedQty,
            environment: environment,
          },
        ],
      };

      await uploadEvidence(caseId, payload);
      onEvidenceUploaded();
      onClose();
    } catch (err) {
      setError(err.message || 'Failed to upload telemetry evidence');
    } finally {
      setLoading(false);
    }
  };

  const handleRulesSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    try {
      const targetLine = ruleLineId || (invoiceLines[0] ? invoiceLines[0].id : '');
      if (evidenceKind === 'rule') {
        if (!targetLine) {
          throw new Error('Please select an invoice line for the contract rule');
        }

        const ruleId = `rule-amend-${Date.now().toString().slice(-6)}`;
        const parsedRate = parseInt(rateCents, 10) || 0;

        let parsedTiers = null;
        if (ruleType === 'TIERED_GRADUATED' || ruleType === 'TIERED_VOLUME') {
          parsedTiers = tiers.map((t) => ({
            up_to: t.up_to !== null && t.up_to !== '' ? parseInt(t.up_to, 10) : null,
            rate_cents: parseInt(t.rate_cents, 10) || 0,
          }));
        }

        const payload = {
          source_note: ruleSourceNote,
          contract_rules: [
            {
              id: ruleId,
              line_id: targetLine,
              rule_type: ruleType,
              rate_cents: parsedRate,
              tiers: parsedTiers,
              supersedes_rule_id: supersedesRuleId || null,
            },
          ],
        };

        await uploadRulesEvidence(caseId, payload);
      } else {
        // Manual Adjustment
        const adjId = `adj-${Date.now().toString().slice(-6)}`;
        const amountCents = Math.round(parseFloat(adjAmountDollars || '0') * 100);
        if (isNaN(amountCents) || amountCents <= 0) {
          throw new Error('Adjustment amount must be a positive dollar amount');
        }

        const payload = {
          source_note: ruleSourceNote || 'Manual adjustment evidence',
          adjustments: [
            {
              id: adjId,
              invoice_line_id: adjLineId || null,
              amount_cents: amountCents,
              description: adjDescription,
            },
          ],
        };

        await uploadRulesEvidence(caseId, payload);
      }

      onEvidenceUploaded();
      onClose();
    } catch (err) {
      setError(err.message || 'Failed to upload contract / adjustment evidence');
    } finally {
      setLoading(false);
    }
  };

  // Filter rules that can be superseded
  const activeRulesForLine = contractRules.filter(
    (r) => r.is_active !== false && (!ruleLineId || r.line_id === ruleLineId)
  );

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        ref={modalRef}
        className="modal-content"
        role="dialog"
        aria-modal="true"
        aria-labelledby="evidence-modal-title"
        onClick={(e) => e.stopPropagation()}
        style={{ maxWidth: 620 }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem' }}>
          <div>
            <h3 id="evidence-modal-title" style={{ fontSize: '1.35rem' }}>Upload Dispute Evidence</h3>
            <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
              Bumps evidence version, invalidates stale findings, and auto-reopens resolved cases.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="btn btn-secondary btn-sm"
            aria-label="Close dialog"
            style={{ borderRadius: '50%', width: 32, height: 32, padding: 0 }}
          >
            <X size={16} />
          </button>
        </div>

        {/* Tab Navigation */}
        <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1.25rem', borderBottom: '1px solid var(--border-subtle)', paddingBottom: '0.5rem' }}>
          <button
            type="button"
            className={`btn btn-sm ${activeTab === 'telemetry' ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => { setActiveTab('telemetry'); setError(null); }}
          >
            <Activity size={14} />
            <span>Usage Telemetry</span>
          </button>
          <button
            type="button"
            className={`btn btn-sm ${activeTab === 'contract' ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => { setActiveTab('contract'); setError(null); }}
          >
            <FileText size={14} />
            <span>Contract / Adjustment</span>
          </button>
        </div>

        {error && (
          <div style={{ background: 'rgba(244, 63, 94, 0.1)', border: '1px solid var(--accent-rose)', color: '#fb7185', padding: '0.75rem', borderRadius: 'var(--radius-md)', marginBottom: '1.25rem', fontSize: '0.85rem', display: 'flex', gap: '0.5rem' }}>
            <AlertCircle size={16} />
            <span>{error}</span>
          </div>
        )}

        {/* ── TAB 1: Telemetry Evidence ──────────────────────────────────── */}
        {activeTab === 'telemetry' && (
          <div>
            {/* Quick Presets */}
            <div style={{ marginBottom: '1.25rem', background: 'rgba(255, 255, 255, 0.02)', padding: '0.85rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.78rem', color: 'var(--accent-cyan)', fontWeight: 600, marginBottom: '0.6rem' }}>
                <Sparkles size={14} /> Quick Telemetry Presets:
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
                <button type="button" className="btn btn-secondary btn-sm" onClick={() => loadPreset('prod')}>
                  ⚡ 250 Units (Production)
                </button>
                <button type="button" className="btn btn-secondary btn-sm" onClick={() => loadPreset('staging')}>
                  🛡️ 100 Units (Staging Exempt)
                </button>
                <button type="button" className="btn btn-secondary btn-sm" onClick={() => loadPreset('reopen')}>
                  🔄 Late Logs (Reopens Case)
                </button>
              </div>
            </div>

            <form onSubmit={handleTelemetrySubmit}>
              <div className="form-group">
                <label className="form-label">Audit Source Note</label>
                <input
                  type="text"
                  className="form-input"
                  value={sourceNote}
                  onChange={(e) => setSourceNote(e.target.value)}
                  required
                />
              </div>

              {invoiceLines.length > 1 && (
                <div className="form-group">
                  <label className="form-label">Target Invoice Line</label>
                  <select
                    className="form-select"
                    value={selectedTelemetryLine}
                    onChange={(e) => setSelectedTelemetryLine(e.target.value)}
                  >
                    {invoiceLines.map((l) => (
                      <option key={l.id} value={l.id}>
                        {l.id} - {l.description}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                <div className="form-group">
                  <label className="form-label">Consumed Quantity (Units)</label>
                  <input
                    type="number"
                    step="0.01"
                    className="form-input"
                    value={quantity}
                    onChange={(e) => setQuantity(e.target.value)}
                    required
                  />
                </div>
                <div className="form-group">
                  <label className="form-label">Deployment Environment</label>
                  <select
                    className="form-select"
                    value={environment}
                    onChange={(e) => setEnvironment(e.target.value)}
                  >
                    <option value="production">production</option>
                    <option value="staging">staging (contract exempt)</option>
                    <option value="development">development</option>
                  </select>
                </div>
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem', marginTop: '1.5rem' }}>
                <button type="button" className="btn btn-secondary" onClick={onClose} disabled={loading}>
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary" disabled={loading}>
                  <Upload size={16} />
                  {loading ? 'Uploading...' : 'Ingest Telemetry Evidence'}
                </button>
              </div>
            </form>
          </div>
        )}

        {/* ── TAB 2: Contract Amendment / Adjustment ──────────────────────── */}
        {activeTab === 'contract' && (
          <form onSubmit={handleRulesSubmit}>
            <div style={{ display: 'flex', gap: '1rem', marginBottom: '1.25rem' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.85rem', cursor: 'pointer' }}>
                <input
                  type="radio"
                  name="evidenceKind"
                  checked={evidenceKind === 'rule'}
                  onChange={() => setEvidenceKind('rule')}
                />
                Contract Amendment / Rule
              </label>
              <label style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.85rem', cursor: 'pointer' }}>
                <input
                  type="radio"
                  name="evidenceKind"
                  checked={evidenceKind === 'adjustment'}
                  onChange={() => setEvidenceKind('adjustment')}
                />
                Prior Adjustment / Credit
              </label>
            </div>

            <div className="form-group">
              <label className="form-label">Evidence Source Note</label>
              <input
                type="text"
                className="form-input"
                value={ruleSourceNote}
                onChange={(e) => setRuleSourceNote(e.target.value)}
                placeholder="e.g. Executed Addendum clarifying tiering methodology"
                required
              />
            </div>

            {evidenceKind === 'rule' ? (
              <>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                  <div className="form-group">
                    <label className="form-label">Target Invoice Line</label>
                    <select
                      className="form-select"
                      value={ruleLineId}
                      onChange={(e) => setRuleLineId(e.target.value)}
                    >
                      {invoiceLines.map((l) => (
                        <option key={l.id} value={l.id}>
                          {l.id} - {l.description}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="form-group">
                    <label className="form-label">Rule Type</label>
                    <select
                      className="form-select"
                      value={ruleType}
                      onChange={(e) => setRuleType(e.target.value)}
                    >
                      <option value="TIERED_GRADUATED">TIERED_GRADUATED</option>
                      <option value="TIERED_VOLUME">TIERED_VOLUME</option>
                      <option value="PER_UNIT">PER_UNIT</option>
                      <option value="FLAT">FLAT</option>
                    </select>
                  </div>
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                  <div className="form-group">
                    <label className="form-label">Rate (cents)</label>
                    <input
                      type="number"
                      className="form-input"
                      value={rateCents}
                      onChange={(e) => setRateCents(e.target.value)}
                      placeholder="e.g. 10"
                    />
                  </div>

                  <div className="form-group">
                    <label className="form-label">Supersedes Existing Rule</label>
                    <select
                      className="form-select"
                      value={supersedesRuleId}
                      onChange={(e) => setSupersedesRuleId(e.target.value)}
                    >
                      <option value="">None (Additive Rule)</option>
                      {activeRulesForLine.map((r) => (
                        <option key={r.id} value={r.id}>
                          {r.id} ({r.rule_type} - {r.rate_cents}¢)
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                {(ruleType === 'TIERED_GRADUATED' || ruleType === 'TIERED_VOLUME') && (
                  <div style={{ background: 'rgba(255, 255, 255, 0.02)', padding: '0.85rem', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)', marginBottom: '1rem' }}>
                    <div style={{ fontSize: '0.78rem', color: 'var(--accent-cyan)', fontWeight: 600, marginBottom: '0.5rem' }}>
                      Tier Definition (Tiers must terminate with unbounded final tier):
                    </div>
                    {tiers.map((t, idx) => (
                      <div key={idx} style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', marginBottom: '0.5rem' }}>
                        <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)', width: 60 }}>
                          Tier {idx + 1}:
                        </span>
                        <input
                          type="number"
                          placeholder={idx === tiers.length - 1 ? 'Unbounded' : 'Up to'}
                          disabled={idx === tiers.length - 1}
                          className="form-input"
                          style={{ width: 120, fontSize: '0.8rem' }}
                          value={t.up_to ?? ''}
                          onChange={(e) => {
                            const val = e.target.value === '' ? null : parseInt(e.target.value, 10);
                            const next = [...tiers];
                            next[idx].up_to = val;
                            setTiers(next);
                          }}
                        />
                        <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>Rate:</span>
                        <input
                          type="number"
                          className="form-input"
                          style={{ width: 100, fontSize: '0.8rem' }}
                          value={t.rate_cents}
                          onChange={(e) => {
                            const next = [...tiers];
                            next[idx].rate_cents = e.target.value;
                            setTiers(next);
                          }}
                        />
                        <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>¢</span>
                      </div>
                    ))}
                  </div>
                )}
              </>
            ) : (
              <>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                  <div className="form-group">
                    <label className="form-label">Invoice Line (Optional)</label>
                    <select
                      className="form-select"
                      value={adjLineId}
                      onChange={(e) => setAdjLineId(e.target.value)}
                    >
                      <option value="">Case-Wide Adjustment</option>
                      {invoiceLines.map((l) => (
                        <option key={l.id} value={l.id}>
                          {l.id} - {l.description}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="form-group">
                    <label className="form-label">Adjustment Amount ($)</label>
                    <input
                      type="number"
                      step="0.01"
                      className="form-input"
                      value={adjAmountDollars}
                      onChange={(e) => setAdjAmountDollars(e.target.value)}
                      placeholder="5.00"
                      required
                    />
                  </div>
                </div>

                <div className="form-group">
                  <label className="form-label">Description</label>
                  <input
                    type="text"
                    className="form-input"
                    value={adjDescription}
                    onChange={(e) => setAdjDescription(e.target.value)}
                    placeholder="e.g. Previous courtesy credit"
                    required
                  />
                </div>
              </>
            )}

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem', marginTop: '1.5rem' }}>
              <button type="button" className="btn btn-secondary" onClick={onClose} disabled={loading}>
                Cancel
              </button>
              <button type="submit" className="btn btn-primary" disabled={loading}>
                <Upload size={16} />
                {loading ? 'Uploading...' : 'Submit Contract Amendment'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
