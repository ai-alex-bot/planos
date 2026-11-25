import { Environment, OrbitControls } from "@react-three/drei";
import { Canvas, useThree } from "@react-three/fiber";
import { Suspense, useCallback, useEffect, useState } from "react";
import { Box3, Object3D, PerspectiveCamera, Vector3 } from "three";
import type { FloorInfo, UnitInfo } from "../lib/gltfInfo";
import { readUnitInfo } from "../lib/gltfInfo";
import { Model } from "./Model";

export const HDRI_URL = `${import.meta.env.BASE_URL}hdri/lebombo_1k.hdr`;

export interface Bounds {
  center: Vector3;
  size: Vector3;
}

interface Props {
  url: string;
  selectedSlug: string | null;
  onSelectFloor: (floor: FloorInfo | null) => void;
  onUnitInfo: (info: UnitInfo) => void;
}

const ORBIT_DIRECTION = new Vector3(0.55, 0.85, 0.75).normalize();
const FIT_MARGIN = 1.08;

/** Distance at which a sphere of the model's size fits both the vertical and horizontal FOV. */
export function fitDistance(size: Vector3, fovDeg: number, aspect: number): number {
  const radius = size.length() / 2;
  const v = (fovDeg * Math.PI) / 180;
  const h = 2 * Math.atan(Math.tan(v / 2) * aspect);
  return (radius / Math.sin(Math.min(v, h) / 2)) * FIT_MARGIN;
}

function OrbitRig({ bounds }: { bounds: Bounds }) {
  const camera = useThree((s) => s.camera) as PerspectiveCamera;
  const aspect = useThree((s) => s.size.width / Math.max(1, s.size.height));
  useEffect(() => {
    const d = fitDistance(bounds.size, camera.fov, aspect);
    camera.position.copy(bounds.center).addScaledVector(ORBIT_DIRECTION, d);
    camera.near = 0.05;
    camera.far = d * 20;
    camera.updateProjectionMatrix();
  }, [camera, bounds, aspect]);
  const r = Math.max(bounds.size.x, bounds.size.z);
  return (
    <OrbitControls
      makeDefault
      target={[bounds.center.x, 0.8, bounds.center.z]}
      maxPolarAngle={Math.PI / 2 - 0.05}
      minDistance={1.5}
      maxDistance={r * 4}
      enableDamping
    />
  );
}

export function Viewer3D({ url, selectedSlug, onSelectFloor, onUnitInfo }: Props) {
  const [bounds, setBounds] = useState<Bounds | null>(null);

  const handleReady = useCallback(
    (root: Object3D) => {
      const box = new Box3().setFromObject(root);
      setBounds({ center: box.getCenter(new Vector3()), size: box.getSize(new Vector3()) });
      onUnitInfo(readUnitInfo(root.userData));
    },
    [onUnitInfo],
  );

  return (
    <Canvas
      className="canvas"
      shadows
      dpr={[1, 2]}
      camera={{ fov: 50, position: [8, 10, 10] }}
      onPointerMissed={() => onSelectFloor(null)}
    >
      <color attach="background" args={["#f3f1ec"]} />
      <hemisphereLight args={["#ffffff", "#d8d2c4", 0.35]} />
      <directionalLight position={[6, 12, 4]} intensity={1.2} castShadow shadow-mapSize={[2048, 2048]}>
        <orthographicCamera attach="shadow-camera" args={[-10, 10, 10, -10, 0.5, 40]} />
      </directionalLight>
      <Suspense fallback={null}>
        <Environment files={HDRI_URL} environmentIntensity={0.8} />
        <Model url={url} selectedSlug={selectedSlug} onSelectFloor={onSelectFloor} onReady={handleReady} />
      </Suspense>
      <mesh rotation-x={-Math.PI / 2} position-y={-0.005} receiveShadow>
        <planeGeometry args={[200, 200]} />
        <meshStandardMaterial color="#e7e3da" roughness={1} />
      </mesh>
      {bounds && <OrbitRig bounds={bounds} />}
    </Canvas>
  );
}
