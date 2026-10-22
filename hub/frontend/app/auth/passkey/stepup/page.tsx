"use client";
import { Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { fetchStepupMethods, isPasskeySupported, StepupMethod, stepUpWithPasskey, stepupOtpStart, stepupOtpVerify, stepupWithTotp } from "@/lib/passkey";

function message(e: unknown) {
  if (typeof e === "object" && e && "detail" in e) {
    const d = (e as {detail: unknown}).detail;
    if (typeof d === "object" && d && "message" in d) return String((d as {message: unknown}).message);
    if (typeof d === "string") return d;
  }
  return e instanceof Error ? e.message : "ยืนยันไม่สำเร็จ";
}
export function safeInternalPath(v: string | null) {
  if (!v || !v.startsWith("/") || v.startsWith("//") || v.includes("\\")) return "/dashboard";
  if ([...v].some(c => c.charCodeAt(0) < 32 || c.charCodeAt(0) === 127)) return "/dashboard";
  return v;
}
const labels: Record<StepupMethod, [string,string]> = {
  passkey:["Passkey","ยืนยันด้วยอุปกรณ์ที่ลงทะเบียนไว้"],
  totp:["Authenticator (TOTP)","กรอกรหัส 6 หลักจากแอป Authenticator"],
  email_otp:["Email OTP","รับรหัสทางอีเมลที่ยืนยันแล้ว"],
};
function Inner() {
  const params=useSearchParams();
  const back=useMemo(()=>safeInternalPath(params.get("return_to")),[params]);
  const [methods,setMethods]=useState<StepupMethod[]|null>(null);
  const [mode,setMode]=useState<StepupMethod|null>(null);
  const [code,setCode]=useState(""); const [sent,setSent]=useState(false);
  const [busy,setBusy]=useState(false); const [error,setError]=useState<string|null>(null);
  useEffect(()=>{let live=true; fetchStepupMethods().then(x=>{if(!live)return; setMethods(x.available_methods); if(x.available_methods.length===1)setMode(x.available_methods[0]); else if(x.preferred_method)setMode(x.preferred_method);}).catch(e=>setError(message(e))); return()=>{live=false}},[]);
  const done=()=>{window.location.href=back};
  const run=async(fn:()=>Promise<unknown>)=>{setBusy(true);setError(null);try{await fn();done()}catch(e){setError(message(e))}finally{setBusy(false)}};
  return <main className="min-h-screen grid place-items-center bg-gradient-to-br from-ink-900 via-ink-800 to-brand-900 px-4"><section className="w-full max-w-md rounded-2xl bg-white p-8 shadow-2xl">
    <p className="text-xs font-semibold tracking-wider text-brand-600">STEP-UP VERIFICATION</p><h1 className="mt-1 text-xl font-extrabold">ยืนยันตัวตนอีกครั้ง</h1>
    <p className="mt-2 mb-6 text-sm text-ink-500">กรุณาเลือกวิธีที่ลงทะเบียนไว้และใช้งานได้</p>
    {error&&<div role="alert" className="mb-4 rounded-lg bg-amber-50 p-3 text-sm">{error}</div>}
    {methods===null&&!error&&<p>กำลังตรวจสอบวิธีที่ใช้ได้…</p>}
    {methods?.length===0&&<div><p className="rounded-lg bg-amber-50 p-3 text-sm">ไม่มีวิธียืนยันตัวตนที่ใช้งานได้ จึงไม่สามารถข้าม Step-up ได้</p><a className="mt-3 block text-center text-brand-700" href="/auth/passkey/recover">กู้คืนบัญชีหรือติดต่อผู้ดูแล</a></div>}
    {methods&&methods.length>0&&!mode&&<div className="space-y-3">{methods.map(x=><button key={x} disabled={x==="passkey"&&!isPasskeySupported()} onClick={()=>setMode(x)} className="w-full rounded-xl border p-3 text-left"><b className="block">{labels[x][0]}</b><span className="text-xs">{labels[x][1]}</span></button>)}</div>}
    {mode==="passkey"&&<button disabled={busy||!isPasskeySupported()} onClick={()=>run(stepUpWithPasskey)} className="w-full rounded-xl bg-emerald-600 py-3 text-white">ยืนยันด้วย Passkey</button>}
    {mode==="totp"&&<div className="space-y-3"><input aria-label="รหัส Authenticator" value={code} onChange={e=>setCode(e.target.value.replace(/\D/g,""))} maxLength={8} className="w-full rounded-lg border p-3 text-center"/><button disabled={busy||code.length<6} onClick={()=>run(()=>stepupWithTotp(code))} className="w-full rounded-xl bg-brand-600 py-3 text-white">ยืนยันรหัส Authenticator</button></div>}
    {mode==="email_otp"&&<div className="space-y-3">{!sent?<button disabled={busy} onClick={async()=>{setBusy(true);try{const x=await stepupOtpStart();setSent(true);setError(x.message)}catch(e){setError(message(e))}finally{setBusy(false)}} className="w-full rounded-xl bg-brand-600 py-3 text-white">ส่ง OTP ทาง Email</button>:<><input aria-label="รหัส Email OTP" value={code} onChange={e=>setCode(e.target.value.replace(/\D/g,""))} maxLength={6} className="w-full rounded-lg border p-3 text-center"/><button disabled={busy||code.length!==6} onClick={()=>run(()=>stepupOtpVerify(code))} className="w-full rounded-xl bg-brand-600 py-3 text-white">ยืนยัน Email OTP</button></>}</div>}
    {mode&&methods&&methods.length>1&&<button onClick={()=>{setMode(null);setCode("");setError(null)}} className="mt-4 w-full text-sm">เลือกวิธีอื่น</button>}
    <button onClick={done} className="mt-5 w-full text-xs text-ink-400">ยกเลิก — กลับหน้าเดิม</button>
  </section></main>;
}
export default function Page(){return <Suspense><Inner/></Suspense>}
