import { Box3, Mesh, Object3D, Vector3 } from "three";
import { readFloorInfo, type FloorInfo } from "./gltfInfo";
import { yawTowards } from "./walk";

export interface FloorEntry {
  mesh: Mesh;
  info: FloorInfo;
  /** label anchor: pipeline label position, else bbox center */
  anchor: Vector3;
}

export interface SceneIndex {
  center: Vector3;
  size: Vector3;
  walls: Mesh[];
  floors: FloorEntry[];
  walkStart: { position: Vector3; yaw: number };
}

/** Everything the camera rigs need, computed once per loaded model. */
export function indexScene(root: Object3D): SceneIndex {
  root.updateMatrixWorld(true);
  const box = new Box3().setFromObject(root);
  const center = box.getCenter(new Vector3());
  const size = box.getSize(new Vector3());
  const walls: Mesh[] = [];
  const floors: FloorEntry[] = [];
  root.traverse((o) => {
    const mesh = o as Mesh;
    if (!mesh.isMesh) return;
    if (mesh.userData?.type === "wall") walls.push(mesh);
    const info = readFloorInfo(mesh.userData);
    if (info) {
      const anchor = info.labelPosition
        ? new Vector3(...info.labelPosition).applyMatrix4(root.matrixWorld)
        : new Box3().setFromObject(mesh).getCenter(new Vector3());
      floors.push({ mesh, info, anchor });
    }
  });

  // walking starts in the largest roofed room (usually the living room), looking at the unit center
  const roofed = floors.filter((f) => f.info.isRoofed);
  const pool = roofed.length ? roofed : floors;
  const start = pool.reduce<FloorEntry | null>((a, b) => (!a || b.info.netAreaM2 > a.info.netAreaM2 ? b : a), null);
  const position = start ? start.anchor.clone() : center.clone();
  const yaw =
    position.distanceTo(new Vector3(center.x, position.y, center.z)) > 0.5
      ? yawTowards(position.x, position.z, center.x, center.z)
      : 0;
  return { center, size, walls, floors, walkStart: { position, yaw } };
}
