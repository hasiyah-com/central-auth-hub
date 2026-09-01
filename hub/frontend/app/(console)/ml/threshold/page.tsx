"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Topbar } from "@/components/Topbar";
import { clientFetch } from "@/lib/api";
import type { Overview, ThresholdPreview } from "../_types";

export default function ThresholdPage() {
  // Init sliders จาก current .env thresholds
  const [blockT, setBlockT] = useState(0.7);
  const [mfaT, setMfaT] = useState(0.4);
  const [currentThresholds, setCurrentThresholds] = useState<{
    block: number;
    mfa: number;
  } | null>(null);

  const [preview, setPreview] = useState<ThresholdPreview | null>(null);
  const [pvLoading, setPvLoading] = useState(false);

  // Fetch current thresholds จาก overview (ครั้งเดียวตอน mount)
  useEffect(() => {
    clientFetch<Overview>("/admin/ml/overview?days=1").then((ov) => {
      const t = ov.meta.thresholds;
      setCurrentThresholds(t);
      setBlockT(t.block);
      setMfaT(t.mfa);
    });
  }, []);

  // Debounce 300ms เรียก preview API เมื่อ slider เปลี่ยน
  useEffect(() => {
    if (mfaT >= blockT) return;
    const t = setTimeout(() => {
      setPvLoading(true);
      clientFetch<ThresholdPreview>(
        `/admin/ml/threshold/preview?block=${blockT}&mfa=${mfaT}&days=30`
      )
        .then(setPreview)
        .catch(() => setPreview(null))
        .finally(() => setPvLoading(false));
    }, 300);
    return () => clearTimeout(t);
  }, [blockT, mfaT]);

  const fmt = (n: number) => n.toLocaleString("en-US");

  return (
    <>
      <Topbar title="Threshold Tuning" />
      <main className="signal-page">
        {/* Breadcrumb */}
        <Link
          href="/ml"
          className="text-xs text-ink-500 hover:text-brand-600 underline"
        >
          &larr; ML Overview
        </Link>

        {/* Header */}
        <div className="mt-3 mb-6">
          <h2 className="text-2xl font-extrabold text-ink-900">
            Threshold Tuning
          </h2>
          <p className="text-sm text-ink-500 mt-1 max-w-2xl">
            จำลองว่าถ้าเปลี่ยน threshold จะส่งผลอย่างไรกับ sessions ที่บันทึกไว้ (30 วัน)
            ไม่ retrain model — แค่ apply threshold ใหม่กับ scores ที่มีอยู่
          </p>
        </div>

        {/* 2-column layout */}
        <div className="grid grid-cols-1 lg:grid-cols-[1fr_1.4fr] gap-4">
          {/* Left: Sliders */}
          <div className="bg-white rounded-xl border border-ink-200 shadow-sm p-6">
            <div className="mb-5">
              <div className="flex items-baseline justify-between mb-2">
                <label className="text-xs font-bold text-ink-500 uppercase tracking-wider">
                  Block threshold
                </label>
                <span className="text-2xl font-extrabold text-rose-600 tabular-nums">
                  {blockT.toFixed(2)}
                </span>
              </div>
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={blockT}
                onChange={(e) => setBlockT(Number(e.target.value))}
                className="w-full accent-rose-500"
              />
              <div className="text-[10px] text-ink-400 mt-1">
                score &gt;= {blockT.toFixed(2)} &rarr; block
              </div>
            </div>

            <div className="mb-3">
              <div className="flex items-baseline justify-between mb-2">
                <label className="text-xs font-bold text-ink-500 uppercase tracking-wider">
                  MFA threshold
                </label>
                <span className="text-2xl font-extrabold text-amber-600 tabular-nums">
                  {mfaT.toFixed(2)}
                </span>
              </div>
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={mfaT}
                onChange={(e) => setMfaT(Number(e.target.value))}
                className="w-full accent-amber-500"
              />
              <div className="text-[10px] text-ink-400 mt-1">
                score &gt;= {mfaT.toFixed(2)} &rarr; mfa (และต่ำกว่า block)
              </div>
            </div>

            {mfaT >= blockT && (
              <div className="mt-3 p-2 rounded bg-rose-50 border border-rose-200 text-xs text-rose-700">
                ⚠ MFA threshold ต้องน้อยกว่า Block threshold
              </div>
            )}

            <div className="mt-4 pt-4 border-t border-ink-100 text-[11px] text-ink-500 space-y-1">
              <div className="flex justify-between">
                <span>ค่าปัจจุบันใน .env</span>
                <span className="font-mono">
                  B={currentThresholds?.block ?? "…"} · M=
                  {currentThresholds?.mfa ?? "…"}
                </span>
              </div>
              {currentThresholds && (blockT !== currentThresholds.block || mfaT !== currentThresholds.mfa) && (
                <div className="flex justify-between text-brand-600 font-semibold">
                  <span>Proposed</span>
                  <span className="font-mono">
                    B={blockT.toFixed(2)} · M={mfaT.toFixed(2)}
                  </span>
                </div>
              )}
            </div>
          </div>

          {/* Right: Simulated breakdown */}
          <div className="bg-white rounded-xl border border-ink-200 shadow-sm p-6">
            <div className="flex items-baseline justify-between mb-5">
              <h4 className="text-xs font-bold text-ink-500 uppercase tracking-wider">
                Simulated · 30 วัน
              </h4>
              {pvLoading && (
                <span className="text-[10px] text-ink-400 animate-pulse">
                  ● computing…
                </span>
              )}
            </div>

            {preview ? (
              <>
                <div className="grid grid-cols-3 gap-3 mb-5">
                  <SimCell
                    label="Pass"
                    value={fmt(preview.data.simulated_breakdown.pass)}
                    tone="good"
                  />
                  <SimCell
                    label="MFA"
                    value={fmt(preview.data.simulated_breakdown.mfa)}
                    tone="warn"
                  />
                  <SimCell
                    label="Block"
                    value={fmt(preview.data.simulated_breakdown.block)}
                    tone="danger"
                  />
                </div>

                {/* Current vs Proposed delta */}
                {currentThresholds && (
                  <div className="mb-5 p-3 rounded-lg bg-ink-50 border border-ink-200">
                    <div className="text-[11px] font-bold text-ink-500 uppercase tracking-wider mb-2">
                      Current &rarr; Proposed
                    </div>
                    <div className="grid grid-cols-3 gap-3 text-center text-xs">
                      <DeltaCell
                        label="Pass"
                        current={preview.data.current_breakdown.pass ?? 0}
                        proposed={preview.data.simulated_breakdown.pass}
                      />
                      <DeltaCell
                        label="MFA"
                        current={
                          (preview.data.current_breakdown.mfa ?? 0) +
                          (preview.data.current_breakdown.would_mfa ?? 0)
                        }
                        proposed={preview.data.simulated_breakdown.mfa}
                      />
                      <DeltaCell
                        label="Block"
                        current={
                          (preview.data.current_breakdown.block ?? 0) +
                          (preview.data.current_breakdown.would_block ?? 0)
                        }
                        proposed={preview.data.simulated_breakdown.block}
                      />
                    </div>
                  </div>
                )}

                <div className="pt-4 border-t border-ink-100">
                  <div className="text-[11px] font-bold text-ink-500 uppercase tracking-wider mb-2">
                    Feedback (ground truth)
                  </div>
                  <div className="grid grid-cols-3 gap-3 text-center">
                    <div>
                      <div className="text-[10px] text-ink-400 uppercase">TP</div>
                      <div className="text-xl font-extrabold text-ink-900">
                        {preview.data.with_feedback.true_positive}
                      </div>
                    </div>
                    <div>
                      <div className="text-[10px] text-ink-400 uppercase">FP</div>
                      <div className="text-xl font-extrabold text-ink-900">
                        {preview.data.with_feedback.false_positive}
                      </div>
                    </div>
                    <div>
                      <div className="text-[10px] text-ink-400 uppercase">
                        Precision
                      </div>
                      <div className="text-xl font-extrabold text-emerald-600">
                        {preview.data.with_feedback.precision_estimate !== null
                          ? `${(preview.data.with_feedback.precision_estimate * 100).toFixed(1)}%`
                          : "—"}
                      </div>
                    </div>
                  </div>
                </div>
              </>
            ) : (
              <div className="text-center py-12 text-ink-400 text-sm">
                เลื่อน slider เพื่อจำลอง
              </div>
            )}
          </div>
        </div>
      </main>
    </>
  );
}

