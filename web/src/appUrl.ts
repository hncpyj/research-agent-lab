/**
 * Where the real application lives.
 *
 * This site is the public one: what ResearchAgentLab is, what it costs, and
 * where the source is. The application itself is a different thing on a
 * different machine -- it runs research for hours, holds open websockets and
 * writes to a disk -- so it is not part of this build and is linked to instead.
 *
 * Set VITE_APP_URL at build time. The default is the local server, so running
 * this site on a laptop points at the copy running on that laptop.
 */
export const APP_URL: string =
  (import.meta.env.VITE_APP_URL as string | undefined) || 'http://localhost:8000';

/** A path inside the application, as an absolute URL. */
export function appLink(path = ''): string {
  return APP_URL.replace(/\/$/, '') + path;
}
