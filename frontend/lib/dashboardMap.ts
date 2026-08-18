export interface DashboardMapPoint {
  id: string;
  name: string;
  type: string;
  county: string;
  lat: number;
  lng: number;
  properties: Record<string, unknown>;
}

function asNumber(value: unknown): number | null {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function getText(value: unknown, fallback: string): string {
  if (value === null || value === undefined || value === "") return fallback;
  return String(value);
}

export function dashboardRowsToMapPoints(
  rows: Record<string, unknown>[],
  limit = 500,
): DashboardMapPoint[] {
  const points: DashboardMapPoint[] = [];
  for (let index = 0; index < rows.length && points.length < limit; index += 1) {
    const row = rows[index];
    const lat = asNumber(row.lat ?? row.latitude);
    const lng = asNumber(row.lng ?? row.lon ?? row.longitude);
    if (lat === null || lng === null) continue;

    const name = getText(row.name ?? row.label, `Facility ${index + 1}`);
    const type = getText(row.type, "Facility");
    const county = getText(row.county, "");
    points.push({
      id: getText(row.id, `${index}-${lat}-${lng}`),
      name,
      type,
      county,
      lat,
      lng,
      properties: {
        ...row,
        name,
        type,
        county,
        lat,
        lng,
      },
    });
  }
  return points;
}

export function countMapPointsByType(points: DashboardMapPoint[]): Array<[string, number]> {
  const counts = new Map<string, number>();
  for (const point of points) counts.set(point.type, (counts.get(point.type) ?? 0) + 1);
  return Array.from(counts.entries()).sort((a, b) => b[1] - a[1]);
}
