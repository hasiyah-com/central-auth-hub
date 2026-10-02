import { render, screen, waitFor, act } from '@testing-library/react';
import ActivityPage from '../(console)/activity/page';
import { clientFetch } from '@/lib/api';
jest.mock('@/components/Topbar', () => ({ Topbar: () => null }));
jest.mock('@/lib/api', () => ({ clientFetch: jest.fn() }));
const fetchMock = clientFetch as jest.Mock;
const data = { active: [], active_count: 2, items: [], total: 0, window_hours: 24,
  kpis: { total: 0, blocked: 0, challenged: 0, unique_users: 0, avg_risk: null, online: 2 },
  channels: {}, hourly: [] };
beforeEach(() => { fetchMock.mockReset(); });
test('failed initial load reports unknown session status instead of zero online', async () => {
  fetchMock.mockRejectedValue({ detail: 'network failed' });
  render(<ActivityPage />);
  expect(await screen.findByText('network failed')).toBeInTheDocument();
  expect(screen.getByText('สถานะไม่ทราบ')).toBeInTheDocument();
  expect(screen.queryByText('0 ONLINE')).not.toBeInTheDocument();
});
test('refresh failure removes previously displayed online count', async () => {
  fetchMock.mockImplementation((path: string) => Promise.resolve(path.includes('/activity') ? data : []));
  render(<ActivityPage />);
  await screen.findByText('2 ONLINE');
  fetchMock.mockRejectedValue(new Error('offline'));
  await act(async () => { screen.getByText('รีเฟรช').click(); });
  await waitFor(() => expect(screen.queryByText('2 ONLINE')).not.toBeInTheDocument());
  expect(screen.getByText('สถานะไม่ทราบ')).toBeInTheDocument();
});
