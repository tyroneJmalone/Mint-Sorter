import React, { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { FileDropzone } from "@/components/FileDropzone";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { useToast } from "@/hooks/use-toast";
import { Loader2, Download, AlertCircle, CheckCircle2 } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { ProcessInputPreset, OutputFile } from "@workspace/api-client-react";
import { CustomSortBuilder } from "@/components/CustomSortBuilder";
import { SpreadsheetMapping, type SpreadsheetColumnMapping } from "@/components/SpreadsheetMapping";
import { StoreExportParser } from "@/components/StoreExportParser";

async function triggerDownload(url: string, filename: string) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Download failed: ${response.statusText}`);
  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = objectUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(objectUrl);
}

export default function Home() {
  const { toast } = useToast();
  const [preset, setPreset] = useState<ProcessInputPreset>("combine_labels");
  const [sortFields, setSortFields] = useState<string[]>([]);
  const [packingSlips, setPackingSlips] = useState<File[]>([]);
  const [labels, setLabels] = useState<File[]>([]);
  const [spreadsheet, setSpreadsheet] = useState<File[]>([]);
  const [spreadsheetMapping, setSpreadsheetMapping] = useState<SpreadsheetColumnMapping | null>(null);
  const [storeExport, setStoreExport] = useState<File[]>([]);
  const [additionalDropIndexes, setAdditionalDropIndexes] = useState<number[]>([]);
  const [isProcessing, setIsProcessing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<{ jobId: string; outputs: OutputFile[] } | null>(null);

  const needsPackingSlips = ["sort_slips", "sort_slips_name", "sort_slips_custom", "sort_slips_custom_first", "sort_labels", "sort_both", "match_labels", "custom_sort", "required_field", "split_required_field"].includes(preset);
  const needsLabels = ["combine_labels", "sort_labels", "sort_both", "match_labels", "spreadsheet_sequence"].includes(preset);
  const needsSpreadsheet = preset === "spreadsheet_sequence";
  const needsStoreExport = preset === "parse_store_export";
  const needsPackingSlipsForPreset = needsPackingSlips || needsSpreadsheet;

  const handleProcess = async () => {
    if (needsPackingSlipsForPreset && packingSlips.length === 0) {
      setError("Packing slips are required for this preset.");
      return;
    }
    if (needsLabels && labels.length === 0) {
      setError("Shipping labels are required for this preset.");
      return;
    }
    if (preset === "custom_sort" && sortFields.length === 0) {
      setError("Add at least one sort field before processing.");
      return;
    }
    if (needsSpreadsheet) {
      if (spreadsheet.length === 0 || !spreadsheetMapping) {
        setError("Upload the sequence spreadsheet and map its order-number column.");
        return;
      }
      if (!spreadsheetMapping.order_number_column) {
        setError("Map the spreadsheet order-number column.");
        return;
      }
    }
    if (needsStoreExport && storeExport.length === 0) {
      setError("Upload a store export CSV.");
      return;
    }

    setError(null);
    setIsProcessing(true);
    setResults(null);

    try {
      const formData = new FormData();
      formData.append("preset", preset);

      if (preset === "custom_sort") {
        formData.append("sort_fields", JSON.stringify(sortFields));
      }
      if (needsSpreadsheet && spreadsheet[0] && spreadsheetMapping) {
        formData.append("spreadsheet", spreadsheet[0]);
        formData.append("spreadsheet_mapping", JSON.stringify(spreadsheetMapping));
      }
      if (needsStoreExport && storeExport[0]) {
        formData.append("store_export", storeExport[0]);
        formData.append("remove_column_indexes", JSON.stringify(additionalDropIndexes));
      }
      
      if (needsPackingSlipsForPreset && packingSlips[0]) {
        formData.append("packing_slips", packingSlips[0]);
      }
      
      if (needsLabels) {
        labels.forEach((f) => formData.append("labels", f));
      }

      const response = await fetch(`${import.meta.env.BASE_URL}api/process`, {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.error || "Processing failed");
      }

      const result = await response.json();
      setResults(result);
      toast({
        title: "Processing complete",
        description: "Your files are ready for download.",
      });
    } catch (err: any) {
      setError(err.message || "An unexpected error occurred during processing.");
      toast({
        variant: "destructive",
        title: "Processing failed",
        description: err.message || "An unexpected error occurred.",
      });
    } finally {
      setIsProcessing(false);
    }
  };

  const handleReset = () => {
    setPackingSlips([]);
    setLabels([]);
    setSpreadsheet([]);
    setSpreadsheetMapping(null);
    setStoreExport([]);
    setAdditionalDropIndexes([]);
    setResults(null);
    setError(null);
  };

  return (
    <div className="min-h-screen bg-background py-10 px-4 md:px-8 flex flex-col items-center">
      <div className="w-full max-w-4xl space-y-8">
        <div className="space-y-2 text-center">
          <h1 className="text-3xl font-bold tracking-tight text-foreground">
            <a
              href={import.meta.env.BASE_URL}
              title="Home — start a new session"
              aria-label="Mint Sorter & Parser — Home, start a new session"
              className="rounded-sm transition-colors hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-4"
            >
              Mint Sorter &amp; Parser
            </a>
          </h1>
          <p className="text-muted-foreground">
            Sort and match PDFs, or clean common store exports.
          </p>
        </div>

        <Card className="border-border shadow-sm">
          <CardHeader>
            <CardTitle>Process Configuration</CardTitle>
            <CardDescription>Select a preset and upload your files</CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="space-y-3">
              <Label htmlFor="preset-select">Operation Preset</Label>
              <Select
                value={preset}
                onValueChange={(val) => {
                  setPreset(val as ProcessInputPreset);
                  setError(null);
                }}
              >
                <SelectTrigger id="preset-select" className="w-full bg-input">
                  <SelectValue placeholder="Select preset" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="combine_labels">Combine labels only</SelectItem>
                  <SelectItem value="sort_slips">Sort packing slips (Style → Color → Size → Order #)</SelectItem>
                  <SelectItem value="sort_slips_name">Sort packing slips (Style → Color → Size → Last Name)</SelectItem>
                  <SelectItem value="sort_slips_custom">Sort packing slips (Style → Color → Size → Last Name → Custom Field)</SelectItem>
                  <SelectItem value="sort_slips_custom_first">Sort packing slips (Custom Field → Last Name)</SelectItem>
                  <SelectItem value="sort_labels">Sort labels to match sorted packing slips</SelectItem>
                  <SelectItem value="sort_both">Sort both packing slips and labels</SelectItem>
                  <SelectItem value="match_labels">Sort labels to existing packing slip order (no slip sorting)</SelectItem>
                  <SelectItem value="custom_sort">Custom Sort (Build Your Own)</SelectItem>
                  <SelectItem value="required_field">Sort packing slips (Required Field: Birth Year Oldest to Recent)</SelectItem>
                  <SelectItem value="split_required_field">Create batches by Required Field (Birth Year)</SelectItem>
                  <SelectItem value="spreadsheet_sequence">Sort slips & labels to spreadsheet sequence</SelectItem>
                  <SelectItem value="parse_store_export">Parse store export (remove columns)</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <AnimatePresence mode="popLayout">
              {preset === "custom_sort" && (
                <motion.div
                  key="custom-sort-builder"
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: "auto" }}
                  exit={{ opacity: 0, height: 0 }}
                  className="space-y-3"
                >
                  <Label>Sort Configuration</Label>
                  <CustomSortBuilder value={sortFields} onChange={setSortFields} />
                </motion.div>
              )}

              {needsPackingSlipsForPreset && (
                <motion.div
                  key="packing-slips"
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: "auto" }}
                  exit={{ opacity: 0, height: 0 }}
                  className="space-y-3"
                >
                  <Label>Packing Slips (Single PDF)</Label>
                  {preset === "split_required_field" && (
                    <p className="text-sm text-muted-foreground">
                      Creates one PDF per birth year without changing the order sequence.
                    </p>
                  )}
                  {preset !== "match_labels" && (
                    <p className="text-sm text-muted-foreground">
                      Totals-only continuation pages are automatically consolidated when the summary fits.
                      Product pages stay intact. A downloadable report explains which slips were consolidated or kept.
                    </p>
                  )}
                  <FileDropzone
                    multiple={false}
                    files={packingSlips}
                    onFilesAccepted={(files) => setPackingSlips([files[0]])}
                    onFileRemoved={() => setPackingSlips([])}
                    label="Only PDF files are supported"
                  />
                </motion.div>
              )}

              {needsSpreadsheet && (
                <motion.div
                  key="spreadsheet"
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: "auto" }}
                  exit={{ opacity: 0, height: 0 }}
                  className="space-y-3"
                >
                  <Label>Sequence Spreadsheet</Label>
                    <p className="text-sm text-muted-foreground">
                      Spreadsheet order numbers set the packing-slip sequence. Shipping labels are then matched to that reordered slip sequence.
                    </p>
                  <SpreadsheetMapping
                    files={spreadsheet}
                    onFilesChange={setSpreadsheet}
                    mapping={spreadsheetMapping}
                    onMappingChange={setSpreadsheetMapping}
                  />
                </motion.div>
              )}

              {needsStoreExport && (
                <motion.div
                  key="store-export"
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: "auto" }}
                  exit={{ opacity: 0, height: 0 }}
                  className="space-y-3"
                >
                  <Label>Store Export CSV</Label>
                  <StoreExportParser
                    files={storeExport}
                    onFilesChange={setStoreExport}
                    additionalDropIndexes={additionalDropIndexes}
                    onAdditionalDropIndexesChange={setAdditionalDropIndexes}
                  />
                </motion.div>
              )}

              {needsLabels && (
                <motion.div
                  key="labels"
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: "auto" }}
                  exit={{ opacity: 0, height: 0 }}
                  className="space-y-3"
                >
                  <Label>Shipping Labels (Multiple PDFs)</Label>
                  <FileDropzone
                    multiple={true}
                    files={labels}
                    onFilesAccepted={(files) => setLabels([...labels, ...files])}
                    onFileRemoved={(idx) => setLabels(labels.filter((_, i) => i !== idx))}
                    label="Multiple PDF files are supported"
                  />
                </motion.div>
              )}
            </AnimatePresence>

            <AnimatePresence>
              {error && (
                <motion.div
                  initial={{ opacity: 0, y: -10 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -10 }}
                >
                  <Alert variant="destructive">
                    <AlertCircle className="h-4 w-4" />
                    <AlertTitle>Error</AlertTitle>
                    <AlertDescription>{error}</AlertDescription>
                  </Alert>
                </motion.div>
              )}
            </AnimatePresence>

            <div className="pt-4 flex items-center justify-end space-x-4 border-t border-border">
              <Button
                variant="outline"
                onClick={handleReset}
                disabled={isProcessing || (packingSlips.length === 0 && labels.length === 0 && spreadsheet.length === 0 && storeExport.length === 0 && !results)}
              >
                Reset
              </Button>
              <Button
                onClick={handleProcess}
                disabled={isProcessing}
                className="w-40"
              >
                {isProcessing ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Processing...
                  </>
                ) : (
                  "Process Files"
                )}
              </Button>
            </div>
          </CardContent>
        </Card>

        <AnimatePresence>
          {results && (
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -20 }}
            >
              <Card className="border-primary/20 shadow-md overflow-hidden">
                <div className="bg-primary/10 px-6 py-4 flex items-center border-b border-primary/20">
                  <CheckCircle2 className="h-5 w-5 text-primary mr-3" />
                  <h3 className="font-semibold text-primary">Processing Successful</h3>
                </div>
                <CardContent className="p-6">
                  <div className="grid gap-4 sm:grid-cols-2">
                    {results.outputs.map((output) => {
                      const downloadUrl = `${import.meta.env.BASE_URL}api/jobs/${results.jobId}/files/${output.key}`;
                      return (
                        <div
                          key={output.key}
                          className="flex flex-col justify-between p-4 bg-muted rounded-lg border border-border"
                        >
                          <div className="mb-4">
                            <h4 className="font-medium text-foreground">{output.label}</h4>
                            <p className="text-sm text-muted-foreground truncate" title={output.filename}>
                              {output.filename}
                            </p>
                          </div>
                          <Button
                            variant="default"
                            className="w-full"
                            onClick={() =>
                              triggerDownload(downloadUrl, output.filename).catch((err) =>
                                toast({ variant: "destructive", title: "Download failed", description: err.message })
                              )
                            }
                          >
                            <Download className="mr-2 h-4 w-4" />
                            Download
                          </Button>
                        </div>
                      );
                    })}
                  </div>
                </CardContent>
              </Card>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
