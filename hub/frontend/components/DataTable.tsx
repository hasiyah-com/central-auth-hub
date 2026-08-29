import React from "react";

export type Column<T> = {
  key: string;
  header: string;
  render?: (row: T) => React.ReactNode;
  width?: string;
  align?: "left" | "right" | "center";
};

type Props<T> = {
  columns: Column<T>[];
  rows: T[];
  emptyMessage?: string;
  onRowClick?: (row: T) => void;
};

export function DataTable<T extends Record<string, unknown>>({ columns, rows, emptyMessage = "ไม่มีข้อมูล", onRowClick }: Props<T>) {
  return (
    <div className="overflow-hidden rounded-xl border border-ink-200 bg-white">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[680px] text-sm">
          <thead className="sticky top-0 z-[1] bg-ink-50/95 backdrop-blur">
            <tr className="border-b border-ink-200">
              {columns.map((col) => (
                <th key={col.key} style={col.width ? { width: col.width } : undefined} className={`px-4 py-3 text-[10px] font-semibold uppercase tracking-[.12em] text-ink-500 ${align(col.align)}`}>
                  {col.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-ink-100">
            {rows.length === 0 ? (
              <tr>
                <td colSpan={columns.length} className="px-4 py-14 text-center">
                  <div className="mx-auto mb-3 grid h-9 w-9 place-items-center rounded-full border border-dashed border-ink-300 font-mono text-[10px] text-ink-400">00</div>
                  <div className="text-sm font-medium text-ink-500">{emptyMessage}</div>
                </td>
              </tr>
            ) : rows.map((row, index) => (
              <tr key={index} onClick={onRowClick ? () => onRowClick(row) : undefined} tabIndex={onRowClick ? 0 : undefined} onKeyDown={onRowClick ? (event) => { if (event.key === "Enter" || event.key === " ") onRowClick(row); } : undefined} className={`group transition-colors odd:bg-white even:bg-ink-50/25 hover:bg-brand-50/45 ${onRowClick ? "cursor-pointer focus:bg-brand-50/60 focus:outline-none" : ""}`}>
                {columns.map((col) => (
                  <td key={col.key} className={`px-4 py-3.5 text-[13px] text-ink-700 ${align(col.align)}`}>
                    {col.render ? col.render(row) : String(row[col.key] ?? "—")}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function align(value?: "left" | "right" | "center") {
  return value === "right" ? "text-right" : value === "center" ? "text-center" : "text-left";
}
