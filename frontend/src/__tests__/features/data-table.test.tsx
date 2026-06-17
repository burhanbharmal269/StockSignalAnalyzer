import { render, screen } from "@testing-library/react";
import { DataTable } from "@/components/shared/data-table";
import type { ColumnDef } from "@tanstack/react-table";

interface Row {
  name: string;
  value: number;
}

const columns: ColumnDef<Row>[] = [
  { accessorKey: "name", header: "Name" },
  { accessorKey: "value", header: "Value" },
];

describe("DataTable", () => {
  it("renders column headers", () => {
    render(<DataTable columns={columns} data={[]} />);
    expect(screen.getByText("Name")).toBeTruthy();
    expect(screen.getByText("Value")).toBeTruthy();
  });

  it("renders data rows", () => {
    const data: Row[] = [
      { name: "Alpha", value: 100 },
      { name: "Beta", value: 200 },
    ];
    render(<DataTable columns={columns} data={data} />);
    expect(screen.getByText("Alpha")).toBeTruthy();
    expect(screen.getByText("Beta")).toBeTruthy();
  });

  it("shows empty message when no data", () => {
    render(<DataTable columns={columns} data={[]} emptyMessage="Nothing here" />);
    expect(screen.getByText("Nothing here")).toBeTruthy();
  });

  it("uses default empty message", () => {
    render(<DataTable columns={columns} data={[]} />);
    expect(screen.getByText("No data")).toBeTruthy();
  });
});
