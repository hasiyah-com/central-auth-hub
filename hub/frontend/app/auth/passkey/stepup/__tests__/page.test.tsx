import { safeInternalPath } from "../page";
test.each(["//evil.example","/\\\\evil.example","/\tevil.example"])("rejects unsafe return_to %s",v=>expect(safeInternalPath(v)).toBe("/dashboard"));
test("keeps internal path",()=>expect(safeInternalPath("/account?tab=security")).toBe("/account?tab=security"));
