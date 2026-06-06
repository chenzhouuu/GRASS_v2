declare module "react-plotly.js" {
  import { Component } from "react";

  interface PlotParams {
    data: Plotly.Data[];
    layout?: Partial<Plotly.Layout>;
    config?: Partial<Plotly.Config>;
    frames?: Plotly.Frame[];
    style?: React.CSSProperties;
    className?: string;
    useResizeHandler?: boolean;
    onInitialized?: (figure: Readonly<{ data: Plotly.Data[]; layout: Partial<Plotly.Layout> }>, graphDiv: HTMLElement) => void;
    onUpdate?: (figure: Readonly<{ data: Plotly.Data[]; layout: Partial<Plotly.Layout> }>, graphDiv: HTMLElement) => void;
    onError?: (err: Error) => void;
    onClick?: (event: Readonly<Plotly.PlotMouseEvent>) => void;
    onHover?: (event: Readonly<Plotly.PlotMouseEvent>) => void;
    onRelayout?: (event: Readonly<Plotly.PlotRelayoutEvent>) => void;
    revision?: number;
  }

  export default class Plot extends Component<PlotParams> {}
}

declare module "react-plotly.js/factory" {
  import { Component } from "react";

  interface PlotParams {
    data: Plotly.Data[];
    layout?: Partial<Plotly.Layout>;
    config?: Partial<Plotly.Config>;
    frames?: Plotly.Frame[];
    style?: React.CSSProperties;
    className?: string;
    useResizeHandler?: boolean;
    revision?: number;
  }

  function createPlotlyComponent(
    plotly: object
  ): typeof Component & { new (props: PlotParams): Component<PlotParams> };

  export default createPlotlyComponent;
}

declare module "plotly.js-dist-min" {
  import * as Plotly from "plotly.js";
  export = Plotly;
}
