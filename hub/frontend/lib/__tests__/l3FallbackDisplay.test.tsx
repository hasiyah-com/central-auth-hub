import { fireEvent, render, screen } from '@testing-library/react';
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

test('shows every stored point input without pretending unavailable SHAP is zero', () => {
  const s = session();
  s.risk_breakdown!.l3_point_features = [
    { feature: 'hour_of_day', value: 20 },
    { feature: 'day_of_week', value: 4 },
    { feature: 'is_new_device', value: 1 },
    { feature: 'is_thailand', value: 1 },
    { feature: 'passkey_count', value: 2 },
    { feature: 'impossible_travel_score', value: 0 },
  ];
  s.risk_breakdown!.l3 = { point_available: false };
  render(<SessionDetailPanel session={s} />);
  expect(screen.queryByRole('table')).not.toBeInTheDocument();
  expect(screen.getByText('แสดง 5 / 6')).toBeInTheDocument();
  expect(screen.getByText('อุปกรณ์ใหม่')).toBeInTheDocument();
  expect(screen.queryByTitle('impossible_travel_score')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: /ดูเพิ่มเติมทั้งหมด/ }));
  expect(screen.getByTitle('impossible_travel_score')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: /ย่อ/ }));
  expect(screen.getByText(/ยังไม่มีค่า SHAP/)).toBeInTheDocument();
});
