import React, { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { X, Upload, Sparkles, AlertCircle, FileText, Activity, Plus, Trash2 } from 'lucide-react';
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
    { up_to: 500, rate_cents: 0 },
    { up_to: 1000, rate_cents: 80 },
    { up_to: null, rate_cents: 45 },
  ]);
  const [includedUnits, setIncludedUnits] = useState('0');
  const [overageRateCents, setOverageRateCents] = useState('0');
  const [discountPct, setDiscountPct] = useState('10');
  const [minimumCommitDollars, setMinimumCommitDollars] = useState('0.00');
  const [exemptEnvironments, setExemptEnvironments] = useState('staging, test');

  // Adjustment state
  const [adjLineId, setAdjLineId] = useState('');
  const [adjAmountDollars, setAdjAmountDollars] = useState('5.00');
  const [adjDescription, setAdjDescription] = useState('Prior goodwill credit adjustment');

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleAddTier = () => {
    const last = tiers[tiers.length - 1];
    const prevUpTo = last?.up_to || 500;
    const updated = tiers.map((t, idx) => {
      if (idx === tiers.length - 1 && t.up_to === null) {
        return { ...t, up_to: prevUpTo + 500 };
      }
      return t;
    });
    setTiers([...updated, { up_to: null, rate_cents: 20 }]);
  };

  const handleRemoveTier = (idx) => {
    if (tiers.length <= 1) return;
    const filtered = tiers.filter((_, i) => i !== idx);
    filtered[filtered.length - 1] = { ...filtered[filtered.length - 1], up_to: null };
    setTiers(filtered);
  };

  const validateTiers = () => {
    if (ruleType !== 'TIERED_GRADUATED' && ruleType !== 'TIERED_VOLUME') return null;
    if (!tiers || tiers.length === 0) return 'At least one tier slab is required.';
    let prev = 0;
    for (let i = 0; i < tiers.length; i++) {
      const t = tiers[i];
      const rate = parseInt(t.rate_cents, 10);
      if (isNaN(rate) || rate < 0) return `Tier ${i + 1} rate must be >= 0`;
      if (i < tiers.length - 1) {
        if (t.up_to === null || isNaN(parseInt(t.up_to, 10))) {
          return `Tier ${i + 1} must have a valid upper limit (only final tier is unbounded)`;
        }
        const upTo = parseInt(t.up_to, 10);
        if (upTo <= prev) {
          return `Tier ${i + 1} upper limit (${upTo}) must be greater than previous (${prev})`;
        }
        prev = upTo;
      } else {
        if (t.up_to !== null && t.up_to !== '') {
          return 'The final tier must be unbounded (No upper limit)';
        }
      }
    }
    return null;
  };

  const modalRef = useRef(null);

  const [prevLineId, setPrevLineId] = useState(lineId);
  if (lineId !== prevLineId) {
    setPrevLineId(lineId);
    if (lineId) {
      setSelectedTelemetryLine(lineId);
      setRuleLineId(lineId);
    } else if (invoiceLines.length > 0) {
      setSelectedTelemetryLine(invoiceLines[0].id);
      setRuleLineId(invoiceLines[0].id);
    }
  }

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
        if (focusableElements.length === 0) return;
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

        const tierErr = validateTiers();
        if (tierErr) {
          throw new Error(tierErr);
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
              rate_cents: (ruleType === 'PER_UNIT' || ruleType === 'FLAT') ? parsedRate : 0,
              tiers: parsedTiers,
              discount_pct: ruleType === 'DISCOUNT_PCT' ? parseFloat(discountPct || '0') : null,
              minimum_commit_cents: ruleType === 'MINIMUM_COMMIT' ? Math.round(parseFloat(minimumCommitDollars || '0') * 100) : 0,
              included_units: ruleType === 'INCLUDED_UNITS' ? parseInt(includedUnits || '0', 10) : 0,
              overage_rate_cents: ruleType === 'INCLUDED_UNITS' ? parseInt(overageRateCents || '0', 10) : null,
              exempt_environments: exemptEnvironments.split(',').map((s) => s.trim()).filter(Boolean),
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

  const modalElement = (
    <div className="modal-overlay" onClick={onClose} role="dialog" aria-modal="true" aria-labelledby="evidence-modal-title">
      <div
        ref={modalRef}
        className="modal-content"
        onClick={(e) => e.stopPropagation()}
        style={{ maxWidth: 640 }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '1.25rem' }}>
          <div>
            <div className="eyebrow" style={{ marginBottom: '0.35rem' }}>02 · Evidence Ingestion & Versioning</div>
            <h3 id="evidence-modal-title" style={{ fontFamily: 'var(--font-serif)', fontSize: '1.45rem', fontWeight: 600, letterSpacing: '-0.02em', margin: 0 }}>
              Upload Dispute Evidence
            </h3>
            <p style={{ fontSize: '0.82rem', color: 'var(--ink-muted)', marginTop: '0.25rem', marginBottom: 0 }}>
              Bumps evidence version, automatically marks dependent findings as STALE, and triggers dispute recalculation.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="btn btn-secondary btn-sm"
            aria-label="Close dialog"
            style={{ borderRadius: '50%', width: 32, height: 32, padding: 0 }}
          >
            <X size={15} />
          </button>
        </div>

        {/* Tab Navigation */}
        <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1.25rem', borderBottom: '1px solid var(--border)', paddingBottom: '0.5rem' }}>
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
          <div style={{ 
            background: 'var(--danger-bg)', 
            border: '1px solid var(--danger-border)', 
            color: 'var(--danger-text)', 
            padding: '0.75rem 1rem', 
            borderRadius: 'var(--radius-md)', 
            marginBottom: '1.25rem', 
            fontSize: '0.82rem', 
            display: 'flex', 
            gap: '0.6rem',
            alignItems: 'flex-start'
          }}>
            <AlertCircle size={16} style={{ flexShrink: 0, marginTop: 2 }} />
            <span>{error}</span>
          </div>
        )}

        {/* ── TAB 1: Telemetry Evidence ──────────────────────────────────── */}
        {activeTab === 'telemetry' && (
          <div>
            {/* Quick Presets */}
            <div style={{ 
              marginBottom: '1.25rem', 
              background: 'var(--bg-subtle)', 
              padding: '0.85rem 1rem', 
              borderRadius: 'var(--radius-md)', 
              border: '1px solid var(--border)' 
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.75rem', color: 'var(--ink-muted)', fontWeight: 600, letterSpacing: '0.04em', textTransform: 'uppercase', marginBottom: '0.6rem' }}>
                <Sparkles size={13} style={{ color: 'var(--accent)' }} /> Quick Telemetry Presets:
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
                <button type="button" className="btn btn-secondary btn-sm" onClick={() => loadPreset('prod')}>
                  250 Units (Production)
                </button>
                <button type="button" className="btn btn-secondary btn-sm" onClick={() => loadPreset('staging')}>
                  100 Units (Staging Exempt)
                </button>
                <button type="button" className="btn btn-secondary btn-sm" onClick={() => loadPreset('reopen')}>
                  Late Logs (Reopens Case)
                </button>
              </div>
            </div>

            <form onSubmit={handleTelemetrySubmit}>
              <div className="form-group">
                <label className="form-label" htmlFor="telemetry-source-note">Audit Source Note</label>
                <input
                  id="telemetry-source-note"
                  type="text"
                  className="form-input"
                  value={sourceNote}
                  onChange={(e) => setSourceNote(e.target.value)}
                  required
                />
              </div>

              {invoiceLines.length > 1 && (
                <div className="form-group">
                  <label className="form-label" htmlFor="telemetry-line-select">Target Invoice Line</label>
                  <select
                    id="telemetry-line-select"
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

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem', marginBottom: '1.25rem' }}>
                <div className="form-group" style={{ marginBottom: 0 }}>
                  <label className="form-label" htmlFor="telemetry-quantity">Consumed Quantity (Units)</label>
                  <input
                    id="telemetry-quantity"
                    type="number"
                    step="0.01"
                    className="form-input font-mono"
                    value={quantity}
                    onChange={(e) => setQuantity(e.target.value)}
                    required
                  />
                </div>
                <div className="form-group" style={{ marginBottom: 0 }}>
                  <label className="form-label" htmlFor="telemetry-environment">Deployment Environment</label>
                  <select
                    id="telemetry-environment"
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

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem' }}>
                <button type="button" className="btn btn-secondary" onClick={onClose} disabled={loading}>
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary" disabled={loading}>
                  <Upload size={15} />
                  {loading ? 'Uploading...' : 'Ingest Telemetry Evidence'}
                </button>
              </div>
            </form>
          </div>
        )}

        {/* ── TAB 2: Contract Amendment / Adjustment ──────────────────────── */}
        {activeTab === 'contract' && (
          <form onSubmit={handleRulesSubmit}>
            <div style={{ display: 'flex', gap: '1.25rem', marginBottom: '1.25rem' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', fontSize: '0.85rem', cursor: 'pointer', fontWeight: 500 }}>
                <input
                  type="radio"
                  name="evidenceKind"
                  checked={evidenceKind === 'rule'}
                  onChange={() => setEvidenceKind('rule')}
                />
                Contract Amendment / Rule
              </label>
              <label style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', fontSize: '0.85rem', cursor: 'pointer', fontWeight: 500 }}>
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
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem', marginBottom: '1rem' }}>
                  <div className="form-group" style={{ marginBottom: 0 }}>
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

                  <div className="form-group" style={{ marginBottom: 0 }}>
                    <label className="form-label">Rule Type</label>
                    <select
                      className="form-select font-mono"
                      value={ruleType}
                      onChange={(e) => setRuleType(e.target.value)}
                    >
                      <option value="TIERED_GRADUATED">TIERED_GRADUATED (Graduated Slabs)</option>
                      <option value="TIERED_VOLUME">TIERED_VOLUME (Volume Slabs)</option>
                      <option value="PER_UNIT">PER_UNIT (Flat Per Unit Rate)</option>
                      <option value="FLAT">FLAT (Fixed Platform / Line Charge)</option>
                      <option value="INCLUDED_UNITS">INCLUDED_UNITS (Included Units + Overage)</option>
                      <option value="DISCOUNT_PCT">DISCOUNT_PCT (Percentage Discount)</option>
                      <option value="MINIMUM_COMMIT">MINIMUM_COMMIT (Floor Commitment)</option>
                    </select>
                  </div>
                </div>

                {/* Dynamic fields based on rule type */}
                {(ruleType === 'PER_UNIT' || ruleType === 'FLAT') && (
                  <div className="form-group" style={{ marginBottom: '1rem' }}>
                    <label className="form-label">{ruleType === 'FLAT' ? 'Fixed Amount (cents)' : 'Unit Rate (cents)'}</label>
                    <input
                      type="number"
                      className="form-input font-mono"
                      value={rateCents}
                      onChange={(e) => setRateCents(e.target.value)}
                      placeholder="e.g. 10"
                      required
                    />
                  </div>
                )}

                {ruleType === 'INCLUDED_UNITS' && (
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem', marginBottom: '1rem' }}>
                    <div className="form-group" style={{ marginBottom: 0 }}>
                      <label className="form-label">Included Units (Free)</label>
                      <input
                        type="number"
                        className="form-input font-mono"
                        value={includedUnits}
                        onChange={(e) => setIncludedUnits(e.target.value)}
                        placeholder="e.g. 500"
                        required
                      />
                    </div>
                    <div className="form-group" style={{ marginBottom: 0 }}>
                      <label className="form-label">Overage Rate (cents/unit)</label>
                      <input
                        type="number"
                        className="form-input font-mono"
                        value={overageRateCents}
                        onChange={(e) => setOverageRateCents(e.target.value)}
                        placeholder="e.g. 80"
                        required
                      />
                    </div>
                  </div>
                )}

                {ruleType === 'DISCOUNT_PCT' && (
                  <div className="form-group" style={{ marginBottom: '1rem' }}>
                    <label className="form-label">Discount Percentage (0–100%)</label>
                    <input
                      type="number"
                      step="0.1"
                      min="0"
                      max="100"
                      className="form-input font-mono"
                      value={discountPct}
                      onChange={(e) => setDiscountPct(e.target.value)}
                      placeholder="10"
                      required
                    />
                  </div>
                )}

                {ruleType === 'MINIMUM_COMMIT' && (
                  <div className="form-group" style={{ marginBottom: '1rem' }}>
                    <label className="form-label">Minimum Floor Commitment ($ USD)</label>
                    <input
                      type="number"
                      step="0.01"
                      className="form-input font-mono"
                      value={minimumCommitDollars}
                      onChange={(e) => setMinimumCommitDollars(e.target.value)}
                      placeholder="500.00"
                      required
                    />
                  </div>
                )}

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem', marginBottom: '1rem' }}>
                  <div className="form-group" style={{ marginBottom: 0 }}>
                    <label className="form-label">Exempt Environments (Optional)</label>
                    <input
                      type="text"
                      className="form-input font-mono"
                      value={exemptEnvironments}
                      onChange={(e) => setExemptEnvironments(e.target.value)}
                      placeholder="e.g. staging, test"
                    />
                  </div>

                  <div className="form-group" style={{ marginBottom: 0 }}>
                    <label className="form-label">Supersedes Existing Rule</label>
                    <select
                      className="form-select"
                      value={supersedesRuleId}
                      onChange={(e) => setSupersedesRuleId(e.target.value)}
                    >
                      <option value="">None (Additive / Competing Rule)</option>
                      {activeRulesForLine.map((r) => (
                        <option key={r.id} value={r.id}>
                          {r.id} ({r.rule_type} - {r.rate_cents}¢)
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                {(ruleType === 'TIERED_GRADUATED' || ruleType === 'TIERED_VOLUME') && (
                  <div style={{ 
                    background: 'var(--bg-subtle)', 
                    padding: '0.85rem 1rem', 
                    borderRadius: 'var(--radius-md)', 
                    border: '1px solid var(--border)', 
                    marginBottom: '1.25rem' 
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                      <div className="eyebrow">
                        {ruleType === 'TIERED_GRADUATED' ? 'Graduated Tier Slabs' : 'Volume Tier Slabs'}:
                      </div>
                      <button
                        type="button"
                        className="btn btn-secondary btn-sm"
                        style={{ fontSize: '0.75rem', padding: '0.2rem 0.5rem' }}
                        onClick={handleAddTier}
                      >
                        <Plus size={12} /> Add Slab
                      </button>
                    </div>
                    {tiers.map((t, idx) => (
                      <div key={idx} style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', marginBottom: '0.5rem' }}>
                        <span style={{ fontSize: '0.8rem', color: 'var(--ink-muted)', width: 65, fontWeight: 500 }}>
                          Tier {idx + 1}:
                        </span>
                        <input
                          type="number"
                          placeholder={idx === tiers.length - 1 ? 'Unbounded (∞)' : 'Up to'}
                          disabled={idx === tiers.length - 1}
                          className="form-input font-mono"
                          style={{ width: 130, fontSize: '0.82rem', padding: '0.35rem 0.5rem' }}
                          value={t.up_to ?? ''}
                          onChange={(e) => {
                            const val = e.target.value === '' ? null : parseInt(e.target.value, 10);
                            const next = [...tiers];
                            next[idx].up_to = val;
                            setTiers(next);
                          }}
                        />
                        <span style={{ fontSize: '0.8rem', color: 'var(--ink-muted)' }}>Rate:</span>
                        <input
                          type="number"
                          className="form-input font-mono"
                          style={{ width: 90, fontSize: '0.82rem', padding: '0.35rem 0.5rem' }}
                          value={t.rate_cents}
                          onChange={(e) => {
                            const next = [...tiers];
                            next[idx].rate_cents = e.target.value;
                            setTiers(next);
                          }}
                        />
                        <span style={{ fontSize: '0.8rem', color: 'var(--ink-muted)' }}>¢</span>
                        {tiers.length > 1 && (
                          <button
                            type="button"
                            className="btn btn-secondary btn-sm"
                            style={{ padding: '0.25rem', color: 'var(--status-rust)' }}
                            onClick={() => handleRemoveTier(idx)}
                            title="Remove tier"
                          >
                            <Trash2 size={12} />
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </>
            ) : (
              <>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem', marginBottom: '1rem' }}>
                  <div className="form-group" style={{ marginBottom: 0 }}>
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
                  <div className="form-group" style={{ marginBottom: 0 }}>
                    <label className="form-label">Adjustment Amount ($ USD)</label>
                    <input
                      type="number"
                      step="0.01"
                      className="form-input font-mono"
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

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem', marginTop: '1.25rem' }}>
              <button type="button" className="btn btn-secondary" onClick={onClose} disabled={loading}>
                Cancel
              </button>
              <button type="submit" className="btn btn-primary" disabled={loading}>
                <Upload size={15} />
                {loading ? 'Uploading...' : 'Submit Contract Amendment'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );

  return typeof document !== 'undefined' ? createPortal(modalElement, document.body) : modalElement;
}

