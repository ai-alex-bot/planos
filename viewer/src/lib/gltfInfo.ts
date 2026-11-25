// Reads the extras written by the pipeline (three.js exposes them as `userData`).

export type AreaKind = "declarada" | "calculada";

export interface UnitInfo {
  displayAreaM2: number | null;
  displayAreaKind: AreaKind | null;
  floorToCeiling: number;
  openAreaM2: number | null;
  sourceFile: string | null;
}

export interface FloorInfo {
  roomId: string;
  name: string | null;
  slug: string;
  netAreaM2: number;
  isRoofed: boolean;
}

type Data = Record<string, unknown>;

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const str = (v: unknown): string | null => (typeof v === "string" && v.length > 0 ? v : null);

export const DEFAULT_FLOOR_TO_CEILING = 2.4;

export function readUnitInfo(userData: Data | undefined): UnitInfo {
  const d = userData ?? {};
  const kind = d.display_area_kind;
  return {
    displayAreaM2: num(d.display_area_m2),
    displayAreaKind: kind === "declarada" || kind === "calculada" ? kind : null,
    floorToCeiling: num(d.floor_to_ceiling) ?? DEFAULT_FLOOR_TO_CEILING,
    openAreaM2: num(d.open_area_m2),
    sourceFile: str(d.source_file),
  };
}

export function readFloorInfo(userData: Data | undefined): FloorInfo | null {
  const d = userData ?? {};
  if (d.type !== "floor") return null;
  const slug = str(d.slug);
  const area = num(d.net_area_m2);
  if (!slug || area === null) return null;
  return {
    roomId: str(d.room_id) ?? slug,
    name: str(d.name),
    slug,
    netAreaM2: area,
    isRoofed: d.is_roofed !== false,
  };
}

const areaFormat = new Intl.NumberFormat("es-PE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export function formatArea(m2: number): string {
  return `${areaFormat.format(m2)} m²`;
}

/** "DORM. PRINCIPAL" → "Dorm. Principal"; "S.H." stays as is. */
export function prettyName(name: string | null): string {
  if (!name) return "Ambiente";
  if (/^[A-ZÁÉÍÓÚÑ.\s]{1,6}$/.test(name) && name.includes(".")) return name; // abbreviations: S.H., SS.HH.
  return name
    .toLowerCase()
    .replace(/(^|[\s\-./])(\p{L})/gu, (_, sep: string, ch: string) => sep + ch.toUpperCase());
}
