import { fireEvent, render, screen } from '@testing-library/react';
import { StatusImportModal } from '../StatusImportModal';

test('offers both status update and full new-user import paths', () => {
  render(<StatusImportModal onClose={() => {}} onSaved={() => {}} />);
  expect(screen.getByText(/status_updates/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'เพิ่มผู้ใช้ใหม่' }));
  expect(screen.getByText(/new_users/)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'ยืนยันการเพิ่มผู้ใช้' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'เปลี่ยนสถานะผู้ใช้' }));
  expect(screen.getByText(/status_updates/)).toBeInTheDocument();
});
