import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { UserFormModal } from '../UserFormModal';
import { clientFetch } from '@/lib/api';
jest.mock('@/lib/api', () => ({ clientFetch: jest.fn() }));
const api = clientFetch as jest.Mock;

test('selects existing faculty and major, or enters new values, with a ten-character phone limit', async () => {
  api.mockResolvedValue({ faculties: ['Science'], majors: ['Mathematics'] });
  render(<UserFormModal mode="create" onClose={() => {}} onSaved={() => {}} />);
  await waitFor(() => expect(screen.getByRole('option', { name: 'Science' })).toBeInTheDocument());
  fireEvent.change(screen.getByRole('combobox', { name: 'คณะ' }), { target: { value: 'Science' } });
  fireEvent.change(screen.getByRole('combobox', { name: 'สาขา / ตำแหน่ง' }), { target: { value: '__new__' } });
  fireEvent.change(screen.getByRole('textbox', { name: 'สาขา / ตำแหน่งใหม่' }), { target: { value: 'Physics' } });
  expect(screen.getByRole('textbox', { name: 'สาขา / ตำแหน่งใหม่' })).toHaveValue('Physics');
  expect(screen.getByRole('textbox', { name: 'เบอร์โทร' })).toHaveAttribute('maxLength', '10');
});
