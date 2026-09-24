import { Router, type IRouter } from "express";
import multer from "multer";
import { spawn } from "child_process";
import path from "path";
import fs from "fs";
import { randomUUID } from "crypto";
import { logger } from "../lib/logger";

const router: IRouter = Router();

const upload = multer({ dest: "/tmp/mint-uploads/" });

// In-memory job store (jobId → { key → filepath })
const jobs = new Map<string, Map<string, { filepath: string; filename: string; mime: string; label: string }>>();

// Resolve workspace root regardless of cwd
const workspaceRoot = process.cwd().endsWith(path.join("artifacts", "api-server"))
  ? path.resolve(process.cwd(), "../..")
  : process.cwd();

const processorScript = path.resolve(workspaceRoot, "artifacts/api-server/python/processor_cli.py");
const spreadsheetInspectScript = path.resolve(workspaceRoot, "artifacts/api-server/python/spreadsheet_inspect_cli.py");

function mimeForExt(ext: string): string {
  if (ext === ".zip") return "application/zip";
  if (ext === ".csv") return "text/csv";
  return "application/pdf";
}

const OUTPUT_LABELS: Record<string, string> = {
  combined_labels: "Download combined labels PDF",
  sorted_packing_slips: "Download sorted packing slips PDF",
  sorted_shipping_labels: "Download sorted shipping labels PDF",
  match_report: "Download match report CSV",
  custom_field_report: "Download custom field report CSV",
  custom_sort_report: "Download sort report CSV",
  required_field_report: "Download required field report CSV",
  birth_year_batch_manifest: "Download birth year batch manifest CSV",
  spreadsheet_sequence_packing_slips: "Download spreadsheet-sequenced packing slips PDF",
  spreadsheet_sequence_shipping_labels: "Download spreadsheet-sequenced shipping labels PDF",
  spreadsheet_sequence_match_report: "Download spreadsheet match report CSV",
  spreadsheet_sequence_label_report: "Download shipping label match report CSV",
  parsed_store_export: "Download parsed store export CSV",
  mint_pdf_sorter_outputs: "Download all outputs (ZIP)",
};

const VALID_PRESETS = [
  "combine_labels",
  "sort_slips",
  "sort_slips_name",
  "sort_slips_custom",
  "sort_slips_custom_first",
  "sort_labels",
  "sort_both",
  "match_labels",
  "custom_sort",
  "required_field",
  "split_required_field",
  "spreadsheet_sequence",
  "parse_store_export",
] as const;

const PACKING_SLIP_PRESETS = [
  "sort_slips",
  "sort_slips_name",
  "sort_slips_custom",
  "sort_slips_custom_first",
  "sort_labels",
  "sort_both",
  "match_labels",
  "custom_sort",
  "required_field",
  "split_required_field",
  "spreadsheet_sequence",
];

router.post("/spreadsheet/inspect", upload.single("spreadsheet"), async (req, res): Promise<void> => {
  const spreadsheet = req.file;
  if (!spreadsheet) {
    res.status(400).json({ error: "Spreadsheet file is required" });
    return;
  }
  try {
    const stdout = await new Promise<string>((resolve, reject) => {
      const proc = spawn("python3", [
        spreadsheetInspectScript,
        spreadsheet.path,
        spreadsheet.originalname,
      ]);
      let output = "";
      let stderr = "";
      proc.stdout.on("data", (data) => { output += data.toString(); });
      proc.stderr.on("data", (data) => { stderr += data.toString(); });
      proc.on("close", (code) => {
        if (code === 0) resolve(output);
        else reject(new Error(stderr || `Python exited with code ${code}`));
      });
      proc.on("error", reject);
    });
    res.json(JSON.parse(stdout));
  } catch (err) {
    req.log.error({ err }, "Spreadsheet inspection failed");
    res.status(400).json({ error: `Could not read spreadsheet: ${(err as Error).message}` });
  } finally {
    try { fs.unlinkSync(spreadsheet.path); } catch { /* ignore */ }
  }
});

