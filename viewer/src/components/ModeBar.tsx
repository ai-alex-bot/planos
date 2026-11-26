export type ViewMode = "orbit" | "plan" | "walk";

const MODES: { id: ViewMode; label: string }[] = [
  { id: "orbit", label: "Órbita" },
  { id: "plan", label: "Planta" },
  { id: "walk", label: "Caminar" },
];

export function ModeBar({ mode, onChange }: { mode: ViewMode; onChange: (m: ViewMode) => void }) {
  return (
    <nav className="mode-bar card" aria-label="Modo de vista">
      {MODES.map((m) => (
        <button
          key={m.id}
          className={`mode-btn${m.id === mode ? " active" : ""}`}
          aria-pressed={m.id === mode}
          onClick={() => onChange(m.id)}
        >
          {m.label}
        </button>
      ))}
    </nav>
  );
}
