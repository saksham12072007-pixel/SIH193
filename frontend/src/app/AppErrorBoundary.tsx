import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
}

export class AppErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("Application rendering failed", error, errorInfo);
  }

  handleReload = () => {
    window.location.reload();
  };

  render() {
    if (this.state.hasError) {
      return (
        <main className="screen-center error-screen">
          <section className="empty-panel" role="alert">
            <span className="eyebrow">APPLICATION ERROR</span>
            <h1>KrishiMitra could not load this view</h1>
            <p>Refresh the application and try again. Your saved session will be preserved.</p>
            <button className="primary-button error-retry" onClick={this.handleReload}>Refresh application <span>↻</span></button>
          </section>
        </main>
      );
    }

    return this.props.children;
  }
}
