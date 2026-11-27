// Viewer settings. Values can be overridden from the URL for demos (e.g. ?corte=1.4).

/** Height of the horizontal section plane in plan view (m), like an architectural floor plan. */
export const DEFAULT_PLAN_CUT_HEIGHT = 1.2;
const MIN_CUT = 0.3;
const MAX_CUT = 2.3;

export function planCutHeight(search: string = window.location.search): number {
  const raw = new URLSearchParams(search).get("corte");
  const v = raw === null ? NaN : Number(raw.replace(",", "."));
  if (!Number.isFinite(v)) return DEFAULT_PLAN_CUT_HEIGHT;
  return Math.min(MAX_CUT, Math.max(MIN_CUT, v));
}

/** Colors used only in plan view. */
export const PLAN_WALL_FILL = "#3b3833"; // cut walls (poché)
export const PLAN_OPENING_LINE = "#2f6fd6"; // windows and glass doors
