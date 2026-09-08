import React from "react";

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
        <main className="auth-screen" role="alert">
          <div>
            <h1>Orion hit a display error</h1>
            <p>The analysis could not be rendered safely. Reload Orion or choose another stock.</p>
            <button type="button" onClick={() => window.location.reload()}>
              Reload Orion
            </button>
          </div>
        </main>
      );
    }

    return this.props.children;
  }
}
