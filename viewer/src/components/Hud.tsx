import type { ChangeEvent } from "react";
import { formatArea, prettyName, type FloorInfo, type UnitInfo } from "../lib/gltfInfo";
import type { ViewMode } from "./ModeBar";

interface Props {
  unit: UnitInfo | null;
  selected: FloorInfo | null;
  mode: ViewMode;
  isTouch: boolean;
  fileName: string | null;
  onOpenFile: (file: File) => void;
  onCloseRoom: () => void;
}

function hint(mode: ViewMode, touch: boolean): string {
  if (mode === "walk") return touch ? "Usa el joystick para caminar · arrastra para mirar" : "WASD o flechas para caminar · arrastra para mirar";
  if (mode === "plan") return touch ? "Arrastra para mover · pellizca para acercar · toca un ambiente" : "Arrastra para mover · rueda para acercar · clic en un ambiente";
  return touch ? "Arrastra para girar · pellizca para acercar · toca un piso" : "Arrastra para girar · rueda para acercar · clic en un piso";
}

export function Hud({ unit, selected, mode, isTouch, fileName, onOpenFile, onCloseRoom }: Props) {
  const pick = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) onOpenFile(file);
    e.target.value = "";
  };
  const walking = mode === "walk";

  return (
    <>
      <header className="hud-top">
        <div className="card unit">
          <div className="unit-title">{fileName ?? "Departamento modelo"}</div>
          {unit?.displayAreaM2 != null && (
            <div className="unit-area">
              {formatArea(unit.displayAreaM2)}
              <span className="muted"> área techada{unit.displayAreaKind === "calculada" ? " (calculada)" : ""}</span>
            </div>
          )}
        </div>
        <label className="btn" title="Abrir un archivo GLB">
          Abrir GLB
          <input type="file" accept=".glb,model/gltf-binary" onChange={pick} hidden />
        </label>
      </header>

      {selected && walking && (
        <section className="card room-chip" role="status" aria-live="polite">
          <span className="muted">Estás en</span> <strong className="room-name">{prettyName(selected.name)}</strong>{" "}
          <span className="room-area">{formatArea(selected.netAreaM2)}</span>
        </section>
      )}

      {selected && !walking && (
        <section className="card room" role="status" aria-live="polite">
          <button className="close" onClick={onCloseRoom} aria-label="Cerrar">
            ×
          </button>
          <div className="room-name">{prettyName(selected.name)}</div>
          <div className="room-area">
            {formatArea(selected.netAreaM2)} <span className="muted">área útil</span>
          </div>
          {!selected.isRoofed && <div className="tag">Sin techar</div>}
        </section>
      )}

      {!(selected && !walking) && <p className="hint">{hint(mode, isTouch)}</p>}
    </>
  );
}
