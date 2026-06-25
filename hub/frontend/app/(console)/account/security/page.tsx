import { redirect } from "next/navigation";

/**
 * /account/security — ย้าย Passkey ไปรวมที่หน้า /account (บัญชีของฉัน) แล้ว.
 * คง route เดิมไว้ → redirect กันลิงก์/bookmark เก่าพัง.
 */
export default function SecurityRedirect() {
  redirect("/account");
}
