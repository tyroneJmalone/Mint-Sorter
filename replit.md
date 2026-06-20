# Mint PDF Sorter

A production PDF processing tool for Mint Printworks. Upload packing slips and shipping label PDFs, choose a preset, and download sorted/combined output files.

## Run & Operate

- `pnpm --filter @workspace/api-server run dev` — run the API server (port 8080)
- `pnpm --filter @workspace/mint-pdf-sorter run dev` — run the React frontend (port 20707)
- `pnpm run typecheck` — full typecheck across all packages
- `pnpm run build` — typecheck + build all packages
- `pnpm --filter @workspace/api-spec run codegen` — regenerate API hooks and Zod schemas from the OpenAPI spec

## Stack

- pnpm workspaces, Node.js 24, TypeScript 5.9
- Frontend: React + Vite (wouter routing, Tailwind CSS, shadcn/ui, framer-motion)
- API: Express 5 with multer for multipart file uploads
- PDF processing: Python 3 (pdfplumber, pypdf, pandas) — called as a subprocess
- API codegen: Orval (from OpenAPI spec)

## Where things live

- `lib/api-spec/openapi.yaml` — API contract (source of truth)
- `lib/api-client-react/src/generated/` — generated React Query hooks
- `lib/api-zod/src/generated/` — generated Zod schemas
- `artifacts/mint-pdf-sorter/src/` — React frontend
- `artifacts/api-server/src/routes/process.ts` — upload/download route handlers
- `artifacts/api-server/python/processor.py` — PDF processing logic (original Streamlit app logic)
- `artifacts/api-server/python/processor_cli.py` — CLI wrapper called by Express

## Architecture decisions

- Python processor runs as a child process (`python3 processor_cli.py`) — preserves pdfplumber's layout-aware PDF text extraction which is hard to replicate in Node.js
- Job results stored in memory (Map) with temp files in `/tmp/mint-jobs/<jobId>/` — no database needed since this is a stateless processing tool
- File uploads handled by multer; the generated `useProcessFiles` hook is bypassed in the frontend (uses raw fetch/FormData) since generated hooks don't support multipart
- Frontend uses raw `fetch` for the upload and constructs download URLs manually using `BASE_URL + "api/jobs/:jobId/files/:key"`

## Product

- **Presets:**
  - Combine labels only — merges multiple shipping label PDFs into one
  - Sort packing slips — sorts by Style → Color → Size → Order #
  - Sort labels to match packing slips — matches labels to the sorted slip sequence
  - Sort both — does all of the above and exports a match report CSV
- After processing, users get per-file download buttons plus a single ZIP download

## User preferences

_Populate as you build — explicit user instructions worth remembering across sessions._

## Gotchas

- Python packages (pdfplumber, pypdf, pandas) must be installed in the Replit environment: `pip install pdfplumber pypdf pandas`
- The `File`/`Blob` TS types are not available in the Node.js api-zod package, so binary format fields must not be used in the OpenAPI spec for multipart bodies — multer handles those server-side
- Job files live in `/tmp/mint-jobs/` — they are ephemeral and lost on server restart

## Pointers

- See the `pnpm-workspace` skill for workspace structure, TypeScript setup, and package details
