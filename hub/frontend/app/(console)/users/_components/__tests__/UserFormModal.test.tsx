import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { UserFormModal } from '../UserFormModal';
import { clientFetch } from '@/lib/api';
jest.mock('@/lib/api', () => ({ clientFetch: jest.fn() }));
const api = clientFetch as jest.Mock;

test('selects existing faculty and major, or enters new values, with a ten-character phone limit', async () => {
  api.mockResolvedValue({ faculties: ['Science', 'Engineering'], majors_by_faculty: {
    Science: ['Mathematics'], Engineering: ['Mechanical', 'Civil'],
  } });
  render(<UserFormModal mode="create" onClose={() => {}} onSaved={() => {}} />);
  await waitFor(() => expect(screen.getByRole('option', { name: 'Science' })).toBeInTheDocument());
  fireEvent.change(screen.getByRole('combobox', { name: 'คณะ' }), { target: { value: 'Science' } });
  expect(screen.getByRole('option', { name: 'Mathematics' })).toBeInTheDocument();
  expect(screen.queryByRole('option', { name: 'Mechanical' })).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole('combobox', { name: 'คณะ' }), { target: { value: 'Engineering' } });
  expect(screen.getByRole('option', { name: 'Mechanical' })).toBeInTheDocument();
  expect(screen.queryByRole('option', { name: 'Mathematics' })).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole('combobox', { name: 'สาขา / ตำแหน่ง' }), { target: { value: '__new__' } });
  fireEvent.change(screen.getByRole('textbox', { name: 'สาขา / ตำแหน่งใหม่' }), { target: { value: 'Physics' } });
  expect(screen.getByRole('textbox', { name: 'สาขา / ตำแหน่งใหม่' })).toHaveValue('Physics');
  expect(screen.getByRole('textbox', { name: 'เบอร์โทร' })).toHaveAttribute('maxLength', '10');
});
