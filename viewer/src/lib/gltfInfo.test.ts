import { describe, expect, it } from "vitest";
import { formatArea, prettyName, readFloorInfo, readUnitInfo } from "./gltfInfo";

describe("readUnitInfo", () => {
  it("reads the area to display and its kind", () => {
    const u = readUnitInfo({ display_area_m2: 72.5, display_area_kind: "declarada", floor_to_ceiling: 2.5 });
    expect(u.displayAreaM2).toBe(72.5);
    expect(u.displayAreaKind).toBe("declarada");
    expect(u.floorToCeiling).toBe(2.5);
  });

  it("tolerates missing extras (GLB from another tool)", () => {
    const u = readUnitInfo(undefined);
    expect(u.displayAreaM2).toBeNull();
    expect(u.displayAreaKind).toBeNull();
    expect(u.floorToCeiling).toBe(2.4);
  });
});

describe("readFloorInfo", () => {
  it("reads floor nodes", () => {
    const f = readFloorInfo({
      type: "floor",
      room_id: "room_06",
      name: "SALA-COMEDOR",
      slug: "sala_comedor",
      net_area_m2: 18.825,
      is_roofed: true,
    });
    expect(f).toEqual({ roomId: "room_06", name: "SALA-COMEDOR", slug: "sala_comedor", netAreaM2: 18.825, isRoofed: true });
  });

  it("ignores walls and incomplete data", () => {
    expect(readFloorInfo({ type: "wall", wall_id: "wall_001" })).toBeNull();
    expect(readFloorInfo({ type: "floor", slug: "x" })).toBeNull();
    expect(readFloorInfo(undefined)).toBeNull();
  });
});

describe("formatting", () => {
  it("formats areas with two decimals", () => {
    expect(formatArea(18.825)).toMatch(/^18[.,]8[23] m²$/);
    expect(formatArea(4.9)).toMatch(/^4[.,]90 m²$/);
  });

  it("prettifies room names but keeps abbreviations", () => {
    expect(prettyName("SALA-COMEDOR")).toBe("Sala-Comedor");
    expect(prettyName("DORM. PRINCIPAL")).toBe("Dorm. Principal");
    expect(prettyName("LAVANDERÍA")).toBe("Lavandería");
    expect(prettyName("S.H.")).toBe("S.H.");
    expect(prettyName(null)).toBe("Ambiente");
  });
});
