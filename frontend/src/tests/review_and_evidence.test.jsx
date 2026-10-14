import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, act, fireEvent, waitFor, within } from '@testing-library/react';
import EvidenceModal from '../components/EvidenceModal';
import CaseDetail from '../components/CaseDetail';
import InvestigationTab from '../components/case-tabs/InvestigationTab';
import * as client from '../api/client';

// Mock the API client
vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    getCase: vi.fn(),
    getCaseEvents: vi.fn(),
    getCaseInvestigations: vi.fn(),
    getCaseFindings: vi.fn(),
    getCaseCredits: vi.fn(),
    getCaseCalculations: vi.fn(),
    getCreditCap: vi.fn(),
    reviewFinding: vi.fn(),
    transitionCase: vi.fn(),
    uploadEvidence: vi.fn(),
    uploadRulesEvidence: vi.fn(),
    runCalculation: vi.fn(),
    triggerInvestigation: vi.fn(),
    approveCredit: vi.fn(),
    getActiveRole: vi.fn(() => 'REVIEWER'),
  };
});

describe('EvidenceModal Component Flow', () => {
  const mockOnClose = vi.fn();
  const mockOnUploaded = vi.fn();
  const sampleInvoiceLines = [
    { id: 'line-test-1', description: 'Compute Instances', original_amount_cents: 5000 },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders modal when isOpen is true', () => {
    render(
      <EvidenceModal
        isOpen={true}
        onClose={mockOnClose}
        caseId="case-101"
        lineId="line-test-1"
        invoiceLines={sampleInvoiceLines}
        onEvidenceUploaded={mockOnUploaded}
      />
    );

    expect(screen.getByText(/Usage Telemetry/i)).toBeInTheDocument();
    expect(screen.getByText(/Contract \/ Adjustment/i)).toBeInTheDocument();
  });

  it('submits valid telemetry evidence successfully and triggers callbacks', async () => {
    client.uploadEvidence.mockResolvedValueOnce({ status: 'ok', evidence_version: 2 });

    render(
      <EvidenceModal
        isOpen={true}
        onClose={mockOnClose}
        caseId="case-101"
        lineId="line-test-1"
        invoiceLines={sampleInvoiceLines}
        onEvidenceUploaded={mockOnUploaded}
      />
    );

    // Fill in quantity and source note
    const qtyInput = screen.getByLabelText(/Consumed Quantity/i);
    fireEvent.change(qtyInput, { target: { value: '450' } });

    const noteInput = screen.getByLabelText(/Audit Source Note/i);
    fireEvent.change(noteInput, { target: { value: 'Production Prometheus metric ingestion' } });

    // Submit telemetry form
    const submitBtn = screen.getByRole('button', { name: /Ingest Telemetry Evidence/i });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(client.uploadEvidence).toHaveBeenCalledTimes(1);
    });

    const [calledCaseId, payload] = client.uploadEvidence.mock.calls[0];
    expect(calledCaseId).toBe('case-101');
    expect(payload.source_note).toBe('Production Prometheus metric ingestion');
    expect(payload.events[0].quantity).toBe(450);
    expect(payload.events[0].environment).toBe('production');

    expect(mockOnUploaded).toHaveBeenCalledTimes(1);
    expect(mockOnClose).toHaveBeenCalledTimes(1);
  });

  it('displays a validation error when quantity is invalid or negative', async () => {
    render(
      <EvidenceModal
        isOpen={true}
        onClose={mockOnClose}
        caseId="case-101"
        lineId="line-test-1"
        invoiceLines={sampleInvoiceLines}
        onEvidenceUploaded={mockOnUploaded}
      />
    );

    const qtyInput = screen.getByLabelText(/Consumed Quantity/i);
    fireEvent.change(qtyInput, { target: { value: '-25' } });

    const submitBtn = screen.getByRole('button', { name: /Ingest Telemetry Evidence/i });
    fireEvent.click(submitBtn);

    expect(await screen.findByText(/Quantity must be a valid non-negative number/i)).toBeInTheDocument();
    expect(client.uploadEvidence).not.toHaveBeenCalled();
    expect(mockOnUploaded).not.toHaveBeenCalled();
  });

  it('updates form fields when preset buttons are clicked', () => {
    render(
      <EvidenceModal
        isOpen={true}
        onClose={mockOnClose}
        caseId="case-101"
        lineId="line-test-1"
        invoiceLines={sampleInvoiceLines}
        onEvidenceUploaded={mockOnUploaded}
      />
    );

    const stagingBtn = screen.getByRole('button', { name: /100 Units \(Staging Exempt\)/i });
    fireEvent.click(stagingBtn);

    const noteInput = screen.getByLabelText(/Audit Source Note/i);
    expect(noteInput.value).toContain('Staging test run logs');
  });
});

