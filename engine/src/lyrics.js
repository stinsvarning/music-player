import { textOf } from "./text.js";

export function lyricLinesFromText(text) {
  return String(text || "")
    .replace(/\r\n/g, "\n")
    .split("\n")
    .map((line) => ({ text: line, start: null }));
}

export function parseLyrics(shelf) {
  if (!shelf) {
    return { text: "", footer: "", found: false, lines: [] };
  }
  const text = textOf(shelf.description).trim();
  const footer = textOf(shelf.footer).trim();
  if (!text) {
    return { text: "", footer, found: false, lines: [] };
  }
  return { text, footer, found: true, lines: lyricLinesFromText(text) };
}

export function parseVtt(raw) {
  const text = String(raw || "").replace(/^\uFEFF/, "");
  const lines = [];
  const chunks = text.split(/\n\n+/);
  for (const chunk of chunks) {
    const rows = chunk.split("\n").map((r) => r.trim()).filter(Boolean);
    if (!rows.length || /^WEBVTT/i.test(rows[0])) {
      continue;
    }
    const stamp = rows.find((r) => r.includes("-->"));
    if (!stamp) {
      continue;
    }
    const start = parseVttTime(stamp.split("-->")[0]);
    const body = rows
      .filter((r) => r !== stamp && !/^\d+$/.test(r))
      .join("\n")
      .replace(/<[^>]+>/g, "")
      .trim();
    if (!body || start == null) {
      continue;
    }
    lines.push({ text: body, start });
  }
  return lines;
}

export function parseVttTime(raw) {
  const m = String(raw || "")
    .trim()
    .match(/(?:(\d+):)?(\d{2}):(\d{2})[.](\d{1,3})/);
  if (!m) {
    return null;
  }
  const hours = Number(m[1] || 0);
  const minutes = Number(m[2]);
  const seconds = Number(m[3]);
  const frac = Number((m[4] || "0").padEnd(3, "0"));
  return hours * 3600 + minutes * 60 + seconds + frac / 1000;
}

export function currentLyricIndex(lines, position, duration) {
  if (!Array.isArray(lines) || !lines.length) {
    return -1;
  }
  const pos = Number(position) || 0;
  const timed = lines.some((row) => row && row.start != null);
  if (timed) {
    let idx = 0;
    for (let i = 0; i < lines.length; i += 1) {
      const start = lines[i]?.start;
      if (start != null && pos >= start) {
        idx = i;
      }
    }
    return idx;
  }
  const dur = Number(duration) || 0;
  if (dur <= 0) {
    return 0;
  }
  const sung = [];
  for (let i = 0; i < lines.length; i += 1) {
    if (String(lines[i]?.text ?? "").trim()) {
      sung.push(i);
    }
  }
  if (!sung.length) {
    return -1;
  }
  const start = Math.min(12, dur * 0.15);
  const end = Math.max(start, dur - Math.min(10, dur * 0.12));
  if (pos < start) {
    return -1;
  }
  if (pos >= end) {
    return sung[sung.length - 1];
  }
  const span = end - start;
  if (span <= 0) {
    return sung[0];
  }
  const slot = Math.min(
    sung.length - 1,
    Math.max(0, Math.floor(((pos - start) / span) * sung.length)),
  );
  return sung[slot];
}

