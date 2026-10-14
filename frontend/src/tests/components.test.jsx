import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import { formatCents, formatDifference } from '../utils/money';
import InvestigationTab from '../components/case-tabs/InvestigationTab';
import CreditsTab from '../components/case-tabs/CreditsTab';
import Navbar from '../components/Navbar';

// ── Test 1: formatCents helper ──────────────────────────────────────────────
describe('formatCents helper', () => {
  it('formats positive cents correctly as dollar strings', () => {
    expect(formatCents(1234)).toBe('$12.34');
    expect(formatCents(5000)).toBe('$50.00');
    expect(formatCents(0)).toBe('$0.00');
  });

  it('formats negative cents with negative sign', () => {
    expect(formatCents(-2500)).toBe('-$25.00');
    expect(formatCents(-50)).toBe('-$0.50');
  });

  it('handles null, undefined, and NaN gracefully', () => {
    expect(formatCents(null)).toBe('-');
    expect(formatCents(undefined)).toBe('-');
    expect(formatCents(NaN)).toBe('-');
  });

  it('formats difference with sign and explanation', () => {
    expect(formatDifference(-1500)).toBe('-$15.00 overcharge');
    expect(formatDifference(1000)).toBe('+$10.00 undercharge');
    expect(formatDifference(0)).toBe('$0.00 (exact)');
  });
});

// ── Test 2: Stale badge renders in InvestigationTab ─────────────────────────
describe('InvestigationTab component', () => {
  it('renders stale evidence badge when finding is marked stale', () => {
    const mockFinding = {
      id: 'f-stale-1',
      calculation_line_result_id: 1,
      finding_type: 'CONFIRMED_CALCULATION_DISCREPANCY',
      is_stale: true,
      stale_reason: 'Evidence version upgraded from v1 to v2',
      narrative: 'Discrepancy identified on compute units.',
      raw_ai_text: 'Discrepancy identified on compute units.',
      citation_ids: ['res_1', 'line-1'],
      citation_validation_passed: true,
      reviews: [],
    };

    render(
      <InvestigationTab
        investigation={{ id: 'inv-1', status: 'COMPLETED', resolution_options: [] }}
        findings={[mockFinding]}
        calculation={{ line_results: [{ id: 1, line_id: 'line-1' }] }}
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

    const badge = screen.getByTestId('stale-finding-badge');
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent('STALE EVIDENCE');
    expect(screen.getByText(/Evidence version upgraded from v1 to v2/i)).toBeInTheDocument();
  });
});

// ── Test 3: Approve-credit button disabled when cap is 0 ────────────────────
describe('CreditsTab component', () => {
  it('disables approve-credit button when allowable credit cap is 0', () => {
    const mockCalculation = {
      line_results: [
        {
          id: 1,
          line_id: 'line-1',
          difference_cents: -5000,
        },
      ],
    };

    const mockFindings = [
      {
        id: 'f-1',
        calculation_line_result_id: 1,
        is_stale: false,
        reviews: [{ action: 'ACCEPT', reviewer: 'reviewer_1' }],
      },
    ];

    const mockCapInfo = {
      eligible_cents: 5000,
      prior_credits_cents: 5000,
      remaining_cap_cents: 0,
    };

    render(
      <CreditsTab
        calculation={mockCalculation}
        findings={mockFindings}
        credits={[{ id: 'c-1', invoice_line_id: 'line-1', amount_cents: 5000 }]}
        capInfo={mockCapInfo}
        caseData={{ invoice_lines: [{ id: 'line-1', description: 'Compute', original_amount_cents: 5000 }] }}
        selectedLineId="line-1"
        setSelectedLineId={vi.fn()}
        creditAmountDollars="0.00"
        setCreditAmountDollars={vi.fn()}
        creditReason="RATE_CALCULATION_ERROR"
        setCreditReason={vi.fn()}
        creditNote=""
        setCreditNote={vi.fn()}
        resolutionOptions={[]}
        selectedResolutionOptionId={null}
        handleApproveCredit={vi.fn()}
        actionLoading={false}
        formatCents={formatCents}
      />
    );

    const button = screen.getByTestId('approve-credit-btn');
    expect(button).toBeDisabled();
    expect(screen.getByText(/Remaining allowable credit cap is \$0\.00/i)).toBeInTheDocument();
  });
});

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    checkHealth: vi.fn().mockResolvedValue({ status: 'ok' }),
  };
});

// ── Test 4: Token modal shows on 401 ────────────────────────────────────────
describe('Navbar component on 401 authError', () => {
  it('opens configure session token modal when authError event is dispatched', async () => {
    await act(async () => {
      render(<Navbar onSelectCase={vi.fn()} activeCaseId={null} />);
    });

    // Initially modal is not shown
    expect(screen.queryByText(/Authentication failed \(401\)/i)).not.toBeInTheDocument();

    // Trigger authError custom event (fired by client.js on HTTP 401)
    act(() => {
      window.dispatchEvent(new CustomEvent('authError', { detail: { status: 401 } }));
    });

    // Token modal must be visible
    expect(screen.getByText(/Authentication failed \(401\)/i)).toBeInTheDocument();
    expect(screen.getByText(/Configure REVIEWER Session Token/i)).toBeInTheDocument();
  });
});
