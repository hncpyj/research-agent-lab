/**
 * Where the real application lives.
 *
 * The public build deliberately does not link to the research application.
 * This helper remains for a future separately reviewed deployment only.
 *
 * A production build must never silently fall back to a visitor's localhost.
 */
const configuredAppUrl = (import.meta.env.VITE_APP_URL as string | undefined)?.trim();

if (import.meta.env.PROD && !configuredAppUrl) {
  throw new Error('VITE_APP_URL must be set before linking a production build to the research application.');
}

export const APP_URL: string = configuredAppUrl || 'http://localhost:8000';

/** A path inside the application, as an absolute URL. */
export function appLink(path = ''): string {
  return APP_URL.replace(/\/$/, '') + path;
}
