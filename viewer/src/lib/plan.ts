// Plan view helpers (pure, unit-tested).
import { Matrix4, Vector3 } from "three";

export type OpeningKind = "door" | "window" | "glass_door" | "passage" | "railing";

export interface OpeningInfo {
  id: string;
  kind: OpeningKind;
  width: number;
  sillHeight: number;
  headHeight: number;
}

const KINDS: OpeningKind[] = ["door", "window", "glass_door", "passage", "railing"];

export function readOpeningInfo(userData: Record<string, unknown> | undefined): OpeningInfo | null {
  const d = userData ?? {};
  if (d.type !== "opening" || typeof d.kind !== "string" || !KINDS.includes(d.kind as OpeningKind)) return null;
  const width = typeof d.width === "number" ? d.width : NaN;
  if (!(width > 0)) return null;
  return {
    id: typeof d.opening_id === "string" ? d.opening_id : "",
    kind: d.kind as OpeningKind,
    width,
    sillHeight: typeof d.sill_height === "number" ? d.sill_height : 0,
    headHeight: typeof d.head_height === "number" ? d.head_height : 0,
  };
}

/** Windows and glass doors are drawn as a line over the gap; doors, passages and railings are not. */
export function drawsPlanLine(kind: OpeningKind): boolean {
  return kind === "window" || kind === "glass_door";
}

/**
 * World endpoints of an opening's line: the opening node's local X axis runs along its wall,
 * centered on the node. `y` is the drawing height (just below the section plane).
 */
export function openingLine(nodeMatrixWorld: Matrix4, width: number, y: number): [Vector3, Vector3] {
  const a = new Vector3(-width / 2, 0, 0).applyMatrix4(nodeMatrixWorld);
  const b = new Vector3(width / 2, 0, 0).applyMatrix4(nodeMatrixWorld);
  a.y = y;
  b.y = y;
  return [a, b];
}

/** First hit that is still visible below the section plane (three's raycaster ignores clipping). */
export function firstVisibleHit<T extends { point: { y: number } }>(hits: T[], cutHeight: number | null): T | undefined {
  if (cutHeight === null) return hits[0];
  return hits.find((h) => h.point.y <= cutHeight + 1e-3);
}
