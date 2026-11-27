import { Matrix4, Quaternion, Vector3 } from "three";
import { describe, expect, it } from "vitest";
import { planCutHeight } from "../config";
import { drawsPlanLine, firstVisibleHit, openingLine, readOpeningInfo } from "./plan";

describe("readOpeningInfo", () => {
  it("reads opening extras", () => {
    const o = readOpeningInfo({ type: "opening", opening_id: "opening_window_01", kind: "window", width: 1.4, sill_height: 1, head_height: 2.1 });
    expect(o).toEqual({ id: "opening_window_01", kind: "window", width: 1.4, sillHeight: 1, headHeight: 2.1 });
    expect(readOpeningInfo({ type: "opening", kind: "skylight", width: 1 })).toBeNull();
    expect(readOpeningInfo({ type: "floor" })).toBeNull();
  });

  it("only windows and glass doors get a plan line", () => {
    expect(drawsPlanLine("window")).toBe(true);
    expect(drawsPlanLine("glass_door")).toBe(true);
    expect(drawsPlanLine("door")).toBe(false);
    expect(drawsPlanLine("passage")).toBe(false);
    expect(drawsPlanLine("railing")).toBe(false);
  });
});

describe("openingLine", () => {
  it("runs along the node's local X axis, centered, at the given height", () => {
    // node rotated 90° about Y (a wall along -Z in world), at (2, 1, 3)
    const m = new Matrix4().compose(
      new Vector3(2, 1, 3),
      new Quaternion().setFromAxisAngle(new Vector3(0, 1, 0), Math.PI / 2),
      new Vector3(1, 1, 1),
    );
    const [a, b] = openingLine(m, 1.2, 1.18);
    expect(a.x).toBeCloseTo(2);
    expect(b.x).toBeCloseTo(2);
    expect(Math.abs(a.z - b.z)).toBeCloseTo(1.2);
    expect((a.z + b.z) / 2).toBeCloseTo(3);
    expect(a.y).toBe(1.18);
    expect(b.y).toBe(1.18);
  });
});

describe("firstVisibleHit", () => {
  const hits = [{ point: { y: 2.3 }, name: "lintel" }, { point: { y: 0 }, name: "floor" }];
  it("skips geometry above the section plane", () => {
    expect(firstVisibleHit(hits, 1.2)?.name).toBe("floor");
    expect(firstVisibleHit(hits, null)?.name).toBe("lintel");
    expect(firstVisibleHit([{ point: { y: 2 } }], 1.2)).toBeUndefined();
  });
});

describe("planCutHeight", () => {
  it("defaults to 1.20 m and accepts ?corte= within limits", () => {
    expect(planCutHeight("")).toBe(1.2);
    expect(planCutHeight("?corte=1.5")).toBe(1.5);
    expect(planCutHeight("?corte=1,4")).toBe(1.4);
    expect(planCutHeight("?corte=9")).toBe(2.3);
    expect(planCutHeight("?corte=abc")).toBe(1.2);
  });
});
