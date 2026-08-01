import "@testing-library/jest-dom";
/**
 * Component test — DataTable: render rows, empty state, custom render, row click.
 * ใช้ user-event ทดสอบ interaction จริง.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DataTable, type Column } from "@/components/DataTable";

type Row = { id: string; name: string };
const cols: Column<Row>[] = [
  { key: "name", header: "ชื่อ" },
  { key: "go", header: "", render: () => <span>›</span> },
];

describe("DataTable", () => {
  test("แสดงหัวตาราง + แถวข้อมูล", () => {
    render(<DataTable columns={cols} rows={[{ id: "1", name: "สมชาย" }]} />);
    expect(screen.getByText("ชื่อ")).toBeInTheDocument();
    expect(screen.getByText("สมชาย")).toBeInTheDocument();
  });

  test("rows ว่าง → แสดง emptyMessage", () => {
    render(
      <DataTable columns={cols} rows={[]} emptyMessage="ไม่พบผู้ใช้" />
    );
    expect(screen.getByText("ไม่พบผู้ใช้")).toBeInTheDocument();
  });

  test("emptyMessage default เมื่อไม่ระบุ", () => {
    render(<DataTable columns={cols} rows={[]} />);
    expect(screen.getByText("ไม่มีข้อมูล")).toBeInTheDocument();
  });

  test("คลิกแถว → เรียก onRowClick พร้อม row", async () => {
    const onClick = jest.fn();
    render(
      <DataTable
        columns={cols}
        rows={[{ id: "42", name: "คลิกฉัน" }]}
        onRowClick={onClick}
      />
    );
    await userEvent.click(screen.getByText("คลิกฉัน"));
    expect(onClick).toHaveBeenCalledWith({ id: "42", name: "คลิกฉัน" });
  });

  test("custom render column ทำงาน", () => {
    render(<DataTable columns={cols} rows={[{ id: "1", name: "x" }]} />);
    expect(screen.getByText("›")).toBeInTheDocument();
  });
});
