"use client";

import { Component, Fragment, type ReactNode } from "react";

interface State {
  generation: number;
  error: Error | null;
}

/**
 * Self-healing boundary for a react-leaflet v4 fault ("Map container is
 * already initialized"). When React hides and re-shows a mounted subtree
 * — a Suspense boundary re-suspending, or Fast Refresh in dev — refs
 * detach and re-attach, and MapContainer's init guard (`context === null`,
 * closed over at first render with an empty dependency list) passes again,
 * so Leaflet initializes a DOM node that already carries a map and throws.
 * Fixed upstream only in react-leaflet v5, which requires React 19.
 *
 * Recovery: remount the subtree under a fresh key, giving Leaflet a fresh
 * node. The viewport lives in the map store, so the user keeps their view.
 * Any other error is re-thrown to the outer panel boundary.
 */
export class MapInitRecovery extends Component<{ children: ReactNode }, State> {
  state: State = { generation: 0, error: null };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  componentDidCatch(error: Error) {
    if (/already initialized/i.test(error.message)) {
      this.setState((s) => ({ generation: s.generation + 1, error: null }));
    }
  }

  render() {
    const { error, generation } = this.state;
    if (error) {
      if (/already initialized/i.test(error.message)) {
        return null; // one frame; componentDidCatch remounts with a fresh key
      }
      throw error; // not ours — the panel's error boundary handles it
    }
    return <Fragment key={generation}>{this.props.children}</Fragment>;
  }
}
