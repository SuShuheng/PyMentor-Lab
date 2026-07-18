import type { ReactNode } from "react";
import { useId } from "react";

export interface ChartFrameProps {
  children: ReactNode;
  columns: readonly string[];
  description: string;
  rows: readonly (readonly string[])[];
  title: string;
}

export function ChartFrame({
  children,
  columns,
  description,
  rows,
  title,
}: ChartFrameProps) {
  const titleId = useId();
  const descriptionId = useId();

  return (
    <figure
      aria-describedby={descriptionId}
      aria-labelledby={titleId}
      className="py-chart-frame"
    >
      <div className="py-chart-frame__heading">
        <h2 id={titleId}>{title}</h2>
        <p id={descriptionId}>{description}</p>
      </div>
      <div aria-hidden="true" className="py-chart-frame__visual">
        {children}
      </div>
      <table aria-label={`${title}数据`} className="py-chart-frame__table">
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column} scope="col">
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={`${row[0] ?? "row"}-${rowIndex}`}>
              {row.map((cell, cellIndex) =>
                cellIndex === 0 ? (
                  <th key={`${cell}-${cellIndex}`} scope="row">
                    {cell}
                  </th>
                ) : (
                  <td key={`${cell}-${cellIndex}`}>{cell}</td>
                ),
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
