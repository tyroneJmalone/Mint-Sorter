import { useMemo, useState } from "react";
import { Check, Loader2, Search } from "lucide-react";
import { FileDropzone } from "@/components/FileDropzone";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Label } from "@/components/ui/label";

export const STORE_EXPORT_DEFAULT_DROP_COLUMNS = [
  "Dealer Name",
  "Organization County",
  "Catalog Sales Id",
  "Sales Id",
  "Status",
  "Ship Country",
  "Ship Country Code",
  "Product Status",
  "Event Product ID",
  "Sub Category",
  "Product Image URL",
  "Product UPC",
  "Tax Total",
  "Salesperson Id",
  "Salesperson External Id",
  "BatchID",
  "External Organization ID",
  "External Organization Branch ID",
  "Batch Standalone",
] as const;

const DEFAULT_DROP_SET = new Set<string>(STORE_EXPORT_DEFAULT_DROP_COLUMNS);

export function StoreExportParser({
  files,
  onFilesChange,
  additionalDropIndexes,
  onAdditionalDropIndexesChange,
}: {
  files: File[];
  onFilesChange: (files: File[]) => void;
  additionalDropIndexes: number[];
  onAdditionalDropIndexesChange: (indexes: number[]) => void;
}) {
  const [headers, setHeaders] = useState<string[]>([]);
  const [search, setSearch] = useState("");
  const [isInspecting, setIsInspecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const inspectFile = async (file: File) => {
    onFilesChange([file]);
    onAdditionalDropIndexesChange([]);
    setHeaders([]);
    setError(null);
    setIsInspecting(true);
    try {
      const formData = new FormData();
      formData.append("spreadsheet", file);
      const response = await fetch(`${import.meta.env.BASE_URL}api/spreadsheet/inspect`, {
        method: "POST",
        body: formData,
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Could not read CSV");
      const nextHeaders = (result.sheets?.[0]?.rows?.[0] ?? []).map(String);
      if (nextHeaders.length === 0) throw new Error("The CSV has no header row");
      setHeaders(nextHeaders);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not read CSV");
    } finally {
      setIsInspecting(false);
    }
  };

  const visibleHeaders = useMemo(() => {
    const term = search.trim().toLowerCase();
    return headers
      .map((header, index) => ({ header, index }))
      .filter(({ header }) => !DEFAULT_DROP_SET.has(header))
      .filter(({ header }) => !term || header.toLowerCase().includes(term));
  }, [headers, search]);

  const toggleColumn = (index: number) => {
    onAdditionalDropIndexesChange(
      additionalDropIndexes.includes(index)
        ? additionalDropIndexes.filter((value) => value !== index)
        : [...additionalDropIndexes, index].sort((a, b) => a - b),
    );
  };

  return (
    <div className="space-y-4">
      <FileDropzone
        multiple={false}
        files={files}
        accept={{ "text/csv": [".csv"] }}
        onFilesAccepted={(accepted) => void inspectFile(accepted[0])}
        onFileRemoved={() => {
          onFilesChange([]);
          onAdditionalDropIndexesChange([]);
          setHeaders([]);
          setSearch("");
          setError(null);
        }}
        label="Chipply store export CSV"
      />

      {isInspecting && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Reading CSV columns…
        </div>
      )}
      {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}

      {headers.length > 0 && (
        <div className="space-y-4 rounded-lg border border-border bg-muted/30 p-4">
          <div>
            <p className="text-sm font-medium">19 standard columns will be removed</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Select any additional columns you do not need for this job. All other columns and cell values stay in their original order and text format.
            </p>
          </div>

          <div className="flex flex-wrap gap-1.5">
            {STORE_EXPORT_DEFAULT_DROP_COLUMNS.map((column) => (
              <span key={column} className="rounded-full border border-border bg-background px-2 py-1 text-xs text-muted-foreground">
                {column}
              </span>
            ))}
          </div>

          <div className="space-y-2">
            <Label htmlFor="column-search">Additional columns to remove</Label>
            <div className="relative">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <input
                id="column-search"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search columns"
                className="flex h-10 w-full rounded-md border border-input bg-input pl-9 pr-3 py-2 text-sm"
              />
            </div>
          </div>

          <div className="grid max-h-72 gap-2 overflow-y-auto pr-1 sm:grid-cols-2">
            {visibleHeaders.map(({ header, index }) => {
              const selected = additionalDropIndexes.includes(index);
              return (
                <button
                  key={`${header}-${index}`}
                  type="button"
                  onClick={() => toggleColumn(index)}
                  aria-pressed={selected}
                  className={`flex min-h-10 items-center gap-3 rounded-md border px-3 py-2 text-left text-sm transition-colors ${
                    selected
                      ? "border-primary bg-primary/10 text-foreground"
                      : "border-border bg-background hover:border-primary/50"
                  }`}
                >
                  <span className={`flex h-4 w-4 shrink-0 items-center justify-center rounded border ${
                    selected ? "border-primary bg-primary text-primary-foreground" : "border-input"
                  }`}>
                    {selected && <Check className="h-3 w-3" />}
                  </span>
                  <span>{header || `Unnamed column ${index + 1}`}</span>
                </button>
              );
            })}
          </div>
          <p className="text-xs font-medium text-muted-foreground">
            {additionalDropIndexes.length} additional {additionalDropIndexes.length === 1 ? "column" : "columns"} selected
          </p>
        </div>
      )}
    </div>
  );
}