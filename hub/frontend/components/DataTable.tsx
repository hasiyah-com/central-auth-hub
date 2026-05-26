import React from "react";

export type Column<T> = {
  key: string;
  header: string;
  render?: (row: T) => React.ReactNode;
  width?: string;
};

type Props<T> = {
  columns: Column<T>[];
  rows: T[];
  emptyMessage?: string;
};

export function DataTable<T extends Record<string, unknown>>({
  columns,
  rows,
  emptyMessage = "ไม่มีข้อมูล",
}: Props<T>) {
  return (
    <div className="bg-white rounded-xl border border-ink-200 overflow-hidden shadow-sm">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-ink-50">
            <tr>
              {columns.map((col) => (
                <th
                  key={col.key}
                  style={col.width ? { width: col.width } : undefined}
                  className="px-4 py-3 text-left text-[11px] font-bold text-ink-500 uppercase tracking-wider"
                >
                  {col.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-ink-100">
            {rows.length === 0 ? (
              <tr>
                <td
                  colSpan={columns.length}
                  className="px-4 py-12 text-center text-ink-400"
                >
                  {emptyMessage}
                </td>
              </tr>
            ) : (
              rows.map((row, i) => (
                <tr key={i} className="hover:bg-ink-50/50 transition">
                  {columns.map((col) => (
                    <td key={col.key} className="px-4 py-3 text-ink-700">
                      {col.render
                        ? col.render(row)
                        : String(row[col.key] ?? "—")}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
