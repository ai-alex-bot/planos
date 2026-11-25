import type { ChangeEvent } from "react";
import { formatArea, prettyName, type FloorInfo, type UnitInfo } from "../lib/gltfInfo";

interface Props {
  unit: UnitInfo | null;
  selected: FloorInfo | null;
  fileName: string | null;
  onOpenFile: (file: File) => void;
  onCloseRoom: () => void;
}

export function Hud({ unit, selected, fileName, onOpenFile, onCloseRoom }: Props) {
  const pick = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) onOpenFile(file);
    e.target.value = "";
  };

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

      {selected ? (
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
      ) : (
        <p className="hint">Toca un piso para ver el ambiente y su área</p>
      )}
    </>
  );
}
