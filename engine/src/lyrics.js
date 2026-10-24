import { textOf } from "./text.js";

export function lyricLinesFromText(text) {
  return String(text || "")
    .replace(/\r\n/g, "\n")
    .split("\n")
    .map((line) => ({ text: line }));
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
