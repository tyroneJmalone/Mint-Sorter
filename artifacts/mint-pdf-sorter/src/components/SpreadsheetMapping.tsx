import { useMemo, useState } from "react";
import { Loader2 } from "lucide-react";
import { FileDropzone } from "@/components/FileDropzone";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

export type SpreadsheetColumnMapping = {
  sheet_name: string;
  header_row: number;
  full_name_column: string;
  first_name_column: string;
  last_name_column: string;
  order_number_column: string;
};

type PreviewSheet = { name: string; rows: string[][] };
type PreviewResult = { sheets: PreviewSheet[] };

const NONE = "__none__";

function suggestedColumn(headers: string[], pattern: RegExp): string {
  return headers.find((header) => pattern.test(header.trim())) ?? "";
}

export function SpreadsheetMapping({
  files,
  onFilesChange,
  mapping,
  onMappingChange,
}: {
  files: File[];
  onFilesChange: (files: File[]) => void;
  mapping: SpreadsheetColumnMapping | null;
  onMappingChange: (mapping: SpreadsheetColumnMapping | null) => void;
}) {
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [isInspecting, setIsInspecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const inspectFile = async (file: File) => {
    onFilesChange([file]);
    onMappingChange(null);
    setPreview(null);
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
      if (!response.ok) throw new Error(result.error || "Could not read spreadsheet");
      const data = result as PreviewResult;
      const firstSheet = data.sheets[0];
      if (!firstSheet) throw new Error("The spreadsheet has no readable sheets");
      const headers = firstSheet.rows[0] ?? [];
      setPreview(data);
      onMappingChange({
        sheet_name: firstSheet.name,
        header_row: 1,
        full_name_column: suggestedColumn(headers, /^(full\s*)?name$/i),
        first_name_column: suggestedColumn(headers, /first.*name|name.*first/i),
        last_name_column: suggestedColumn(headers, /last.*name|name.*last/i),
        order_number_column: suggestedColumn(headers, /order.*(#|number|no)|(#|number|no).*order/i),
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not read spreadsheet");
    } finally {
      setIsInspecting(false);
    }
  };

  const activeSheet = preview?.sheets.find((sheet) => sheet.name === mapping?.sheet_name);
  const headers = useMemo(
    () => activeSheet?.rows[(mapping?.header_row ?? 1) - 1]?.map(String) ?? [],
    [activeSheet, mapping?.header_row],
  );

  const update = (changes: Partial<SpreadsheetColumnMapping>) => {
    if (mapping) onMappingChange({ ...mapping, ...changes });
  };

  const columnSelect = (
    id: string,
    label: string,
    value: string,
    onValueChange: (value: string) => void,
  ) => (
    <div className="space-y-2">
      <Label htmlFor={id}>{label}</Label>
      <Select value={value || NONE} onValueChange={(next) => onValueChange(next === NONE ? "" : next)}>
        <SelectTrigger id={id} className="bg-input">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={NONE}>Not mapped</SelectItem>
          {headers.filter(Boolean).map((header, index) => (
            <SelectItem key={`${header}-${index}`} value={header}>{header}</SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );

  return (
    <div className="space-y-4">
      <FileDropzone
        multiple={false}
        files={files}
        accept={{
          "text/csv": [".csv"],
          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"],
        }}
        onFilesAccepted={(accepted) => void inspectFile(accepted[0])}
        onFileRemoved={() => {
          onFilesChange([]);
          onMappingChange(null);
          setPreview(null);
          setError(null);
        }}
        label="CSV and Excel (.xlsx) files are supported"
      />

      {isInspecting && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Reading spreadsheet columns…
        </div>
      )}
      {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}

      {preview && mapping && (
        <div className="rounded-lg border border-border bg-muted/30 p-4 space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="spreadsheet-sheet">Sheet</Label>
              <Select
                value={mapping.sheet_name}
                onValueChange={(sheet_name) => update({ sheet_name, header_row: 1 })}
              >
                <SelectTrigger id="spreadsheet-sheet" className="bg-input"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {preview.sheets.map((sheet) => (
                    <SelectItem key={sheet.name} value={sheet.name}>{sheet.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="spreadsheet-header-row">Header row</Label>
              <input
                id="spreadsheet-header-row"
                type="number"
                min={1}
                max={Math.max(activeSheet?.rows.length ?? 1, 1)}
                value={mapping.header_row}
                onChange={(event) => update({ header_row: Math.max(1, Number(event.target.value) || 1) })}
                className="flex h-10 w-full rounded-md border border-input bg-input px-3 py-2 text-sm"
              />
            </div>
          </div>

          <div>
            <p className="text-sm font-medium">Column mapping</p>
            <p className="text-xs text-muted-foreground mt-1">
              Map a full-name column, or map both first and last name. Order number is optional but preferred.
            </p>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            {columnSelect("map-full-name", "Full name", mapping.full_name_column, (value) => update({ full_name_column: value }))}
            {columnSelect("map-order-number", "Order number (optional)", mapping.order_number_column, (value) => update({ order_number_column: value }))}
            {columnSelect("map-first-name", "First name", mapping.first_name_column, (value) => update({ first_name_column: value }))}
            {columnSelect("map-last-name", "Last name", mapping.last_name_column, (value) => update({ last_name_column: value }))}
          </div>

          <div className="rounded-md bg-background border border-border px-3 py-2 text-xs text-muted-foreground">
            Detected headers: {headers.filter(Boolean).join(" · ") || "Choose the correct header row"}
          </div>
        </div>
      )}
    </div>
  );
}