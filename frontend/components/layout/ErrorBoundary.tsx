"use client";

import { Component, type ReactNode } from "react";
import { AlertTriangle, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";

interface Props {
  children: ReactNode;
  name?: string;
}

interface State {
  error: Error | null;
}

export class PanelErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error(
      `[ErrorBoundary] ${this.props.name ?? "Panel"} crashed:`,
      error,
      info.componentStack,
    );
  }

  render() {
    if (this.state.error) {
      return (
        <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center">
          <AlertTriangle className="h-8 w-8 text-destructive/60" />
          <div>
            <p className="text-sm font-medium">
              {this.props.name ?? "Panel"} encountered an error
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              {this.state.error.message}
            </p>
          </div>
          <Button
            variant="outline"
            size="sm"
            className="gap-1.5"
            onClick={() => this.setState({ error: null })}
          >
            <RotateCcw className="h-3.5 w-3.5" />
            Retry
          </Button>
        </div>
      );
    }
    return this.props.children;
  }
}
