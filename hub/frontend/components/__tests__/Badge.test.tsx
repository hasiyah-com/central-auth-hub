import "@testing-library/jest-dom";
/**
 * Component test — Badge (render + tone). ใช้ React Testing Library.
 */
import { render, screen } from "@testing-library/react";
import { Badge } from "@/components/Badge";

describe("Badge", () => {
  test("แสดง children", () => {
    render(<Badge>ทดสอบ</Badge>);
    expect(screen.getByText("ทดสอบ")).toBeInTheDocument();
  });

  test("tone=good → คลาสสีเขียว (emerald)", () => {
    render(<Badge tone="good">active</Badge>);
    expect(screen.getByText("active").className).toContain("emerald");
  });

  test("tone=danger → คลาสสีแดง (rose)", () => {
    render(<Badge tone="danger">deleted</Badge>);
    expect(screen.getByText("deleted").className).toContain("rose");
  });

  test("default tone เมื่อไม่ระบุ", () => {
    render(<Badge>x</Badge>);
    expect(screen.getByText("x").className).toContain("ink");
  });
});
