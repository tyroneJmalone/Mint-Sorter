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
  mint_pdf_sorter_outputs: "Download all birth year batches (ZIP)",
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
];

router.post(
  "/process",
  upload.fields([
    { name: "packing_slips", maxCount: 1 },
    { name: "labels", maxCount: 20 },
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

    const files = req.files as Record<string, Express.Multer.File[]> | undefined;
    const packingFiles = files?.["packing_slips"] ?? [];
    const labelFiles = files?.["labels"] ?? [];

    if (PACKING_SLIP_PRESETS.includes(preset) && packingFiles.length === 0) {
      res.status(400).json({ error: "Packing slips PDF is required for this preset" });
      return;
    }
    if (["combine_labels", "sort_labels", "sort_both", "match_labels"].includes(preset) && labelFiles.length === 0) {
      res.status(400).json({ error: "At least one shipping label PDF is required for this preset" });
      return;
    }

    const jobId = randomUUID();
    const outDir = `/tmp/mint-jobs/${jobId}`;
    fs.mkdirSync(outDir, { recursive: true });

    // Build CLI args: preset, packing_slips_path (or ""), label_paths..., outDir
    const packingPath = packingFiles[0]?.path ?? "";
    const labelPaths = labelFiles.map((f) => f.path);

    const args = [
      processorScript,
      preset,
      packingPath,
      outDir,
      ...(sortFields.length > 0 ? ["--sort-fields", JSON.stringify(sortFields)] : []),
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
    [...packingFiles, ...labelFiles].forEach((f) => {
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
