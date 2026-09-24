const fallbackAppUrl = 'https://researchagentlab-backend-production.up.railway.app';

export const APP_URL = (import.meta.env.VITE_APP_URL || fallbackAppUrl).replace(/\/$/, '');

export function hostedAppUrl(path = '/app') {
  return `${APP_URL}${path.startsWith('/') ? path : `/${path}`}`;
}
