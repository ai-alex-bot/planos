import { useCallback, useEffect, useState } from "react";
import { DropZone } from "./components/DropZone";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { Hud } from "./components/Hud";
import { Viewer3D } from "./components/Viewer3D";
import type { FloorInfo, UnitInfo } from "./lib/gltfInfo";

const DEFAULT_MODEL = `${import.meta.env.BASE_URL}models/demo.glb`;

/** ?model=otro.glb loads public/models/otro.glb (handy for demos with several units). */
function initialModel(): string {
  const name = new URLSearchParams(window.location.search).get("model");
  if (name && /^[\w.-]+\.glb$/i.test(name)) return `${import.meta.env.BASE_URL}models/${name}`;
  return DEFAULT_MODEL;
}

export default function App() {
  const [url, setUrl] = useState(initialModel);
  const [fileName, setFileName] = useState<string | null>(null);
  const [unit, setUnit] = useState<UnitInfo | null>(null);
  const [selected, setSelected] = useState<FloorInfo | null>(null);

  const openFile = useCallback((file: File) => {
    setUrl(URL.createObjectURL(file));
    setFileName(file.name.replace(/\.glb$/i, ""));
    setSelected(null);
    setUnit(null);
  }, []);

  // free the previous blob when another file is opened
  useEffect(() => () => {
    if (url.startsWith("blob:")) URL.revokeObjectURL(url);
  }, [url]);

  return (
    <div className="app">
      <ErrorBoundary resetKey={url}>
        <Viewer3D url={url} selectedSlug={selected?.slug ?? null} onSelectFloor={setSelected} onUnitInfo={setUnit} />
      </ErrorBoundary>
      <Hud unit={unit} selected={selected} fileName={fileName} onOpenFile={openFile} onCloseRoom={() => setSelected(null)} />
      <DropZone onFile={openFile} />
    </div>
  );
}
