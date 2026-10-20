export const APP_URL = '';

export function hostedAppUrl(path = '/app') {
  return `${APP_URL}${path.startsWith('/') ? path : `/${path}`}`;
}
