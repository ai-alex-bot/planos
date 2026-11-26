import { Environment } from "@react-three/drei";
import { Canvas } from "@react-three/fiber";
import { Suspense, useCallback, useState, type MutableRefObject } from "react";
import { Object3D } from "three";
import type { FloorInfo, UnitInfo } from "../lib/gltfInfo";
import { readUnitInfo } from "../lib/gltfInfo";
import { indexScene, type SceneIndex } from "../lib/sceneIndex";
import type { Vec2 } from "../lib/walk";
import type { ViewMode } from "./ModeBar";
import { Model } from "./Model";
import { OrbitRig, PlanRig, WalkRig } from "./rigs";

export const HDRI_URL = `${import.meta.env.BASE_URL}hdri/lebombo_1k.hdr`;

interface Props {
  url: string;
  mode: ViewMode;
  selectedSlug: string | null;
  joystick: MutableRefObject<Vec2>;
  onSelectFloor: (floor: FloorInfo | null) => void;
  onUnitInfo: (info: UnitInfo) => void;
}

export function Viewer3D({ url, mode, selectedSlug, joystick, onSelectFloor, onUnitInfo }: Props) {
  const [index, setIndex] = useState<SceneIndex | null>(null);

  const handleReady = useCallback(
    (root: Object3D) => {
      setIndex(indexScene(root));
      onUnitInfo(readUnitInfo(root.userData));
    },
    [onUnitInfo],
  );

  const walking = mode === "walk";
  return (
    <Canvas
      className="canvas"
      shadows
      dpr={[1, 2]}
      onPointerMissed={() => !walking && onSelectFloor(null)}
    >
      <color attach="background" args={["#f3f1ec"]} />
      <hemisphereLight args={["#ffffff", "#d8d2c4", 0.35]} />
      <directionalLight position={[6, 12, 4]} intensity={1.2} castShadow shadow-mapSize={[2048, 2048]}>
        <orthographicCamera attach="shadow-camera" args={[-10, 10, 10, -10, 0.5, 40]} />
      </directionalLight>
      <Suspense fallback={null}>
        <Environment files={HDRI_URL} environmentIntensity={0.8} />
        <Model
          url={url}
          selectedSlug={walking ? null : selectedSlug}
          interactive={!walking}
          onSelectFloor={onSelectFloor}
          onReady={handleReady}
        />
      </Suspense>
      <mesh rotation-x={-Math.PI / 2} position-y={-0.005} receiveShadow>
        <planeGeometry args={[200, 200]} />
        <meshStandardMaterial color="#e7e3da" roughness={1} />
      </mesh>
      {index && mode === "orbit" && <OrbitRig index={index} />}
      {index && mode === "plan" && <PlanRig index={index} floors />}
      {index && mode === "walk" && <WalkRig index={index} joystick={joystick} onRoom={onSelectFloor} />}
    </Canvas>
  );
}
