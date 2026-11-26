import { useRef, useState, type MutableRefObject, type PointerEvent } from "react";
import type { Vec2 } from "../lib/walk";

const RADIUS = 48; // px the knob can travel
const DEAD_ZONE = 0.12;

/** On-screen joystick for walking on touch devices. Writes the move vector into `value`. */
export function Joystick({ value }: { value: MutableRefObject<Vec2> }) {
  const base = useRef<HTMLDivElement>(null);
  const pointer = useRef<number | null>(null);
  const [knob, setKnob] = useState({ x: 0, y: 0 });

  const update = (e: PointerEvent) => {
    const rect = base.current!.getBoundingClientRect();
    let dx = e.clientX - (rect.left + rect.width / 2);
    let dy = e.clientY - (rect.top + rect.height / 2);
    const len = Math.hypot(dx, dy);
    if (len > RADIUS) {
      dx = (dx / len) * RADIUS;
      dy = (dy / len) * RADIUS;
    }
    setKnob({ x: dx, y: dy });
    const nx = dx / RADIUS;
    const ny = -dy / RADIUS; // screen up = forward
    value.current = Math.hypot(nx, ny) < DEAD_ZONE ? { x: 0, y: 0 } : { x: nx, y: ny };
  };

  const end = () => {
    pointer.current = null;
    setKnob({ x: 0, y: 0 });
    value.current = { x: 0, y: 0 };
  };

  return (
    <div
      ref={base}
      className="joystick"
      aria-label="Joystick para caminar"
      onPointerDown={(e) => {
        pointer.current = e.pointerId;
        e.currentTarget.setPointerCapture(e.pointerId);
        update(e);
      }}
      onPointerMove={(e) => e.pointerId === pointer.current && update(e)}
      onPointerUp={end}
      onPointerCancel={end}
    >
      <div className="joystick-knob" style={{ transform: `translate(${knob.x}px, ${knob.y}px)` }} />
    </div>
  );
}
