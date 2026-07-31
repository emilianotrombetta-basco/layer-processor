import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outputDir = "/Users/emilianotrombetta/Desktop/espansione del dominio/opencup Regionale";
const summaryPath = path.join(outputDir, "opencup_regionale_summary.json");
const outputPath = path.join(outputDir, "conteggio progetti opencup per regione.xlsx");

const summary = JSON.parse(await fs.readFile(summaryPath, "utf8"));
const counts = summary.counts;

const workbook = Workbook.create();
const sheet = workbook.worksheets.add("Conteggio regioni");
sheet.showGridLines = false;

sheet.getRange("A1:C1").merge();
sheet.getRange("A1").values = [["Conteggio progetti OpenCUP per regione"]];
sheet.getRange("A1").format.font = { bold: true, size: 16, color: "#1F2937" };
sheet.getRange("A1").format.fill = { color: "#E8EEF7" };
sheet.getRange("A1").format.rowHeight = 30;

sheet.getRange("A3:B6").values = [
  ["Localizzazioni lette", summary.localization_rows_read],
  ["Progetti letti", summary.project_rows_read],
  ["Progetti Nord distinti", summary.nord_distinct_cups],
  ["Righe scritte in opencup Nord.csv", summary.nord_project_rows_written],
];
sheet.getRange("A3:A6").format.font = { bold: true, color: "#374151" };
sheet.getRange("B3:B6").format.numberFormat = "#,##0";
sheet.getRange("A3:B6").format.fill = { color: "#F9FAFB" };
sheet.getRange("A3:B6").format.borders = { preset: "outside", style: "thin", color: "#CBD5E1" };

const tableRows = [
  ["CODICE_REGIONE", "REGIONE", "PROGETTI_DISTINTI"],
  ...counts.map((row) => [
    row.codice_regione,
    row.regione,
    Number(row.progetti_distinti),
  ]),
];
sheet.getRange(`A9:C${8 + tableRows.length}`).values = tableRows;

const header = sheet.getRange("A9:C9");
header.format.font = { bold: true, color: "#111827" };
header.format.fill = { color: "#D9EAF7" };
header.format.borders = { preset: "outside", style: "thin", color: "#93C5FD" };

const dataRange = sheet.getRange(`A10:C${9 + counts.length}`);
dataRange.format.borders = {
  insideHorizontal: { style: "thin", color: "#E5E7EB" },
  bottom: { style: "thin", color: "#CBD5E1" },
};
sheet.getRange(`C10:C${9 + counts.length}`).format.numberFormat = "#,##0";
sheet.getRange("A:C").format.autofitColumns();
sheet.getRange("A:A").format.columnWidth = 18;
sheet.getRange("B:B").format.columnWidth = 30;
sheet.getRange("C:C").format.columnWidth = 22;
sheet.freezePanes.freezeRows(9);

const noteRow = 32;
sheet.getRange(`A${noteRow}:C${noteRow}`).merge();
sheet.getRange(`A${noteRow}`).values = [
  [
    "Nota: conteggio su CUP distinti per codice regione in OpenCup_Localizzazione.csv. Un progetto localizzato in piu regioni e contato in ciascuna regione.",
  ],
];
sheet.getRange(`A${noteRow}`).format.font = { italic: true, color: "#4B5563" };
sheet.getRange(`A${noteRow}`).format.wrapText = true;
sheet.getRange(`A${noteRow}`).format.rowHeight = 34;

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 50 },
  summary: "final formula error scan",
});
console.log(errors.ndjson);
const tableCheck = await workbook.inspect({
  kind: "table",
  range: "Conteggio regioni!A8:C11",
  include: "values",
  tableMaxRows: 6,
  tableMaxCols: 4,
});
console.log(tableCheck.ndjson);

const preview = await workbook.render({
  sheetName: "Conteggio regioni",
  range: "A1:C32",
  scale: 1,
  format: "png",
});
await fs.writeFile(
  path.join(outputDir, "conteggio progetti opencup per regione.preview.png"),
  new Uint8Array(await preview.arrayBuffer()),
);

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(outputPath);
