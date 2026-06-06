"use client";

import { Component, type ReactNode } from "react";
import { AlertTriangle } from "lucide-react";

interface Props {
  children: ReactNode;
  title?: string;
}

interface State {
  hasError: boolean;
  error: string | null;
}

/**
 * Error boundary for Plotly chart rendering.
 *
 * Catches render errors from react-plotly.js (e.g., malformed specs,
 * missing data traces) and shows a user-friendly fallback instead
 * of a blank white box or React crash.
 */
export class ChartErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error: error.message };
  }

  componentDidCatch(error: Error) {
    console.error("[ChartErrorBoundary]", this.props.title ?? "chart", error);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex h-full w-full flex-col items-center justify-center gap-2 rounded bg-muted/30 p-4 text-muted-foreground">
          <AlertTriangle className="h-5 w-5 text-amber-500" />
          <p className="text-xs font-medium">Chart failed to render</p>
          {this.state.error && (
            <p className="max-w-[300px] text-center text-[10px] opacity-60">
              {this.state.error.slice(0, 120)}
            </p>
          )}
        </div>
      );
    }
    return this.props.children;
  }
}
