import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { ArrowUp, ArrowDown, X, Save, FolderOpen, Trash2, Plus } from "lucide-react";

const ALL_FIELDS: { id: string; label: string }[] = [
  { id: "first_name", label: "First Name" },
  { id: "last_name", label: "Last Name" },
  { id: "style", label: "Style" },
  { id: "size", label: "Size" },
  { id: "color", label: "Color" },
  { id: "custom_field", label: "Custom Field" },
  { id: "delivery_method", label: "Delivery Method" },
  { id: "location", label: "Location" },
  { id: "sort_number", label: "Sort #" },
  { id: "order_number", label: "Order Number" },
  { id: "order_date", label: "Order Date" },
];

const FIELD_LABEL: Record<string, string> = Object.fromEntries(ALL_FIELDS.map((f) => [f.id, f.label]));

const STORAGE_KEY = "mintSortPresets";

interface SavedSortPreset {
  id: string;
  name: string;
  fields: string[];
}

function loadPresets(): SavedSortPreset[] {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "[]");
  } catch {
    return [];
  }
}

function persistPresets(presets: SavedSortPreset[]): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(presets));
}

interface CustomSortBuilderProps {
  value: string[];
  onChange: (fields: string[]) => void;
}

export function CustomSortBuilder({ value, onChange }: CustomSortBuilderProps) {
  const [savedPresets, setSavedPresets] = useState<SavedSortPreset[]>(loadPresets);
  const [presetName, setPresetName] = useState("");
  const [fieldToAdd, setFieldToAdd] = useState("");

  const availableFields = ALL_FIELDS.filter((f) => !value.includes(f.id));

  const addField = () => {
    if (fieldToAdd && !value.includes(fieldToAdd)) {
      onChange([...value, fieldToAdd]);
      setFieldToAdd("");
    }
  };

  const removeField = (idx: number) => onChange(value.filter((_, i) => i !== idx));

  const moveUp = (idx: number) => {
    if (idx === 0) return;
    const next = [...value];
    [next[idx - 1], next[idx]] = [next[idx], next[idx - 1]];
    onChange(next);
  };

  const moveDown = (idx: number) => {
    if (idx === value.length - 1) return;
    const next = [...value];
    [next[idx], next[idx + 1]] = [next[idx + 1], next[idx]];
    onChange(next);
  };

  const savePreset = () => {
    if (!presetName.trim() || value.length === 0) return;
    const preset: SavedSortPreset = {
      id: crypto.randomUUID(),
      name: presetName.trim(),
      fields: [...value],
    };
    const updated = [...savedPresets, preset];
    setSavedPresets(updated);
    persistPresets(updated);
    setPresetName("");
  };

  const loadPreset = (preset: SavedSortPreset) => onChange([...preset.fields]);

  const deletePreset = (id: string) => {
    const updated = savedPresets.filter((p) => p.id !== id);
    setSavedPresets(updated);
    persistPresets(updated);
  };

  return (
    <div className="space-y-4 rounded-lg border border-border bg-muted/30 p-4">
      <div>
        <Label className="text-sm font-medium">Sort Order</Label>
        <p className="text-xs text-muted-foreground mt-0.5 mb-2">
          Fields apply left-to-right: primary → secondary → …
        </p>

        {value.length === 0 ? (
          <p className="text-sm text-muted-foreground italic py-2 px-1">
            No fields added yet — add at least one below.
          </p>
        ) : (
          <div className="space-y-1 mb-3">
            {value.map((fieldId, idx) => (
              <div
                key={fieldId}
                className="flex items-center gap-2 px-3 py-2 bg-background rounded-md border border-border"
              >
                <span className="text-xs text-muted-foreground w-5 text-right shrink-0">{idx + 1}.</span>
                <span className="flex-1 text-sm font-medium">{FIELD_LABEL[fieldId] ?? fieldId}</span>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6 shrink-0"
                  onClick={() => moveUp(idx)}
                  disabled={idx === 0}
                  title="Move up"
                >
                  <ArrowUp className="h-3 w-3" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6 shrink-0"
                  onClick={() => moveDown(idx)}
                  disabled={idx === value.length - 1}
                  title="Move down"
                >
                  <ArrowDown className="h-3 w-3" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6 shrink-0 text-destructive hover:text-destructive"
                  onClick={() => removeField(idx)}
                  title="Remove"
                >
                  <X className="h-3 w-3" />
                </Button>
              </div>
            ))}
          </div>
        )}

        {availableFields.length > 0 && (
          <div className="flex gap-2">
            <Select value={fieldToAdd} onValueChange={setFieldToAdd}>
              <SelectTrigger className="flex-1 bg-input h-9 text-sm">
                <SelectValue placeholder="Add a sort field…" />
              </SelectTrigger>
              <SelectContent>
                {availableFields.map((f) => (
                  <SelectItem key={f.id} value={f.id}>
                    {f.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button variant="outline" size="sm" className="h-9 px-3" onClick={addField} disabled={!fieldToAdd}>
              <Plus className="h-3.5 w-3.5 mr-1" />
              Add
            </Button>
          </div>
        )}
      </div>

      <Separator />

      <div className="space-y-3">
        <Label className="text-sm font-medium">Saved Presets</Label>

        {savedPresets.length > 0 && (
          <div className="space-y-1">
            {savedPresets.map((preset) => (
              <div
                key={preset.id}
                className="flex items-center gap-2 px-3 py-2 rounded-md border border-border bg-background"
              >
                <div className="flex-1 min-w-0">
                  <span className="text-sm font-medium block">{preset.name}</span>
                  <span className="text-xs text-muted-foreground truncate block">
                    {preset.fields.map((f) => FIELD_LABEL[f] ?? f).join(" → ")}
                  </span>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 px-2 shrink-0"
                  onClick={() => loadPreset(preset)}
                >
                  <FolderOpen className="h-3.5 w-3.5 mr-1" />
                  Load
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 px-2 shrink-0 text-destructive hover:text-destructive"
                  onClick={() => deletePreset(preset.id)}
                  title="Delete preset"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
            ))}
          </div>
        )}

        <div className="flex gap-2">
          <Input
            value={presetName}
            onChange={(e) => setPresetName(e.target.value)}
            placeholder="Name this preset…"
            className="flex-1 bg-input h-9 text-sm"
            onKeyDown={(e) => e.key === "Enter" && savePreset()}
          />
          <Button
            variant="outline"
            size="sm"
            className="h-9 px-3 shrink-0"
            onClick={savePreset}
            disabled={!presetName.trim() || value.length === 0}
          >
            <Save className="h-3.5 w-3.5 mr-1" />
            Save
          </Button>
        </div>
      </div>
    </div>
  );
}
