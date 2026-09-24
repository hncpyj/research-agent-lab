const fallbackAppUrl = 'https://app.researchagentlab.com';

export const APP_URL = (import.meta.env.VITE_APP_URL || fallbackAppUrl).replace(/\/$/, '');

export function hostedAppUrl(path = '/app') {
  return `${APP_URL}${path.startsWith('/') ? path : `/${path}`}`;
}
