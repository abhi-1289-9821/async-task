import React, { useEffect, useState } from 'react';
import { Eye, ShieldCheck, Activity, Cpu, Key } from 'lucide-react';
import { getActiveRole, setActiveRole, checkHealth, getToken, setCustomToken } from '../api/client';

export default function Navbar({ onSelectCase, activeCaseId }) {
  const [role, setRole] = useState(getActiveRole());
  const [isHealthy, setIsHealthy] = useState(true);

  useEffect(() => {
    checkHealth()
      .then(() => setIsHealthy(true))
      .catch(() => setIsHealthy(false));
  }, []);

  const handleRoleToggle = (newRole) => {
    setActiveRole(newRole);
    setRole(newRole);
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
          <div className="brand-title">DisputeIQ Agent</div>
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
          onClick={() => {
            const current = getToken(role);
            const val = window.prompt(`Enter personal ${role} Bearer Token:`, current);
            if (val !== null) {
              setCustomToken(role, val);
              setRole((r) => r);
            }
          }}
          title="Configure personal Bearer token (never stored in bundle)"
        >
          <Key size={13} />
          <span>{getToken(role) ? 'Token Configured' : 'Set Token'}</span>
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
    </header>
  );
}
