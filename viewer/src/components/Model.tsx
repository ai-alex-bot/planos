import { useGLTF } from "@react-three/drei";
import type { ThreeEvent } from "@react-three/fiber";
import { useEffect, useMemo } from "react";
import { BackSide, Color, Mesh, MeshBasicMaterial, MeshStandardMaterial, Object3D } from "three";
import { PLAN_WALL_FILL } from "../config";
import { readFloorInfo, type FloorInfo } from "../lib/gltfInfo";
import { firstVisibleHit } from "../lib/plan";
import type { ViewMode } from "./ModeBar";

const HIGHLIGHT = new Color("#ffb54d");
const CEILING_GLOW = "#f4f1ea";
const CLICK_DRAG_TOLERANCE_PX = 6;
const noRaycast = () => {};

interface Props {
  url: string;
  mode: ViewMode;
  selectedSlug: string | null;
  /** section height in plan view (hits above it are invisible and ignored), null otherwise */
  cutHeight: number | null;
  onSelectFloor: (floor: FloorInfo | null) => void;
  onReady: (root: Object3D) => void;
}

/**
 * Loads the GLB, lets the user pick floors and highlights the selected room.
 * - Ceilings: only visible while walking; never cast shadows nor take clicks.
 * - Plan view: every wall gets a dark copy that only draws its inner faces, so walls cut by the
 *   section plane look solid (poché). Walls are closed meshes (tested in the pipeline).
 */
export function Model({ url, mode, selectedSlug, cutHeight, onSelectFloor, onReady }: Props) {
  const gltf = useGLTF(url);

  const { root, ceilings, fills } = useMemo(() => {
    const scene = gltf.scene.clone(true);
    scene.userData = { ...gltf.scene.userData };
    const ceilings: Mesh[] = [];
    const fills: Mesh[] = [];
    const fillMaterial = new MeshBasicMaterial({ color: PLAN_WALL_FILL, side: BackSide });
    const walls: Mesh[] = [];
    scene.traverse((o) => {
      const mesh = o as Mesh;
      if (!mesh.isMesh) return;
      const type = mesh.userData?.type;
      if (readFloorInfo(mesh.userData)) {
        mesh.material = (mesh.material as MeshStandardMaterial).clone(); // own material: highlight alone
        mesh.receiveShadow = true;
      } else if (type === "ceiling") {
        // lit only from below (hemisphere ground color): a little self-light keeps it reading as white
        const mat = (mesh.material as MeshStandardMaterial).clone();
        mat.emissive = new Color(CEILING_GLOW);
        mat.emissiveIntensity = 0.35;
        mesh.material = mat;
        mesh.castShadow = false;
        mesh.receiveShadow = false;
        mesh.raycast = noRaycast; // no clicks, no collisions, no "Estás en" interference
        ceilings.push(mesh);
      } else {
        mesh.castShadow = true;
        mesh.receiveShadow = true;
        if (type === "wall") walls.push(mesh);
      }
    });
    for (const wall of walls) {
      const fill = new Mesh(wall.geometry, fillMaterial);
      fill.userData = { type: "wall_fill" };
      fill.raycast = noRaycast;
      fill.castShadow = false;
      fill.visible = false;
      wall.add(fill);
      fills.push(fill);
    }
    return { root: scene, ceilings, fills };
  }, [gltf]);

  useEffect(() => onReady(root), [root, onReady]);

  useEffect(() => {
    for (const c of ceilings) c.visible = mode === "walk";
    for (const f of fills) f.visible = mode === "plan";
    if (import.meta.env.DEV) {
      (window as unknown as { __ceilingsVisible?: number }).__ceilingsVisible = ceilings.filter((c) => c.visible).length;
    }
  }, [mode, ceilings, fills]);

  useEffect(() => {
    root.traverse((o) => {
      const mesh = o as Mesh;
      const info = mesh.isMesh ? readFloorInfo(mesh.userData) : null;
      if (!info) return;
      const mat = mesh.material as MeshStandardMaterial;
      const on = info.slug === selectedSlug;
      mat.emissive.copy(on ? HIGHLIGHT : new Color(0x000000));
      mat.emissiveIntensity = on ? 0.45 : 0;
    });
  }, [root, selectedSlug]);

  const handleClick = (e: ThreeEvent<MouseEvent>) => {
    if (mode === "walk") return; // taps are used to look around
    e.stopPropagation(); // only the nearest visible hit counts (a wall in front blocks the floor behind)
    if (e.delta > CLICK_DRAG_TOLERANCE_PX) return; // it was a drag (orbit/pan), not a tap
    onSelectFloor(readFloorInfo(firstVisibleHit(e.intersections, cutHeight)?.object.userData));
  };

  return <primitive object={root} onClick={handleClick} />;
}