router.post(
  "/process",
  upload.fields([
    { name: "packing_slips", maxCount: 1 },
    { name: "labels", maxCount: 20 },
    { name: "spreadsheet", maxCount: 1 },
    { name: "store_export", maxCount: 1 },
  ]),
  async (req, res): Promise<void> => {
    const preset = req.body?.preset as string | undefined;
    if (!preset || !VALID_PRESETS.includes(preset as (typeof VALID_PRESETS)[number])) {
      res.status(400).json({ error: "Invalid or missing preset" });
      return;
    }

    const sortFieldsRaw = req.body?.sort_fields as string | undefined;
    let sortFields: string[] = [];
    if (sortFieldsRaw) {
      try {
        sortFields = JSON.parse(sortFieldsRaw);
      } catch {
        res.status(400).json({ error: "sort_fields must be a valid JSON array" });
        return;
      }
    }
    if (preset === "custom_sort" && sortFields.length === 0) {
      res.status(400).json({ error: "custom_sort preset requires at least one sort field" });
      return;
    }
    const spreadsheetMappingRaw = req.body?.spreadsheet_mapping as string | undefined;
    let spreadsheetMapping: Record<string, unknown> | undefined;
    if (spreadsheetMappingRaw) {
      try {
        spreadsheetMapping = JSON.parse(spreadsheetMappingRaw);
      } catch {
        res.status(400).json({ error: "spreadsheet_mapping must be valid JSON" });
        return;
      }
    }

    const files = req.files as Record<string, Express.Multer.File[]> | undefined;
    const packingFiles = files?.["packing_slips"] ?? [];
    const labelFiles = files?.["labels"] ?? [];
    const spreadsheetFiles = files?.["spreadsheet"] ?? [];
    const storeExportFiles = files?.["store_export"] ?? [];

    if (PACKING_SLIP_PRESETS.includes(preset) && packingFiles.length === 0) {
      res.status(400).json({ error: "Packing slips PDF is required for this preset" });
      return;
    }
    if (["combine_labels", "sort_labels", "sort_both", "match_labels"].includes(preset) && labelFiles.length === 0) {
      res.status(400).json({ error: "At least one shipping label PDF is required for this preset" });
      return;
    }
    if (preset === "spreadsheet_sequence" && labelFiles.length === 0) {
      res.status(400).json({ error: "Shipping labels are required for spreadsheet sequencing" });
      return;
    }
    if (preset === "spreadsheet_sequence" && (spreadsheetFiles.length === 0 || !spreadsheetMapping)) {
      res.status(400).json({ error: "Spreadsheet and column mapping are required" });
      return;
    }
    if (
      preset === "spreadsheet_sequence"
      && (
        typeof spreadsheetMapping?.order_number_column !== "string"
        || !spreadsheetMapping.order_number_column.trim()
      )
    ) {
      res.status(400).json({ error: "Spreadsheet order-number column mapping is required" });
      return;
    }
    let removeColumnIndexes: number[] = [];
    if (preset === "parse_store_export") {
      const rawIndexes = req.body?.remove_column_indexes as string | undefined;
      if (rawIndexes) {
        try {
          const parsed = JSON.parse(rawIndexes) as unknown;
          if (
            !Array.isArray(parsed)
            || parsed.some((index) => !Number.isInteger(index) || index < 0)
          ) {
            throw new Error("Expected a JSON array of non-negative column indexes");
          }
          removeColumnIndexes = Array.from(new Set(parsed as number[]));
        } catch (err) {
          res.status(400).json({ error: `Invalid remove_column_indexes: ${(err as Error).message}` });
          return;
        }
      }
      if (storeExportFiles.length === 0) {
        res.status(400).json({ error: "Store export CSV is required for this preset" });
        return;
      }
      if (!storeExportFiles[0].originalname.toLowerCase().endsWith(".csv")) {
        res.status(400).json({ error: "Store export must be a CSV file" });
        return;
      }
    }

    const jobId = randomUUID();
    const outDir = `/tmp/mint-jobs/${jobId}`;
    fs.mkdirSync(outDir, { recursive: true });

    // Build CLI args: preset, packing_slips_path (or ""), label_paths..., outDir
    const packingPath = packingFiles[0]?.path ?? "";
    const labelPaths = labelFiles.map((f) => f.path);
    const spreadsheetFile = spreadsheetFiles[0];
    const storeExportFile = storeExportFiles[0];

    const args = [
      processorScript,
      preset,
      packingPath,
      outDir,
      ...(sortFields.length > 0 ? ["--sort-fields", JSON.stringify(sortFields)] : []),
      ...(spreadsheetFile
        ? [
            "--spreadsheet-path",
            spreadsheetFile.path,
            "--spreadsheet-name",
            spreadsheetFile.originalname,
            "--spreadsheet-mapping",
            JSON.stringify(spreadsheetMapping),
          ]
        : []),
      ...(storeExportFile
        ? [
            "--store-export-path",
            storeExportFile.path,
            "--remove-column-indexes",
            JSON.stringify(removeColumnIndexes),
          ]
        : []),
      ...labelPaths,
    ];

    req.log.info({ preset, labelCount: labelPaths.length }, "Starting PDF processing");

    try {
      await new Promise<void>((resolve, reject) => {
        const proc = spawn("python3", args);
        let stderr = "";
        proc.stderr.on("data", (d) => { stderr += d.toString(); });
        proc.on("close", (code) => {
          if (code === 0) {
            resolve();
          } else {
            reject(new Error(`Python exited with code ${code}: ${stderr}`));
          }
        });
        proc.on("error", reject);
      });
    } catch (err) {
      req.log.error({ err }, "Python processing failed");
      res.status(500).json({ error: `Processing failed: ${(err as Error).message}` });
      return;
    }

    // Read output files from outDir
    const outputFiles = fs.readdirSync(outDir);
    const jobFiles = new Map<string, { filepath: string; filename: string; mime: string; label: string }>();

    for (const filename of outputFiles) {
      const ext = path.extname(filename);
      const key = path.basename(filename, ext);
      const mime = mimeForExt(ext);
      const birthYear = key.match(/^packing_slips_birth_year_(\d{4}|unknown)$/)?.[1];
      const label = birthYear
        ? `Download ${birthYear === "unknown" ? "unknown birth year" : `birth year ${birthYear}`} batch PDF`
        : key === "mint_pdf_sorter_outputs" && preset === "split_required_field"
          ? "Download all birth year batches (ZIP)"
          : OUTPUT_LABELS[key] ?? `Download ${filename}`;
      jobFiles.set(key, {
        filepath: path.join(outDir, filename),
        filename,
        mime,
        label,
      });
    }

    jobs.set(jobId, jobFiles);

    // Clean up uploads
    [...packingFiles, ...labelFiles, ...spreadsheetFiles, ...storeExportFiles].forEach((f) => {
      try { fs.unlinkSync(f.path); } catch { /* ignore */ }
    });

    const outputs = Array.from(jobFiles.entries()).map(([key, info]) => ({
      key,
      filename: info.filename,
      label: info.label,
      mime: info.mime,
    }));

    // Put the all-outputs ZIP last.
    outputs.sort((a, b) =>
      a.key === "mint_pdf_sorter_outputs"
        ? 1
        : b.key === "mint_pdf_sorter_outputs"
          ? -1
          : 0
    );

    req.log.info({ jobId, outputCount: outputs.length }, "Processing complete");
    res.json({ jobId, outputs });
  }
);

router.get("/jobs/:jobId/files/:key", async (req, res): Promise<void> => {
  const jobId = Array.isArray(req.params.jobId) ? req.params.jobId[0] : req.params.jobId;
  const key = Array.isArray(req.params.key) ? req.params.key[0] : req.params.key;

  const jobFiles = jobs.get(jobId);
  if (!jobFiles) {
    res.status(404).json({ error: "Job not found" });
    return;
  }

  const fileInfo = jobFiles.get(key);
  if (!fileInfo || !fs.existsSync(fileInfo.filepath)) {
    res.status(404).json({ error: "File not found" });
    return;
  }

  res.setHeader("Content-Type", fileInfo.mime);
  res.setHeader("Content-Disposition", `attachment; filename="${fileInfo.filename}"`);
  res.sendFile(fileInfo.filepath);
});

export default router;