describe('Human-in-the-Loop Finding Review Flow in CaseDetail', () => {
  const mockFinding = {
    id: 'f-101',
    calculation_line_result_id: 1,
    invoice_line_id: 'line-test-1',
    finding_type: 'CONFIRMED_CALCULATION_DISCREPANCY',
    is_stale: false,
    raw_ai_text: 'Model evaluated an overcharge of $15.00 on Compute line.',
    narrative: 'Model evaluated an overcharge of $15.00 on Compute line.',
    citation_ids: ['res_1', 'line-test-1', 'rule-1'],
    citation_validation_passed: true,
    reviews: [],
  };

  const sampleCase = {
    id: 'case-test-1',
    customer_id: 'cust-1',
    status: 'OPEN',
    title: 'Acme API Dispute',
    customer_name: 'Acme Corp',
    dispute_title: 'API charges dispute',
    dispute_description: 'Claimed overcharge on compute units',
    billing_period_start: '2026-09-01',
    billing_period_end: '2026-09-30',
    invoice_lines: [{ id: 'line-test-1', description: 'Compute', original_amount_cents: 5000 }],
    contract_rules: [],
  };

  const sampleCalc = {
    id: 'calc-1',
    engine_status: 'OK',
    line_results: [
      {
        id: 1,
        line_id: 'line-test-1',
        original_amount_cents: 5000,
        recalculated_amount_cents: 3500,
        difference_cents: -1500,
      },
    ],
  };

  beforeEach(() => {
    vi.clearAllMocks();
    client.getCase.mockResolvedValue(sampleCase);
    client.getCaseEvents.mockResolvedValue([]);
    client.getCaseInvestigations.mockResolvedValue([{ id: 'inv-1', status: 'COMPLETED', token_usage: {} }]);
    client.getCaseFindings.mockResolvedValue([mockFinding]);
    client.getCaseCredits.mockResolvedValue([]);
    client.getCaseCalculations.mockResolvedValue([sampleCalc]);
    client.getCreditCap.mockResolvedValue({ eligible_cents: 1500, remaining_cap_cents: 1500, prior_credits_cents: 0 });
    client.reviewFinding.mockResolvedValue({ id: 'rev-1', action: 'ACCEPT' });
  });

  it('opens review modal, allows selecting EDIT, editing narrative, and submitting', async () => {
    const onToast = vi.fn();

    await act(async () => {
      render(<CaseDetail caseId="case-test-1" onBack={vi.fn()} onToast={onToast} />);
    });

    // Switch to Investigation Tab using role="tab"
    const invTabBtn = await screen.findByRole('tab', { name: /AI Investigation/i });
    fireEvent.click(invTabBtn);

    // Click "Human Review" button on the finding card
    const reviewBtn = await screen.findByRole('button', { name: /Human Review/i });
    fireEvent.click(reviewBtn);

    // Verify modal is open
    expect(screen.getByText(/Human-in-the-Loop Review/i)).toBeInTheDocument();

    // Select EDIT decision
    const editBtn = screen.getByRole('button', { name: /^Edit$/i });
    fireEvent.click(editBtn);

    // The human edited textarea should now be visible
    const editedTextarea = screen.getByDisplayValue(mockFinding.raw_ai_text);
    fireEvent.change(editedTextarea, {
      target: { value: 'Auditor verified rate tier mismatch: correct overcharge is $15.00.' },
    });

    // Change note
    const noteInput = screen.getByLabelText(/Reviewer Note \/ Justification/i);
    fireEvent.change(noteInput, { target: { value: 'Confirmed by Lead Auditor' } });

    // Submit review
    const submitReviewBtn = screen.getByRole('button', { name: /Submit Review/i });
    fireEvent.click(submitReviewBtn);

    await waitFor(() => {
      expect(client.reviewFinding).toHaveBeenCalledWith('f-101', {
        action: 'EDIT',
        note: 'Confirmed by Lead Auditor',
        edited_text: 'Auditor verified rate tier mismatch: correct overcharge is $15.00.',
      });
    });

    expect(onToast).toHaveBeenCalledWith('success', expect.stringContaining('EDIT'));
  });

  it('submits ACCEPT review without edited text', async () => {
    const onToast = vi.fn();

    await act(async () => {
      render(<CaseDetail caseId="case-test-1" onBack={vi.fn()} onToast={onToast} />);
    });

    const invTabBtn = await screen.findByRole('tab', { name: /AI Investigation/i });
    fireEvent.click(invTabBtn);

    const reviewBtn = await screen.findByRole('button', { name: /Human Review/i });
    fireEvent.click(reviewBtn);

    const submitReviewBtn = screen.getByRole('button', { name: /Submit Review/i });
    fireEvent.click(submitReviewBtn);

    await waitFor(() => {
      expect(client.reviewFinding).toHaveBeenCalledWith('f-101', {
        action: 'ACCEPT',
        note: expect.any(String),
        edited_text: null,
      });
    });
  });
});

