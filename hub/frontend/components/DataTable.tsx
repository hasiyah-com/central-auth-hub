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
    <div className="cx-table-wrap">
        <table>
          <thead>
            <tr>
              {columns.map((col) => (
                <th key={col.key} style={col.width ? { width: col.width } : undefined} className={align(col.align)}>
                  {col.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={columns.length}>
                  <div className="cx-empty"><strong>{emptyMessage}</strong><span className="mono">NO DATA</span></div>
                </td>
              </tr>
            ) : rows.map((row, index) => (
              <tr key={index} onClick={onRowClick ? () => onRowClick(row) : undefined} tabIndex={onRowClick ? 0 : undefined} onKeyDown={onRowClick ? (event) => { if (event.key === "Enter" || event.key === " ") onRowClick(row); } : undefined} className={onRowClick ? "cx-clickable-row" : undefined}>
                {columns.map((col) => (
                  <td key={col.key} className={align(col.align)}>
                    {col.render ? col.render(row) : String(row[col.key] ?? "—")}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
    </div>
  );
}

function align(value?: "left" | "right" | "center") {
  return value === "right" ? "text-right" : value === "center" ? "text-center" : "text-left";
}
