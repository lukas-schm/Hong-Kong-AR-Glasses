import { Component, type ReactNode } from 'react';

interface Props { children: ReactNode }
interface State { hasError: boolean; message: string }

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, message: '' };

  static getDerivedStateFromError(error: unknown): State {
    return { hasError: true, message: String(error) };
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: 32, color: '#f3f7ff', fontFamily: 'DM Sans, sans-serif' }}>
          <h2>Something went wrong.</h2>
          <pre style={{ marginTop: 12, fontSize: 12, opacity: 0.7 }}>{this.state.message}</pre>
        </div>
      );
    }
    return this.props.children;
  }
}