describe('Request Additional Information Flow in CaseDetail', () => {
  const findingWithQuestions = {
    id: 'f-202',
    calculation_line_result_id: 1,
    invoice_line_id: 'line-test-1',
    finding_type: 'EVIDENCE_GAP',
    is_stale: false,
    raw_ai_text: 'Missing staging telemetry logs.',
    narrative: 'Missing staging telemetry logs.',
    citation_ids: [],
    citation_validation_passed: true,
    missing_evidence_questions: ['Please provide production API request logs for September 15th-20th.'],
    open_questions: ['Confirm whether staging environment is exempt.'],
    reviews: [],
  };

  const sampleCase = {
    id: 'case-test-2',
    customer_id: 'cust-2',
    status: 'OPEN',
    title: 'Telemetry Gap Dispute',
    customer_name: 'Beta LLC',
    dispute_title: 'Unverified usage',
    billing_period_start: '2026-09-01',
    billing_period_end: '2026-09-30',
    invoice_lines: [{ id: 'line-test-1', description: 'API', original_amount_cents: 10000 }],
  };

  beforeEach(() => {
    vi.clearAllMocks();
    client.getCase.mockResolvedValue(sampleCase);
    client.getCaseEvents.mockResolvedValue([]);
    client.getCaseInvestigations.mockResolvedValue([]);
    client.getCaseFindings.mockResolvedValue([findingWithQuestions]);
    client.getCaseCredits.mockResolvedValue([]);
    client.getCaseCalculations.mockResolvedValue([]);
    client.getCreditCap.mockResolvedValue({ eligible_cents: 0, remaining_cap_cents: 0, prior_credits_cents: 0 });
    client.transitionCase.mockResolvedValue({ id: 'case-test-2', status: 'AWAITING_INFO' });
  });

  it('opens request info modal with AI evidence questions pre-filled and submits with audit note', async () => {
    const onToast = vi.fn();

    await act(async () => {
      render(<CaseDetail caseId="case-test-2" onBack={vi.fn()} onToast={onToast} />);
    });

    // Click "Request Info" button in the case banner
    const requestInfoBtn = await screen.findByTestId('request-info-btn');
    fireEvent.click(requestInfoBtn);

    // Modal should be open
    expect(screen.getByRole('heading', { name: /Request Additional Information/i })).toBeInTheDocument();

    // The textarea should be prefilled with the questions from findingWithQuestions
    const textarea = screen.getByTestId('request-info-textarea');
    expect(textarea.value).toContain('Please provide production API request logs for September 15th-20th.');
    expect(textarea.value).toContain('Confirm whether staging environment is exempt.');

    // Submit the request
    const submitBtn = screen.getByTestId('submit-request-info-btn');
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(client.transitionCase).toHaveBeenCalledWith(
        'case-test-2',
        'AWAITING_INFO',
        expect.stringContaining('Please provide production API request logs')
      );
    });

    expect(onToast).toHaveBeenCalledWith('success', expect.stringContaining('AWAITING_INFO'));
  });
});

describe('Executive Case Investigation Summary in InvestigationTab', () => {
  it('renders executive summary with recovery cap, root cause synthesis, and quick request button', () => {
    const mockFindings = [
      {
        id: 'f-301',
        calculation_line_result_id: 1,
        invoice_line_id: 'line-1',
        finding_type: 'CONFIRMED_CALCULATION_DISCREPANCY',
        is_stale: false,
        raw_ai_text: 'Confirmed overcharge of $20.00.',
        citation_ids: ['res_1', 'line-1'],
        citation_validation_passed: true,
        missing_evidence_questions: ['Provide telemetry logs for staging'],
      },
    ];

    const mockCalc = {
      line_results: [
        {
          id: 1,
          line_id: 'line-1',
          original_amount_cents: 10000,
          recalculated_amount_cents: 8000,
          difference_cents: -2000,
        },
      ],
    };

    const onRequestInfo = vi.fn();

    render(
      <InvestigationTab
        investigation={{ id: 'inv-3', status: 'COMPLETED', token_usage: { provider: 'Gemini', model: 'gemini-2.5-flash', total_tokens: 420 } }}
        findings={mockFindings}
        calculation={mockCalc}
        actionLoading={false}
        handleTriggerInvestigation={vi.fn()}
        setSelectedFinding={vi.fn()}
        setEditedText={vi.fn()}
        setReviewModalOpen={vi.fn()}
        setSelectedResolutionOptionId={vi.fn()}
        setSelectedLineId={vi.fn()}
        setCreditAmountDollars={vi.fn()}
        setActiveTab={vi.fn()}
        onRequestInfo={onRequestInfo}
      />
    );

    // Verify executive summary rendered
    const summaryCard = screen.getByTestId('case-investigation-summary');
    expect(summaryCard).toBeInTheDocument();
    expect(within(summaryCard).getByText(/Case Investigation Summary & Root-Cause Analysis/i)).toBeInTheDocument();
    expect(within(summaryCard).getByText(/\$20\.00/i)).toBeInTheDocument(); // Recovery Cap
    expect(within(summaryCard).getByText(/Root-Cause Synthesis & Operator Directive/i)).toBeInTheDocument();

    // Verify quick action button for missing evidence
    const requestBtn = screen.getByTestId('request-missing-evidence-btn');
    expect(requestBtn).toBeInTheDocument();
    fireEvent.click(requestBtn);
    expect(onRequestInfo).toHaveBeenCalledTimes(1);
  });
});
