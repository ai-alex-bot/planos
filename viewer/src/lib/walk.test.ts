import { describe, expect, it } from "vitest";
import { clampPitch, MAX_PITCH, moveVector, stepDelta, yawTowards } from "./walk";

describe("moveVector", () => {
  it("combines keys and normalizes diagonals", () => {
    expect(moveVector(["KeyW"])).toEqual({ x: 0, y: 1 });
    const d = moveVector(["KeyW", "KeyD"]);
    expect(Math.hypot(d.x, d.y)).toBeCloseTo(1);
    expect(moveVector(["KeyW", "KeyS"])).toEqual({ x: 0, y: 0 });
    expect(moveVector([], { x: 0.3, y: 0.4 })).toEqual({ x: 0.3, y: 0.4 }); // partial joystick keeps its speed
    expect(moveVector(["KeyQ"])).toEqual({ x: 0, y: 0 });
  });
});

describe("stepDelta", () => {
  it("moves forward along -Z when yaw is 0", () => {
    const [dx, dz] = stepDelta(0, { x: 0, y: 1 }, 2, 0.5);
    expect(dx).toBeCloseTo(0);
    expect(dz).toBeCloseTo(-1);
  });

  it("strafes right along +X when yaw is 0 and turns with yaw", () => {
    const [dx, dz] = stepDelta(0, { x: 1, y: 0 }, 1, 1);
    expect(dx).toBeCloseTo(1);
    expect(dz).toBeCloseTo(0);
    const [fx, fz] = stepDelta(Math.PI / 2, { x: 0, y: 1 }, 1, 1); // turned left: forward is -X
    expect(fx).toBeCloseTo(-1);
    expect(fz).toBeCloseTo(0);
  });

  it("yawTowards is consistent with stepDelta", () => {
    const yaw = yawTowards(0, 0, 3, 4);
    const [dx, dz] = stepDelta(yaw, { x: 0, y: 1 }, 5, 1);
    expect(dx).toBeCloseTo(3);
    expect(dz).toBeCloseTo(4);
  });
});

describe("clampPitch", () => {
  it("limits looking up/down", () => {
    expect(clampPitch(3)).toBe(MAX_PITCH);
    expect(clampPitch(-3)).toBe(-MAX_PITCH);
    expect(clampPitch(0.2)).toBe(0.2);
  });
});
