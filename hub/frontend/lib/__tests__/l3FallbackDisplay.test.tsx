import { render, screen } from '@testing-library/react';
import { SessionDetailPanel } from '@/app/(console)/ml/_components/SessionDetailPanel';
import type { UserSession, RiskBreakdown } from '@/app/(console)/ml/_types';

jest.mock('@/lib/api', () => ({ clientFetch: jest.fn() }));

function session(fallback?: NonNullable<RiskBreakdown['l3']>['fallback']): UserSession {
  return {
    id: 'session', score: 0.2, decision: 'allow', ip: null, geo_country: null,
    geo_city: null, os_name: null, browser: null, device_type: null,
    is_attack_ip: false, is_account_takeover: false, risk_score: 0.2,
    risk_reasons: [], created_at: '2026-10-02T00:00:00Z', feedback_label: null,
    risk_breakdown: { rule: 0.2, behavior: 0, iforest: 0, iforest_raw: 0.6,
      ...(fallback ? { l3: { fallback } } : {}) },
  };
}

test('shows calibrated role percentile independently from access score', () => {
  render(<SessionDetailPanel session={session({ status: 'warn', user_type: 'teacher',
    percentile: 0.995, warn_percentile: 0.99, reason: 'role_percentile' })} />);
  expect(screen.getByText(/กลุ่ม teacher · Percentile 99.50/)).toBeInTheDocument();
  expect(screen.getByText(/คำเตือนนี้ไม่เปลี่ยนผลอนุญาต/)).toBeInTheDocument();
});

test('abstention does not show missing percentile as zero', () => {
  render(<SessionDetailPanel session={session({ status: 'abstain', user_type: null,
    percentile: null, warn_percentile: null, reason: 'model_mismatch' })} />);
  expect(screen.getByText(/ข้อมูลอ้างอิงยังไม่พร้อม/)).toBeInTheDocument();
  expect(screen.queryByText(/Percentile/)).not.toBeInTheDocument();
});

test('historic sessions without fallback still render', () => {
  render(<SessionDetailPanel session={session()} />);
  expect(screen.queryByText(/L3 ตัวสำรอง/)).not.toBeInTheDocument();
});