// ── Helpers ──

function SimCell({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "good" | "warn" | "danger";
}) {
  const colors = {
    good: "bg-emerald-50 border-emerald-200 text-emerald-700",
    warn: "bg-amber-50 border-amber-200 text-amber-700",
    danger: "bg-rose-50 border-rose-200 text-rose-700",
  }[tone];
  return (
    <div className={`rounded-lg border p-3 text-center ${colors}`}>
      <div className="text-[10px] font-bold uppercase tracking-wider opacity-80">
        {label}
      </div>
      <div className="text-2xl font-extrabold tabular-nums mt-1">{value}</div>
    </div>
  );
}

function DeltaCell({
  label,
  current,
  proposed,
}: {
  label: string;
  current: number;
  proposed: number;
}) {
  const diff = proposed - current;
  const sign = diff > 0 ? "+" : "";
  const color =
    diff === 0 ? "text-ink-500" : diff > 0 ? "text-rose-600" : "text-emerald-600";
  return (
    <div>
      <div className="text-[10px] text-ink-400 uppercase">{label}</div>
      <div className="font-mono font-bold text-ink-700">
        {current} &rarr; {proposed}
      </div>
      {diff !== 0 && (
        <div className={`text-[10px] font-bold ${color}`}>
          {sign}{diff}
        </div>
      )}
    </div>
  );
}
