import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import fs from 'fs';
import path from 'path';
import EngineTab from '../components/case-tabs/EngineTab';
import InvestigationTab from '../components/case-tabs/InvestigationTab';
import CreditsTab from '../components/case-tabs/CreditsTab';

// ── TASK 1 GUARD: Static Code Scan Guard ────────────────────────────────────
describe('Currency Hardcoding Static Code Guard', () => {
  function getSourceFiles(dir, fileList = []) {
    const files = fs.readdirSync(dir);
    for (const file of files) {
      const filePath = path.join(dir, file);
      const stat = fs.statSync(filePath);
      if (stat.isDirectory()) {
        if (file !== 'tests' && file !== 'node_modules') {
          getSourceFiles(filePath, fileList);
        }
      } else if (/\.(jsx?|tsx?)$/.test(file)) {
        fileList.push(filePath);
      }
    }
    return fileList;
  }

  const srcDir = path.resolve(__dirname, '..');
  const sourceFiles = getSourceFiles(srcDir);

  it('contains zero instances of template string hardcoded dollar (${...})', () => {
    const violations = [];
    for (const file of sourceFiles) {
      const content = fs.readFileSync(file, 'utf-8');
      const lines = content.split('\n');
      lines.forEach((line, idx) => {
        if (line.includes('${') && line.includes('$$')) {
          // check for $${
          violations.push(`${file}:${idx + 1}: ${line.trim()}`);
        } else if (/\$\$\{/.test(line)) {
          violations.push(`${file}:${idx + 1}: ${line.trim()}`);
        }
      });
    }
    expect(violations, `Found template string dollar hardcoding:\n${violations.join('\n')}`).toEqual([]);
  });

  it('contains zero instances of toFixed(2) outside money.js', () => {
    const violations = [];
    for (const file of sourceFiles) {
      if (file.endsWith('money.js')) continue;
      const content = fs.readFileSync(file, 'utf-8');
      const lines = content.split('\n');
      lines.forEach((line, idx) => {
        if (/toFixed\(2\)/.test(line)) {
          violations.push(`${file}:${idx + 1}: ${line.trim()}`);
        }
      });
    }
    expect(violations, `Found toFixed(2) outside money.js:\n${violations.join('\n')}`).toEqual([]);
  });

  it('contains zero instances of literal "($ USD)" in source code', () => {
    const violations = [];
    for (const file of sourceFiles) {
      const content = fs.readFileSync(file, 'utf-8');
      const lines = content.split('\n');
      lines.forEach((line, idx) => {
        if (line.includes('($ USD)')) {
          violations.push(`${file}:${idx + 1}: ${line.trim()}`);
        }
      });
    }
    expect(violations, `Found "($ USD)" literal in UI source:\n${violations.join('\n')}`).toEqual([]);
  });
});

// ── TASK 1 GUARD: Component Currency Symbol Rendering (EUR and GBP) ─────────
describe('Currency Symbol Rendering on Engine, Investigation, and Credits Tabs', () => {
  const eurCaseData = {
    id: 'case-eur',
    currency: 'EUR',
    disputed_amount_cents: 125000,
    invoice_lines: [
      { id: 'line-1', description: 'Compute usage', original_amount_cents: 125000 },
    ],
  };

  const gbpCaseData = {
    id: 'case-gbp',
    currency: 'GBP',
    disputed_amount_cents: 80000,
    invoice_lines: [
      { id: 'line-1', description: 'API calls', original_amount_cents: 80000 },
    ],
  };

  const mockCalculationEUR = {
    total_original_billed_cents: 125000,
    total_recalculated_cents: 76000,
    total_difference_cents: -49000,
    line_results: [
      {
        id: 1,
        line_id: 'line-1',
        original_amount_cents: 125000,
        recalculated_amount_cents: 76000,
        difference_cents: -49000,
        finding_type: 'CONFIRMED_CALCULATION_DISCREPANCY',
      },
    ],
  };

  const mockCalculationGBP = {
    total_original_billed_cents: 80000,
    total_recalculated_cents: 50000,
    total_difference_cents: -30000,
    line_results: [
      {
        id: 1,
        line_id: 'line-1',
        original_amount_cents: 80000,
        recalculated_amount_cents: 50000,
        difference_cents: -30000,
        finding_type: 'CONFIRMED_CALCULATION_DISCREPANCY',
      },
    ],
  };

  const mockFindingsEUR = [
    {
      id: 'f-eur',
      calculation_line_result_id: 1,
      finding_type: 'CONFIRMED_CALCULATION_DISCREPANCY',
      is_stale: false,
      narrative: 'Overcharge confirmed on line-1.',
      raw_ai_text: 'Overcharge confirmed on line-1.',
      citation_ids: ['res_1'],
      citation_validation_passed: true,
      reviews: [{ action: 'ACCEPT', reviewer: 'reviewer_1' }],
    },
  ];

  it('renders EUR symbol (€) on EngineTab for EUR case and no dollar symbol', () => {
    render(
      <EngineTab
        calculation={mockCalculationEUR}
        calculationLoading={false}
        handleRunCalculation={vi.fn()}
        caseData={eurCaseData}
        currency="EUR"
      />
    );
    // Should have € symbol for amounts
    expect(screen.getAllByText(/€/).length).toBeGreaterThan(0);
    // Should not have any stray dollar sign in rendered text
    expect(screen.queryByText(/\$/)).not.toBeInTheDocument();
  });

  it('renders GBP symbol (£) on EngineTab for GBP case and no dollar symbol', () => {
    render(
      <EngineTab
        calculation={mockCalculationGBP}
        calculationLoading={false}
        handleRunCalculation={vi.fn()}
        caseData={gbpCaseData}
        currency="GBP"
      />
    );
    expect(screen.getAllByText(/£/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/\$/)).not.toBeInTheDocument();
  });

  it('renders EUR symbol (€) on CreditsTab for EUR case and no dollar or ($ USD)', () => {
    const mockLedgerEUR = {
      original_cents: 125000,
      recalculated_cents: 76000,
      gross_discrepancy_cents: -49000,
      eligible_overcharge_cents: 49000,
      verified_adjustments_cents: 10000,
      unverified_adjustments_cents: 20000,
      prior_credits_cents: 0,
      remaining_cap_cents: 39000,
      approval_eligibility: 'ELIGIBLE',
      reason: 'Finding accepted',
    };

    render(
      <CreditsTab
        calculation={mockCalculationEUR}
        findings={mockFindingsEUR}
        credits={[]}
        capInfo={mockLedgerEUR}
        capLedger={mockLedgerEUR}
        caseData={eurCaseData}
        currency="EUR"
        selectedLineId="line-1"
        setSelectedLineId={vi.fn()}
        creditAmountDollars="390.00"
        setCreditAmountDollars={vi.fn()}
        creditReason="RATE_CALCULATION_ERROR"
        setCreditReason={vi.fn()}
        creditNote=""
        setCreditNote={vi.fn()}
        resolutionOptions={[]}
        selectedResolutionOptionId={null}
        handleApproveCredit={vi.fn()}
        actionLoading={false}
      />
    );
    expect(screen.getAllByText(/€/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/USD/)).not.toBeInTheDocument();
    expect(screen.queryByText(/\$/)).not.toBeInTheDocument();
  });

  it('renders EUR symbol (€) on InvestigationTab for EUR case and no dollar symbol', () => {
    render(
      <InvestigationTab
        investigation={{ id: 'inv-1', status: 'COMPLETED', resolution_options: [] }}
        findings={mockFindingsEUR}
        calculation={mockCalculationEUR}
        caseData={eurCaseData}
        currency="EUR"
        actionLoading={false}
        handleTriggerInvestigation={vi.fn()}
        setSelectedFinding={vi.fn()}
        setEditedText={vi.fn()}
        setReviewModalOpen={vi.fn()}
        setSelectedResolutionOptionId={vi.fn()}
        setSelectedLineId={vi.fn()}
        setCreditAmountDollars={vi.fn()}
        setActiveTab={vi.fn()}
      />
    );
    expect(screen.getAllByText(/€/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/\$/)).not.toBeInTheDocument();
  });

  it('all three tabs show the same remaining allowable cap value from the single backend ledger fixture', () => {
    const fixtureLedger = {
      line_id: 'line-1',
      original: 125000,
      recalculated: 76000,
      gross_discrepancy: -49000,
      eligible_overcharge: 49000,
      verified_adjustments: 10000,
      unverified_adjustments: 20000,
      prior_credits: 0,
      remaining_cap: 39000,
      remaining_cap_cents: 39000,
      approval_eligibility: 'ELIGIBLE',
      reason: 'Finding accepted and eligible for credit',
    };

    // 1. CreditsTab
    const { unmount: unmountCredits } = render(
      <CreditsTab
        calculation={mockCalculationEUR}
        findings={mockFindingsEUR}
        credits={[]}
        capInfo={fixtureLedger}
        capLedger={fixtureLedger}
        caseData={eurCaseData}
        currency="EUR"
        selectedLineId="line-1"
        setSelectedLineId={vi.fn()}
        creditAmountDollars="390.00"
        setCreditAmountDollars={vi.fn()}
        creditReason="RATE_CALCULATION_ERROR"
        setCreditReason={vi.fn()}
        creditNote=""
        setCreditNote={vi.fn()}
        resolutionOptions={[]}
        selectedResolutionOptionId={null}
        handleApproveCredit={vi.fn()}
        actionLoading={false}
      />
    );
    expect(screen.getByText('€390.00')).toBeInTheDocument();
    unmountCredits();

    // 2. InvestigationTab
    const { unmount: unmountInv } = render(
      <InvestigationTab
        investigation={{ id: 'inv-1', status: 'COMPLETED', resolution_options: [] }}
        findings={mockFindingsEUR}
        calculation={mockCalculationEUR}
        caseData={eurCaseData}
        currency="EUR"
        capLedger={fixtureLedger}
        actionLoading={false}
        handleTriggerInvestigation={vi.fn()}
        setSelectedFinding={vi.fn()}
        setEditedText={vi.fn()}
        setReviewModalOpen={vi.fn()}
        setSelectedResolutionOptionId={vi.fn()}
        setSelectedLineId={vi.fn()}
        setCreditAmountDollars={vi.fn()}
        setActiveTab={vi.fn()}
      />
    );
    expect(screen.getByText('€390.00')).toBeInTheDocument();
    unmountInv();

    // 3. EngineTab
    const { unmount: unmountEngine } = render(
      <EngineTab
        calculation={mockCalculationEUR}
        calculationLoading={false}
        handleRunCalculation={vi.fn()}
        caseData={eurCaseData}
        currency="EUR"
        capLedger={fixtureLedger}
      />
    );
    expect(screen.getByText('€390.00')).toBeInTheDocument();
    unmountEngine();
  });
});
