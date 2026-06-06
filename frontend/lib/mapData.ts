import type {
  GeoJSONFeature,
  GeoJSONFeatureCollection,
  MapLayer,
  MapPayload,
} from "@/lib/types";

function buildMarkerId(feature: GeoJSONFeature, idx: number): string {
  const props = feature.properties ?? {};
  const coords = feature.geometry.coordinates as number[];
  const stableKey = props.id ?? props.name ?? props.label ?? `${coords[0]},${coords[1]}`;
  return `geo_${idx}_${String(stableKey)}`;
}

function buildRouteId(feature: GeoJSONFeature, idx: number): string {
  const props = feature.properties ?? {};
  const coords = feature.geometry.coordinates as number[][];
  const stableKey =
    props.id ??
    props.route_id ??
    props.origin_name ??
    props.label ??
    `${coords[0]?.join(",")}->${coords[coords.length - 1]?.join(",")}`;
  return `route_${idx}_${String(stableKey)}`;
}

export function geoJsonToMapPayload(
  geojson: GeoJSONFeatureCollection | null | undefined,
): Required<MapPayload> {
  const features = geojson?.features ?? [];

  const markers = features
    .filter((f): f is GeoJSONFeature & { geometry: { type: "Point"; coordinates: number[] } } =>
      f.geometry.type === "Point"
    )
    .map((f, idx) => {
      const [lng, lat] = f.geometry.coordinates;
      const props = f.properties ?? {};
      return {
        id: buildMarkerId(f, idx),
        lat,
        lng,
        label: String(props.name ?? props.label ?? `Location ${idx + 1}`),
        type: String(props.type ?? props.category ?? ""),
        properties: props,
      };
    });

  const routes = features
    .filter((f): f is GeoJSONFeature & { geometry: { type: "LineString"; coordinates: number[][] } } =>
      f.geometry.type === "LineString"
    )
    .map((f, idx) => {
      const coords = f.geometry.coordinates;
      const props = f.properties ?? {};
      return {
        id: buildRouteId(f, idx),
        from: [coords[0][1], coords[0][0]] as [number, number],
        to: [coords[coords.length - 1][1], coords[coords.length - 1][0]] as [number, number],
        label: String(props.origin_name ?? props.label ?? ""),
        properties: props,
      };
    });

  const layers: MapLayer[] = routes.length
    ? [
        {
          id: `routes_${routes.length}_${routes[0]?.id ?? "empty"}`,
          type: "routes",
          visible: true,
          data: routes,
        },
      ]
    : [];

  return { markers, layers };
}
