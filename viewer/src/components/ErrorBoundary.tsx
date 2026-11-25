import { Component, type ReactNode } from "react";

interface Props {
  resetKey: string;
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/** Shows a friendly message when a GLB cannot be loaded; resets when another file is opened. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidUpdate(prev: Props) {
    if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null });
  }

  render() {
    if (this.state.error) {
      return (
        <div className="error">
          <strong>No se pudo cargar el modelo.</strong>
          <span>Verifica que sea un archivo .glb válido.</span>
        </div>
      );
    }
    return this.props.children;
  }
}
