import { useCallback, useEffect, useRef, useState } from "react";
import { DropZone } from "./components/DropZone";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { Hud } from "./components/Hud";
import { Joystick } from "./components/Joystick";
import { ModeBar, type ViewMode } from "./components/ModeBar";
import { Viewer3D } from "./components/Viewer3D";
import type { FloorInfo, UnitInfo } from "./lib/gltfInfo";
import type { Vec2 } from "./lib/walk";

const DEFAULT_MODEL = `${import.meta.env.BASE_URL}models/demo.glb`;
const MODES: ViewMode[] = ["orbit", "plan", "walk"];

/** ?model=otro.glb loads public/models/otro.glb; ?modo=planta|caminar picks the initial view. */
function initialModel(): string {
  const name = new URLSearchParams(window.location.search).get("model");
  if (name && /^[\w.-]+\.glb$/i.test(name)) return `${import.meta.env.BASE_URL}models/${name}`;
  return DEFAULT_MODEL;
}

function initialMode(): ViewMode {
  const m = new URLSearchParams(window.location.search).get("modo");
  return ({ orbita: "orbit", planta: "plan", caminar: "walk" } as Record<string, ViewMode>)[m ?? ""] ?? "orbit";
}

function useIsTouch(): boolean {
  const [touch, setTouch] = useState(() => window.matchMedia("(pointer: coarse)").matches);
  useEffect(() => {
    const mq = window.matchMedia("(pointer: coarse)");
    const on = () => setTouch(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return touch;
}

export default function App() {
  const [url, setUrl] = useState(initialModel);
  const [fileName, setFileName] = useState<string | null>(null);
  const [unit, setUnit] = useState<UnitInfo | null>(null);
  const [selected, setSelected] = useState<FloorInfo | null>(null);
  const [mode, setMode] = useState<ViewMode>(initialMode);
  const joystick = useRef<Vec2>({ x: 0, y: 0 });
  const isTouch = useIsTouch();

  const openFile = useCallback((file: File) => {
    setUrl(URL.createObjectURL(file));
    setFileName(file.name.replace(/\.glb$/i, ""));
    setSelected(null);
    setUnit(null);
  }, []);

  const changeMode = useCallback((m: ViewMode) => {
    setMode(m);
    setSelected(null);
    joystick.current = { x: 0, y: 0 };
  }, []);

  // keys 1/2/3 switch modes on desktop
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const i = ["Digit1", "Digit2", "Digit3"].indexOf(e.code);
      if (i >= 0 && !(e.target instanceof HTMLInputElement)) changeMode(MODES[i]);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [changeMode]);

  // free the previous blob when another file is opened
  useEffect(() => () => {
    if (url.startsWith("blob:")) URL.revokeObjectURL(url);
  }, [url]);

  return (
    <div className={`app mode-${mode}`}>
      <ErrorBoundary resetKey={url}>
        <Viewer3D
          url={url}
          mode={mode}
          selectedSlug={selected?.slug ?? null}
          joystick={joystick}
          onSelectFloor={setSelected}
          onUnitInfo={setUnit}
        />
      </ErrorBoundary>
      <Hud
        unit={unit}
        selected={selected}
        mode={mode}
        isTouch={isTouch}
        fileName={fileName}
        onOpenFile={openFile}
        onCloseRoom={() => setSelected(null)}
      />
      {mode === "walk" && isTouch && <Joystick value={joystick} />}
      <ModeBar mode={mode} onChange={changeMode} />
      <DropZone onFile={openFile} />
    </div>
  );
}
