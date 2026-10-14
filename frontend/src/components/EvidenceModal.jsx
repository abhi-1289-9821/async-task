import React, { useState } from 'react';
import { X, Upload, Sparkles, AlertCircle } from 'lucide-react';
import { uploadEvidence } from '../api/client';

export default function EvidenceModal({ isOpen, onClose, caseId, lineId, onEvidenceUploaded }) {
  const [sourceNote, setSourceNote] = useState('Production telemetry batch ingestion');
  const [quantity, setQuantity] = useState('250');
  const [environment, setEnvironment] = useState('production');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  if (!isOpen) return null;

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
    } else if (type === 'amendment') {
      setSourceNote('Contract Amendment Addendum #1 (Explicitly specifies Graduated Tiering)');
      setQuantity('200');
      setEnvironment('production');
    }
  };

  const handleSubmit = async (e) => {
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
      const eventId = `ev-${Date.now().toString().slice(-6)}`;
      
      const payload = {
        source_note: sourceNote,
        events: [
          {
            event_id: eventId,
            line_id: lineId || `line-${caseId}-1`,
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
      setError(err.message || 'Failed to upload evidence');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
          <div>
            <h3 style={{ fontSize: '1.35rem' }}>Upload Usage Evidence</h3>
            <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
              Uploads raw usage events. Bumps evidence version, flags prior findings stale, and auto-reopens resolved cases.
            </p>
          </div>
          <button 
            type="button" 
            onClick={onClose} 
            className="btn btn-secondary btn-sm"
            style={{ borderRadius: '50%', width: 32, height: 32, padding: 0 }}
          >
            <X size={16} />
          </button>
        </div>

        {/* Quick Presets */}
        <div style={{ marginBottom: '1.5rem', background: 'rgba(255, 255, 255, 0.02)', padding: '0.85rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
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
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => loadPreset('amendment')}>
              📜 Contract Amendment
            </button>
          </div>
        </div>

        {error && (
          <div style={{ background: 'rgba(244, 63, 94, 0.1)', border: '1px solid var(--accent-rose)', color: '#fb7185', padding: '0.75rem', borderRadius: 'var(--radius-md)', marginBottom: '1.25rem', fontSize: '0.85rem', display: 'flex', gap: '0.5rem' }}>
            <AlertCircle size={16} />
            <span>{error}</span>
          </div>
        )}

        <form onSubmit={handleSubmit}>
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
    </div>
  );
}
