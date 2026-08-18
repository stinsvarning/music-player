export function textOf(value) {
  if (value == null) {
    return "";
  }
  if (typeof value === "string" || typeof value === "number") {
    return String(value);
  }
  if (typeof value.text === "string" && value.text) {
    return value.text;
  }
  if (typeof value.name === "string" && value.name) {
    return value.name;
  }
  if (Array.isArray(value.runs)) {
    return value.runs.map((run) => (typeof run === "string" ? run : run?.text || "")).join("");
  }
  if (typeof value.toString === "function") {
    const printed = value.toString();
    if (printed && printed !== "[object Object]") {
      return printed;
    }
  }
  return "";
}

export function playlistEditId(id) {
  return String(id || "").replace(/^VL/, "");
}
