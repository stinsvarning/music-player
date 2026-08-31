export const AUTH_REFRESH_MS = 15 * 60 * 1000;

export function looksLikeAuthError(err) {
  const msg = String(err?.message || err || "").toLowerCase();
  if (!msg) {
    return false;
  }
  if (msg.includes("login_required") || msg.includes("unauthenticated") || msg.includes("not logged in")) {
    return true;
  }
  if (msg.includes("status code 401") || msg.includes("error 401")) {
    return true;
  }
  return false;
}
