import { Html, Line, OrbitControls, OrthographicCamera, PerspectiveCamera } from "@react-three/drei";
import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef, type MutableRefObject } from "react";
import {
  Mesh,
  MOUSE,
  PerspectiveCamera as PerspectiveCameraImpl,
  Plane,
  Raycaster,
  TOUCH,
  Vector3,
  type Intersection,
} from "three";
import { PLAN_OPENING_LINE } from "../config";
import { drawsPlanLine, openingLine } from "../lib/plan";
import { formatArea, prettyName, type FloorInfo } from "../lib/gltfInfo";
import type { SceneIndex } from "../lib/sceneIndex";
import {
  BODY_RADIUS,
  clampPitch,
  COLLISION_HEIGHTS,
  EYE_HEIGHT,
  LOOK_SENSITIVITY,
  MOVE_KEYS,
  moveVector,
  RUN_FACTOR,
  stepDelta,
  WALK_SPEED,
  type Vec2,
} from "../lib/walk";

const ORBIT_DIRECTION = new Vector3(0.55, 0.85, 0.75).normalize();
const FIT_MARGIN = 1.08;
const PLAN_MARGIN = 1.3;
const PLAN_UI_OFFSET = 0.04; // fraction of the plan height shifted up, clear of the mode bar
const MAX_FRAME_DT = 0.25; // s; collision rays cover the whole step, so slow devices still walk at full speed
const ROOM_CHECK_INTERVAL = 0.25; // s

/** Distance at which a sphere of the model's size fits both the vertical and horizontal FOV. */
export function fitDistance(size: Vector3, fovDeg: number, aspect: number): number {
  const radius = size.length() / 2;
  const v = (fovDeg * Math.PI) / 180;
  const h = 2 * Math.atan(Math.tan(v / 2) * aspect);
  return (radius / Math.sin(Math.min(v, h) / 2)) * FIT_MARGIN;
}

// ------------------------------------------------------------------ orbit

export function OrbitRig({ index }: { index: SceneIndex }) {
  const cam = useRef<PerspectiveCameraImpl>(null);
  const aspect = useThree((s) => s.size.width / Math.max(1, s.size.height));
  const d = fitDistance(index.size, 50, aspect);
  const position = useMemo(() => index.center.clone().addScaledVector(ORBIT_DIRECTION, d), [index, d]);
  const r = Math.max(index.size.x, index.size.z);
  return (
    <>
      <PerspectiveCamera ref={cam} makeDefault fov={50} near={0.05} far={d * 20} position={position} />
      <OrbitControls
        makeDefault
        target={[index.center.x, 0.8, index.center.z]}
        maxPolarAngle={Math.PI / 2 - 0.05}
        minDistance={1.5}
        maxDistance={r * 4}
        enableDamping
      />
    </>
  );
}

// ------------------------------------------------------------------ plan (top view)

const PLAN_LINE_BELOW_CUT = 0.02; // m: lines sit just under the section plane

/** Horizontal section plane for the plan view (global renderer clipping), removed on unmount. */
function SectionPlane({ height }: { height: number }) {
  const gl = useThree((s) => s.gl);
  useEffect(() => {
    gl.clippingPlanes = [new Plane(new Vector3(0, -1, 0), height)]; // keeps y <= height
    return () => {
      gl.clippingPlanes = [];
    };
  }, [gl, height]);
  return null;
}

/** Windows and glass doors as a single line over their gap. */
function OpeningLines({ index, cutHeight }: { index: SceneIndex; cutHeight: number }) {
  const lines = useMemo(() => {
    return index.openings
      .filter((o) => drawsPlanLine(o.info.kind))
      .map((o) => {
        o.node.updateWorldMatrix(true, false);
        return { id: o.info.id, points: openingLine(o.node.matrixWorld, o.info.width, cutHeight - PLAN_LINE_BELOW_CUT) };
      });
  }, [index, cutHeight]);
  useEffect(() => {
    if (import.meta.env.DEV) (window as unknown as { __planLines?: number }).__planLines = lines.length;
  }, [lines]);
  return (
    <>
      {lines.map((l) => (
        <Line key={l.id} points={l.points} color={PLAN_OPENING_LINE} lineWidth={3} raycast={() => null} />
      ))}
    </>
  );
}

export function PlanRig({ index, floors, cutHeight }: { index: SceneIndex; floors: boolean; cutHeight: number }) {
  const { width, height } = useThree((s) => s.size);
  const zoom = Math.min(width / (index.size.x * PLAN_MARGIN), height / (index.size.z * PLAN_MARGIN));
  const x = index.center.x;
  const z = index.center.z + index.size.z * PLAN_UI_OFFSET;
  return (
    <>
      {/* a hair off vertical so "up" on screen is -Z, i.e. plan north as drawn */}
      <OrthographicCamera makeDefault position={[x, 30, z + 0.001]} zoom={zoom} near={0.1} far={100} />
      <OrbitControls
        makeDefault
        target={[x, 0, z]}
        enableRotate={false}
        screenSpacePanning
        mouseButtons={{ LEFT: MOUSE.PAN, MIDDLE: MOUSE.DOLLY, RIGHT: MOUSE.PAN }}
        touches={{ ONE: TOUCH.PAN, TWO: TOUCH.DOLLY_PAN }}
        minZoom={zoom * 0.5}
        maxZoom={zoom * 6}
      />
      <SectionPlane height={cutHeight} />
      <OpeningLines index={index} cutHeight={cutHeight} />
      {floors &&
        index.floors.map((f) => (
          <Html key={f.info.slug} position={[f.anchor.x, 0.05, f.anchor.z]} center zIndexRange={[10, 0]} pointerEvents="none" wrapperClass="plan-label-wrap">
            <div className="plan-label">
              <strong>{prettyName(f.info.name)}</strong>
              <span>{formatArea(f.info.netAreaM2)}</span>
            </div>
          </Html>
        ))}
    </>
  );
}

