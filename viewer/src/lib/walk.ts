// First-person walking: pure helpers (unit-tested), used by WalkRig.

export const EYE_HEIGHT = 1.6; // m
export const WALK_SPEED = 1.4; // m/s, normal walking pace
export const RUN_FACTOR = 1.8; // with Shift
export const BODY_RADIUS = 0.25; // m, keeps the camera off the walls
export const COLLISION_HEIGHTS = [0.3, 1.0, 1.5]; // rays at knee, hip and chest height: sills block, doors don't
export const LOOK_SENSITIVITY = 0.005; // rad per pixel dragged
export const MAX_PITCH = (80 * Math.PI) / 180;

export interface Vec2 {
  x: number; // right
  y: number; // forward
}

const KEYMAP: Record<string, Vec2> = {
  KeyW: { x: 0, y: 1 },
  ArrowUp: { x: 0, y: 1 },
  KeyS: { x: 0, y: -1 },
  ArrowDown: { x: 0, y: -1 },
  KeyA: { x: -1, y: 0 },
  ArrowLeft: { x: -1, y: 0 },
  KeyD: { x: 1, y: 0 },
  ArrowRight: { x: 1, y: 0 },
};

export const MOVE_KEYS = new Set(Object.keys(KEYMAP));

/** Combined input from pressed keys (KeyboardEvent.code) and the joystick, length ≤ 1. */
export function moveVector(keys: Iterable<string>, joystick: Vec2 = { x: 0, y: 0 }): Vec2 {
  let x = joystick.x;
  let y = joystick.y;
  for (const k of keys) {
    const v = KEYMAP[k];
    if (v) {
      x += v.x;
      y += v.y;
    }
  }
  const len = Math.hypot(x, y);
  return len > 1 ? { x: x / len, y: y / len } : { x, y };
}

/**
 * World displacement (x, z) for yaw (rad, 0 = looking towards -Z, positive turns left)
 * and a move vector, over dt seconds.
 */
export function stepDelta(yaw: number, move: Vec2, speed: number, dt: number): [number, number] {
  const fx = -Math.sin(yaw);
  const fz = -Math.cos(yaw);
  const rx = Math.cos(yaw);
  const rz = -Math.sin(yaw);
  const s = speed * dt;
  return [(fx * move.y + rx * move.x) * s, (fz * move.y + rz * move.x) * s];
}

export function clampPitch(p: number): number {
  return Math.max(-MAX_PITCH, Math.min(MAX_PITCH, p));
}

/** Yaw that looks from (x, z) towards (tx, tz). */
export function yawTowards(x: number, z: number, tx: number, tz: number): number {
  return Math.atan2(-(tx - x), -(tz - z));
}
