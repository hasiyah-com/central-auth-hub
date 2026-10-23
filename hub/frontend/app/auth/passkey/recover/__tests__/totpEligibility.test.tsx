import { fireEvent, render, screen } from "@testing-library/react";
import RecoverPage from "../page";

jest.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
}));

jest.mock("@/lib/passkey", () => ({
  recoverEmailOtpStart: jest.fn(),
  recoverEmailOtpVerify: jest.fn(),
  recoverWithBackupCode: jest.fn(),
  recoverWithTotp: jest.fn(),
  submitRecoveryRequest: jest.fn(),
  regenOtpStart: jest.fn(),
  regenOtpVerify: jest.fn(),
}));

test("explains that TOTP recovery requires prior enrollment", () => {
  render(<RecoverPage />);
  fireEvent.click(screen.getByRole("tab", { name: /Authenticator/ }));
  expect(screen.getByRole("heading", { name: "Authenticator ที่ลงทะเบียนแล้ว" })).toBeInTheDocument();
  expect(screen.getByText(/ใช้ได้เฉพาะบัญชีที่เปิดใช้งาน Authenticator ไว้ก่อนหน้านี้/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /เข้าสู่ระบบเพื่อลงทะเบียน Authenticator/ })).toHaveAttribute(
    "href",
    "/auth/login",
  );
});
