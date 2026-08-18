export function parseRequest(line) {
  const text = String(line || "").trim();
  if (!text) {
    return { ok: false, error: "empty request" };
  }
  let raw;
  try {
    raw = JSON.parse(text);
  } catch {
    return { ok: false, error: "invalid JSON" };
  }
  if (!raw || typeof raw.cmd !== "string" || !raw.cmd) {
    return { ok: false, error: "cmd is required" };
  }
  return { ok: true, request: raw };
}

export function ok(extra = {}) {
  return { ok: true, ...extra };
}

export function fail(error) {
  return { ok: false, error: String(error || "error") };
}

export function encode(obj) {
  return `${JSON.stringify(obj)}\n`;
}

export function attachId(req, resp) {
  if (!resp || typeof resp !== "object" || req?.id == null) {
    return resp;
  }
  return { ...resp, id: req.id };
}
