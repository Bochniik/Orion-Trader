import React from "react";
import OrionMark from "./OrionMark";

export default class AppErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error("Orion UI render failure", error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <main className="orion-system-state" role="alert">
          <section className="orion-system-state-card">
            <OrionMark size={54} className="orion-system-state-mark" />
            <p className="orion-system-state-eyebrow">Display recovery</p>
            <h1>Orion hit a display error</h1>
            <p className="orion-system-state-copy">
              The workspace could not be rendered safely. Reload Orion to restore the current session and interface.
            </p>
            <button className="orion-system-state-action" type="button" onClick={() => window.location.reload()}>
              Reload Orion
            </button>
          </section>
        </main>
      );
    }

    return this.props.children;
  }
}
