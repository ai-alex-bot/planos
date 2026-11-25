import { useGLTF } from "@react-three/drei";
import type { ThreeEvent } from "@react-three/fiber";
import { useEffect, useMemo } from "react";
import { Color, Mesh, MeshStandardMaterial, Object3D } from "three";
import { readFloorInfo, type FloorInfo } from "../lib/gltfInfo";

const HIGHLIGHT = new Color("#ffb54d");
const CLICK_DRAG_TOLERANCE_PX = 6;

interface Props {
  url: string;
  selectedSlug: string | null;
  onSelectFloor: (floor: FloorInfo | null) => void;
  onReady: (root: Object3D) => void;
}

/** Loads the GLB, lets the user pick floors and highlights the selected room. */
export function Model({ url, selectedSlug, onSelectFloor, onReady }: Props) {
  const gltf = useGLTF(url);

  const root = useMemo(() => {
    const scene = gltf.scene.clone(true);
    scene.userData = { ...gltf.scene.userData };
    scene.traverse((o) => {
      const mesh = o as Mesh;
      if (!mesh.isMesh) return;
      if (readFloorInfo(mesh.userData)) {
        // own material per floor so it can be highlighted alone
        mesh.material = (mesh.material as MeshStandardMaterial).clone();
        mesh.receiveShadow = true;
      } else {
        mesh.castShadow = true;
        mesh.receiveShadow = true;
      }
    });
    return scene;
  }, [gltf]);

  useEffect(() => onReady(root), [root, onReady]);

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
    e.stopPropagation(); // only the nearest hit counts (a wall in front blocks the floor behind)
    if (e.delta > CLICK_DRAG_TOLERANCE_PX) return; // it was a drag (orbit), not a tap
    onSelectFloor(readFloorInfo(e.intersections[0]?.object.userData));
  };

  return <primitive object={root} onClick={handleClick} />;
}
