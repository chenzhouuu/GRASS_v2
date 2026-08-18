/**
 * The single "watch handle" for the run currently being observed.
 *
 * Viewing is not owning: aborting a watch only closes this client's SSE
 * connection — the backend run continues (see DISCONNECT_STOPS_RUN in
 * src/api/chat.py). Stopping a run is a separate, explicit action
 * (stopActiveRun in lib/api.ts).
 */

let currentWatch: (() => void) | null = null;

/** Replace the active watch, closing the previous one (if any). */
export function setRunWatch(disconnect: (() => void) | null) {
  currentWatch?.();
  currentWatch = disconnect;
}

/** Stop watching. The run itself is NOT affected. */
export function stopRunWatch() {
  currentWatch?.();
  currentWatch = null;
}
