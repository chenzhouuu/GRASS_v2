const rawApiBase = process.env.NEXT_PUBLIC_API_URL?.trim();

// If NEXT_PUBLIC_API_URL is unset, use relative paths and rely on Next rewrites.
const apiBase = rawApiBase ? rawApiBase.replace(/\/+$/, "") : "";

export function apiUrl(path: string): string {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${apiBase}${normalizedPath}`;
}
