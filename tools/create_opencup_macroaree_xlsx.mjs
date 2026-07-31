import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outputDir = "/Users/emilianotrombetta/Desktop/espansione del dominio/opencup Regionale";
const summaryPath = path.join(outputDir, "opencup_macroaree_summary.json");
const outputPath = path.join(outputDir, "conteggio progetti opencup per macroarea.xlsx");

const summary = JSON.parse(await fs.readFile(summaryPath, "utf8"));
const workbook = Workbook.create();
const sheet = workbook.worksheets.add("Macroaree");
sheet.showGridLines = false;

sheet.getRange("A1:D1").merge();
sheet.getRange("A1").values = [["OpenCUP - riepilogo progetti per macroarea"]];
sheet.getRange("A1").format.font = { bold: true, size: 16, color: "#1F2937" };
sheet.getRange("A1").format.fill = { color: "#E8EEF7" };
sheet.getRange("A1").format.rowHeight = 30;

const rows = [
  ["MACROAREA", "CODICI_REGIONE", "CUP_DISTINTI_LOCALIZZATI", "RIGHE_PROGETTO_SCRITTE"],
  ...Object.entries(summary.macroareas).map(([name, item]) => [
    name,
    item.region_codes.join(", "),
    Number(item.distinct_cups),
    Number(item.rows_written),
  ]),
];
sheet.getRange(`A3:D${2 + rows.length}`).values = rows;

const header = sheet.getRange("A3:D3");
header.format.font = { bold: true, color: "#111827" };
header.format.fill = { color: "#D9EAF7" };
header.format.borders = { preset: "outside", style: "thin", color: "#93C5FD" };
sheet.getRange(`A4:D${2 + rows.length}`).format.borders = {
  insideHorizontal: { style: "thin", color: "#E5E7EB" },
  bottom: { style: "thin", color: "#CBD5E1" },
};
sheet.getRange(`C4:D${2 + rows.length}`).format.numberFormat = "#,##0";
sheet.getRange("A:A").format.columnWidth = 18;
sheet.getRange("B:B").format.columnWidth = 32;
sheet.getRange("C:C").format.columnWidth = 28;
sheet.getRange("D:D").format.columnWidth = 28;
sheet.freezePanes.freezeRows(3);

sheet.getRange("A7:D8").merge(true);
sheet.getRange("A7").values = [
  [
    "Centro: Toscana, Umbria, Marche, Lazio. Sud e Isole: Abruzzo, Molise, Campania, Puglia, Basilicata, Calabria, Sicilia, Sardegna.",
  ],
  [
    "Nota: i CSV contengono le righe progetto trovate nei file OpenCup_Progetti*.csv. La colonna CUP_DISTINTI_LOCALIZZATI deriva da OpenCup_Localizzazione.csv.",
  ],
];
sheet.getRange("A7:D8").format.wrapText = true;
sheet.getRange("A7:D8").format.font = { italic: true, color: "#4B5563" };
sheet.getRange("A7:D8").format.rowHeight = 45;

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 50 },
  summary: "final formula error scan",
});
console.log(errors.ndjson);

const preview = await workbook.render({
  sheetName: "Macroaree",
  range: "A1:D8",
  scale: 1,
  format: "png",
});
await fs.writeFile(
  path.join(outputDir, "conteggio progetti opencup per macroarea.preview.png"),
  new Uint8Array(await preview.arrayBuffer()),
);

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(outputPath);
