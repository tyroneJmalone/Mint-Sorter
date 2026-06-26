# Mint PDF Sorter — App Context for Integration Planning

This document describes the Mint PDF Sorter app built for Mint Printworks so another agent can understand it well enough to plan a combined Printavo dashboard.

---

## What This App Does

Mint Printworks fulfills apparel orders managed in Printavo. When an order batch is ready to ship, staff export two PDFs from Printavo (or a connected vendor platform):

1. **Packing slips PDF** — one page per order, contains customer name, order number, style, color, size, and shipping address
2. **Shipping labels PDF(s)** — one label per order, contains recipient name, shipping address, and USPS tracking number

These two PDFs come out of Printavo/vendor in arbitrary order. Before physical packing, staff need them sorted to match (so slip #1 pairs with label #1 in the same stack). This app automates that sorting and matching.

---

## Processing Presets

The user selects one of five presets on the UI:

| Preset | Input | Output |
|---|---|---|
| `combine_labels` | Label PDF(s) | Single merged labels PDF |
| `sort_slips` | Packing slips PDF | Slips sorted by Style → Color → Size → Order # |
| `sort_labels` | Slips + Labels | Sorted slips PDF + labels reordered to match sorted slips |
| `sort_both` | Slips + Labels | Same as `sort_labels` + a match report CSV |
| `match_labels` | Slips + Labels | Labels reordered to match slips in **their existing order** (no slip sorting) |

**Size sort order**: XS → S → M → L → XL → 2XL → 3XL → 4XL → 5XL → 6XL → YXS → YS → YM → YL → YXL → OSFA → OSFM

---

## Data Extracted from PDFs

Each packing slip page yields:
- `order_number` — Printavo order number (e.g. `7863434`)
- `customer_name` / `shipping_name` — customer name (format: "Last, First" e.g. "Su, Xizhen")
- `style` — garment style code (e.g. `18200`, `B5000`)
- `color` — garment color string
- `size` — size abbreviation (XS, S, M, L, XL, 2XL …)

Each shipping label page yields:
- `name` — recipient name in ALL CAPS FIRST LAST format (e.g. "XIZHEN SU")
- `address` — street + city + state + zip
- `tracking` — USPS tracking number

**Name matching** between slips and labels handles the Last,First ↔ FIRST LAST format mismatch using token-set intersection (order-independent).

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React + Vite, Tailwind CSS, shadcn/ui, framer-motion |
| API | Express 5 (Node.js 24, TypeScript) |
| PDF processing | Python 3 — pdfplumber (text extraction), pypdf (page writing), pandas (match report) |
| Monorepo | pnpm workspaces |
| API contract | OpenAPI 3.1 → Orval codegen (React Query hooks + Zod schemas) |

The Python processor runs as a **child process** (`python3 processor_cli.py`) spawned by Express. This preserves pdfplumber's layout-aware column extraction which is critical for reading Printavo packing slip layouts correctly.

---

## API Surface

Base path: `/api`

### `POST /api/process`
Multipart form upload. Fields:
- `preset` (string, required) — one of the five preset values above
- `packing_slips` (PDF file) — required for all presets except `combine_labels`
- `labels` (PDF file, repeatable) — required for all presets except `sort_slips`

Returns:
```json
{
  "jobId": "abc123",
  "outputs": [
    { "key": "sorted_packing_slips", "filename": "sorted_packing_slips.pdf", "label": "Sorted Packing Slips", "mime": "application/pdf" },
    { "key": "sorted_shipping_labels", "filename": "sorted_shipping_labels.pdf", "label": "Sorted Shipping Labels", "mime": "application/pdf" },
    { "key": "match_report", "filename": "match_report.csv", "label": "Match Report", "mime": "text/csv" },
    { "key": "mint_pdf_sorter_outputs", "filename": "mint_pdf_sorter_outputs.zip", "label": "All Files (ZIP)", "mime": "application/zip" }
  ]
}
```

### `GET /api/jobs/:jobId/files/:key`
Downloads a processed output file by key.

---

## Match Report CSV Schema

Produced by `sort_both` and `match_labels` presets. One row per packing slip in sequence order, plus any unmatched labels appended at the bottom.

| Column | Description |
|---|---|
| `sequence` | Position in the output stack (1-based) |
| `status` | `matched`, `missing_label`, or `unused_label` |
| `method` | How the match was made: `exact name` or `token name` |
| `order_number` | Printavo order number from the packing slip |
| `style` | Garment style code |
| `color` | Garment color |
| `size` | Garment size |
| `slip_name` | Customer name from the packing slip |
| `label_name` | Recipient name from the matched shipping label |
| `tracking` | USPS tracking number |
| `slip_page` | Source page number in the packing slips PDF |
| `label_source_file` | Source label PDF filename |
| `label_source_page` | Source page in the label PDF |

---

## Job Storage

Jobs are stored **in memory** (Node.js `Map`) with temp files written to `/tmp/mint-jobs/<jobId>/`. This is intentionally stateless — jobs are lost on server restart. There is no database. The app is designed for single-session, synchronous use: upload → process → download → done.

---

## Relationship to Printavo

- Packing slips are exported directly from Printavo (the layout is Printavo's standard packing slip template)
- Shipping labels are generated by a connected vendor shipping platform (USPS via a Printavo-connected app) and exported as a separate PDF
- The `order_number` field on each slip is the **Printavo order number** — this is the natural join key between this app's output and any Printavo API data
- This app does not currently call the Printavo API; it is purely PDF-in / PDF-out

---

## Integration Opportunities for a Combined Dashboard

Since `order_number` (Printavo order #) is extracted from every packing slip, the match report CSV is a natural bridge to Printavo data. Potential integrations:

1. **Enrich match report with Printavo order details** — use order numbers from the CSV to pull customer contact info, line items, due dates, or invoice status from the Printavo API
2. **Trigger this processor from within a dashboard** — the `/api/process` endpoint accepts a standard multipart POST and can be called from any app; the dashboard could expose the same PDF sorter UI inline
3. **Feed tracking numbers upstream** — the `tracking` column from the match report could be written back to Printavo orders or to a shipping platform to update fulfillment status
4. **Batch shipment summary** — aggregate size/color/style columns from the match report to generate a shipment manifest for the current batch

---

## Where the Code Lives (Replit Monorepo)

```
artifacts/api-server/
  src/routes/process.ts       — Express upload/download routes
  python/processor.py         — All PDF parsing and sorting logic
  python/processor_cli.py     — CLI wrapper called by Express subprocess

artifacts/mint-pdf-sorter/
  src/pages/Home.tsx          — Main UI (preset selector, file dropzones, download buttons)
  src/components/FileDropzone.tsx

lib/api-spec/openapi.yaml     — API contract (source of truth)
lib/api-client-react/         — Generated React Query hooks
lib/api-zod/                  — Generated Zod validation schemas
```