// ------------------------------------------------------------------ walk (first person)

interface WalkProps {
  index: SceneIndex;
  joystick: MutableRefObject<Vec2>;
  onRoom: (room: FloorInfo | null) => void;
}

export function WalkRig({ index, joystick, onRoom }: WalkProps) {
  const cam = useRef<PerspectiveCameraImpl>(null);
  const gl = useThree((s) => s.gl);
  const yaw = useRef(index.walkStart.yaw);
  const pitch = useRef(0);
  const keys = useRef(new Set<string>());
  const sinceRoomCheck = useRef(ROOM_CHECK_INTERVAL);
  const lastRoom = useRef<string | null>(null);
  const ray = useMemo(() => new Raycaster(), []);
  const tmp = useMemo(() => ({ o: new Vector3(), d: new Vector3(), down: new Vector3(0, -1, 0) }), []);

  // start position
  useEffect(() => {
    const c = cam.current;
    if (!c) return;
    c.position.set(index.walkStart.position.x, EYE_HEIGHT, index.walkStart.position.z);
    yaw.current = index.walkStart.yaw;
    pitch.current = 0;
    lastRoom.current = null;
  }, [index]);

  // keyboard
  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement) return;
      if (MOVE_KEYS.has(e.code) || e.code.startsWith("Shift")) {
        keys.current.add(e.code);
        e.preventDefault();
      }
    };
    const up = (e: KeyboardEvent) => keys.current.delete(e.code);
    const blur = () => keys.current.clear();
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    window.addEventListener("blur", blur);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
      window.removeEventListener("blur", blur);
    };
  }, []);

  // drag to look (mouse or one finger on the canvas)
  useEffect(() => {
    const el = gl.domElement;
    let active: number | null = null;
    let lx = 0;
    let ly = 0;
    const down = (e: PointerEvent) => {
      if (active !== null) return;
      active = e.pointerId;
      lx = e.clientX;
      ly = e.clientY;
      el.setPointerCapture(e.pointerId);
    };
    const move = (e: PointerEvent) => {
      if (e.pointerId !== active) return;
      yaw.current += (e.clientX - lx) * LOOK_SENSITIVITY;
      pitch.current = clampPitch(pitch.current + (e.clientY - ly) * LOOK_SENSITIVITY);
      lx = e.clientX;
      ly = e.clientY;
    };
    const up = (e: PointerEvent) => {
      if (e.pointerId === active) active = null;
    };
    el.addEventListener("pointerdown", down);
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerup", up);
    el.addEventListener("pointercancel", up);
    return () => {
      el.removeEventListener("pointerdown", down);
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerup", up);
      el.removeEventListener("pointercancel", up);
    };
  }, [gl]);

  const blocked = (x: number, z: number, dx: number, dz: number): boolean => {
    const len = Math.hypot(dx, dz);
    if (len === 0) return false;
    tmp.d.set(dx / len, 0, dz / len);
    for (const h of COLLISION_HEIGHTS) {
      tmp.o.set(x, h, z);
      ray.set(tmp.o, tmp.d);
      ray.far = len + BODY_RADIUS;
      if (ray.intersectObjects(index.walls, false).length) return true;
    }
    return false;
  };

  useFrame((_, rawDt) => {
    const c = cam.current;
    if (!c) return;
    const dt = Math.min(rawDt, MAX_FRAME_DT);
    const mv = moveVector(keys.current, joystick.current);
    if (mv.x !== 0 || mv.y !== 0) {
      const run = keys.current.has("ShiftLeft") || keys.current.has("ShiftRight") ? RUN_FACTOR : 1;
      const [dx, dz] = stepDelta(yaw.current, mv, WALK_SPEED * run, dt);
      // axis-separated moves let the walker slide along walls
      if (!blocked(c.position.x, c.position.z, dx, 0)) c.position.x += dx;
      if (!blocked(c.position.x, c.position.z, 0, dz)) c.position.z += dz;
    }
    c.rotation.set(pitch.current, yaw.current, 0, "YXZ");
    if (import.meta.env.DEV) (window as unknown as { __walk?: number[] }).__walk = [c.position.x, c.position.z];

    sinceRoomCheck.current += dt;
    if (sinceRoomCheck.current >= ROOM_CHECK_INTERVAL) {
      sinceRoomCheck.current = 0;
      ray.set(tmp.o.set(c.position.x, EYE_HEIGHT, c.position.z), tmp.down);
      ray.far = EYE_HEIGHT + 0.5;
      const hit = ray.intersectObjects(index.floors.map((f) => f.mesh), false)[0];
      const room = hit ? index.floors.find((f) => f.mesh === hit.object)?.info ?? null : null;
      const slug = room?.slug ?? null;
      if (slug !== lastRoom.current) {
        lastRoom.current = slug;
        onRoom(room);
      }
      if (import.meta.env.DEV) {
        // is the view pointing at a visible ceiling, seen from below (front face)?
        const dir = c.getWorldDirection(new Vector3());
        ray.set(c.position, dir);
        ray.far = 50;
        const hits: Intersection[] = [];
        for (const m of index.ceilings) if (m.visible) Mesh.prototype.raycast.call(m, ray, hits);
        hits.sort((a, b) => a.distance - b.distance);
        const n = hits[0]?.face?.normal.clone().transformDirection(hits[0].object.matrixWorld);
        (window as unknown as { __walkView?: object }).__walkView = { ceiling: !!n && n.dot(dir) < 0, pitch: pitch.current };
      }
    }
  });

  return <PerspectiveCamera ref={cam} makeDefault fov={70} near={0.05} far={200} />;
}
