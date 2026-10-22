import { render, screen } from '@testing-library/react';
import { SessionDetailPanel } from '@/app/(console)/ml/_components/SessionDetailPanel';
import type { UserSession } from '@/app/(console)/ml/_types';

jest.mock('@/lib/api', () => ({ clientFetch: jest.fn() }));

function session(): UserSession {
  return { id: 's', score: .489, decision: 'warn', risk_score: 0,
    ip: null, geo_country: null, geo_city: null, os_name: null, browser: null,
    device_type: null, is_attack_ip: false, is_account_takeover: false,
    risk_reasons: [], feedback_label: null, created_at: '2026-10-22T17:00:00Z',
    risk_breakdown: {rule: 0, behavior: 0, iforest: 0, iforest_raw: .489,
      risk_decision: 'allow', l3_fallback: {applied: true, threshold: .4606}} };
}

test('legacy fallback Warn is the final risk badge, not baseline Allow', () => {
  render(<SessionDetailPanel session={session()} />);
  expect(screen.getByText('WARN')).toBeInTheDocument();
  expect(screen.queryByText('ALLOW')).not.toBeInTheDocument();
  expect(screen.getByText(/ผลชั้น 1\+2: ALLOW/)).toBeInTheDocument();
});

test('shows model unavailable instead of a fabricated zero score', () => {
  const s = session(); s.score = 0;
  s.risk_breakdown!.iforest_raw = 0;
  s.risk_breakdown!.l3_fallback = {applied: false};
  s.risk_breakdown!.l3 = {point_available: false, error: 'l3_timeout', shap_status: 'point_unavailable'};
  render(<SessionDetailPanel session={s} />);
  expect(screen.getByText(/IForest: ไม่มีคะแนน/)).toBeInTheDocument();
  expect(screen.getByText(/l3_timeout/)).toBeInTheDocument();
  expect(screen.queryByText(/IForest raw:/)).not.toBeInTheDocument();
});

test('keeps a real zero score visible when point is available', () => {
  const s = session(); s.score = 0; s.risk_breakdown!.iforest_raw = 0;
  s.risk_breakdown!.l3 = {point_available: true};
  render(<SessionDetailPanel session={s} />);
  expect(screen.getByText(/IForest raw: 0.00/)).toBeInTheDocument();
});

test('separates available scoring from missing SHAP and failed sequence', () => {
  const s = session();
  s.risk_breakdown!.l3 = {point_available: true, shap_status: 'explanation_unavailable',
    explainer: 'ready', sequence_error: 'redis_unavailable'};
  render(<SessionDetailPanel session={s} />);
  expect(screen.getByText(/SHAP: ไม่มีคำอธิบาย/)).toBeInTheDocument();
  expect(screen.getByText(/Sequence: redis_unavailable/)).toBeInTheDocument();
  expect(screen.getByText(/IForest raw: 0.49/)).toBeInTheDocument();
});
