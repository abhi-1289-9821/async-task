import React, { useEffect, useState } from 'react';
import { Eye, ShieldCheck, Activity, Cpu, Key } from 'lucide-react';
import { getActiveRole, setActiveRole, checkHealth, getToken, setCustomToken } from '../api/client';

export default function Navbar({ onSelectCase, activeCaseId }) {
  const [role, setRole] = useState(getActiveRole());
  const [isHealthy, setIsHealthy] = useState(true);
  const [showTokenModal, setShowTokenModal] = useState(false);
  const [tokenInput, setTokenInput] = useState('');

  useEffect(() => {
    checkHealth()
      .then(() => setIsHealthy(true))
      .catch(() => setIsHealthy(false));
  }, []);

  const handleRoleToggle = (newRole) => {
    setActiveRole(newRole);
    setRole(newRole);
  };

  const openTokenModal = () => {
    setTokenInput(getToken(role));
    setShowTokenModal(true);
  };

  const handleSaveToken = () => {
    setCustomToken(role, tokenInput);
    setShowTokenModal(false);
    setRole((r) => r);
  };

  return (
    <header className="navbar">
      <div 
        className="navbar-brand" 
        onClick={() => onSelectCase(null)}
        role="button"
        tabIndex={0}
      >
        <div className="brand-icon">
          <Cpu size={22} />
        </div>
        <div>
          <div className="brand-title">FairBill</div>
          <div className="brand-subtitle">Autonomous Billing Audit & Governance</div>
        </div>
      </div>

      <div className="navbar-actions">
        {/* API Health indicator */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.78rem', color: isHealthy ? '#34d399' : '#f87171' }}>
          <Activity size={14} className={isHealthy ? 'pulse' : ''} />
          <span>{isHealthy ? 'API Online' : 'API Disconnected'}</span>
        </div>

        {/* Token Management */}
        <button
          type="button"
          className="role-pill-btn"
          style={{ borderColor: getToken(role) ? '#34d399' : '#f59e0b', color: getToken(role) ? '#34d399' : '#f59e0b' }}
          onClick={openTokenModal}
          title="Configure personal Bearer token (never stored in bundle)"
        >
          <Key size={13} />
          <span>{getToken(role) ? 'Token Active' : 'Set Token'}</span>
        </button>

        {/* Demo Role Switcher */}
        <div className="role-pill-group" title="Switch Role Identity">
          <button
            type="button"
            className={`role-pill-btn ${role === 'REVIEWER' ? 'active-reviewer' : ''}`}
            onClick={() => handleRoleToggle('REVIEWER')}
          >
            <ShieldCheck size={13} />
            <span>Reviewer</span>
          </button>
          <button
            type="button"
            className={`role-pill-btn ${role === 'VIEWER' ? 'active-viewer' : ''}`}
            onClick={() => handleRoleToggle('VIEWER')}
          >
            <Eye size={13} />
            <span>Viewer (Read-Only)</span>
          </button>
        </div>
      </div>

      {showTokenModal && (
        <div className="modal-overlay" onClick={() => setShowTokenModal(false)}>
          <div className="modal-content" style={{ maxWidth: '480px' }} onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <Key size={18} color="#38bdf8" />
                <h3 className="modal-title">Configure {role} Session Token</h3>
              </div>
            </div>
            <div className="modal-body">
              <p style={{ fontSize: '0.82rem', color: '#94a3b8', marginBottom: '1rem', lineHeight: '1.4' }}>
                Bearer tokens authenticate reviewer and viewer actions. Tokens are stored only in your local browser session and are never baked into client code bundles.
              </p>
              <div className="form-group">
                <label className="form-label">Personal Bearer Token</label>
                <input
                  type="text"
                  className="form-input"
                  placeholder={`Enter ${role.toLowerCase()} token...`}
                  value={tokenInput}
                  onChange={(e) => setTokenInput(e.target.value)}
                />
              </div>
              <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.75rem', flexWrap: 'wrap' }}>
                <button
                  type="button"
                  className="btn btn-secondary"
                  style={{ fontSize: '0.75rem', padding: '0.3rem 0.6rem' }}
                  onClick={() => setTokenInput('demo-reviewer-token-2026')}
                >
                  Fill Demo Reviewer
                </button>
                <button
                  type="button"
                  className="btn btn-secondary"
                  style={{ fontSize: '0.75rem', padding: '0.3rem 0.6rem' }}
                  onClick={() => setTokenInput('demo-viewer-token-2026')}
                >
                  Fill Demo Viewer
                </button>
                <button
                  type="button"
                  className="btn btn-secondary"
                  style={{ fontSize: '0.75rem', padding: '0.3rem 0.6rem', color: '#f87171' }}
                  onClick={() => setTokenInput('')}
                >
                  Clear Token
                </button>
              </div>
            </div>
            <div className="modal-footer">
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => setShowTokenModal(false)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="btn btn-primary"
                onClick={handleSaveToken}
              >
                Save Token
              </button>
            </div>
          </div>
        </div>
      )}
    </header>
  );
}
