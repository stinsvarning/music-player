import assert from "node:assert/strict";
import { test } from "node:test";
import { currentLyricIndex, parseLyrics, parseVtt } from "../src/lyrics.js";
import { Youtube } from "../src/youtube.js";
import { dispatch } from "../src/server.js";

test("parseLyrics reads a description shelf", () => {
  const out = parseLyrics({
    description: { runs: [{ text: "Line one\n" }, { text: "Line two" }] },
    footer: { text: "Source" },
  });
  assert.equal(out.found, true);
  assert.equal(out.text, "Line one\nLine two");
  assert.equal(out.footer, "Source");
});

test("parseLyrics treats missing shelf as not found", () => {
  assert.deepEqual(parseLyrics(null), { text: "", footer: "", found: false, lines: [] });
  assert.deepEqual(parseLyrics({ description: { text: "  " } }), { text: "", footer: "", found: false, lines: [] });
});

test("Youtube.lyrics returns empty when getLyrics throws", async () => {
  const yt = new Youtube();
  yt.loggedIn = true;
  yt.yt = {
    music: {
      getLyrics: async () => {
        throw new Error("Could not find target tab.");
      },
    },
  };
  const out = await yt.lyrics("abc");
  assert.equal(out.found, false);
  assert.equal(out.text, "");
});

test("dispatch lyrics uses the current track when id is omitted", async () => {
  const player = { queue: [{ id: "vid1", title: "A" }], index: 0 };
  const youtube = {
    lyrics: async (id) => ({ text: `words for ${id}`, footer: "", found: true }),
  };
  const resp = await dispatch(player, youtube, { cmd: "lyrics" });
  assert.equal(resp.ok, true);
  assert.equal(resp.id, "vid1");
  assert.equal(resp.found, true);
  assert.equal(resp.text, "words for vid1");
});

test("dispatch lyrics is empty when the queue has no track", async () => {
  const resp = await dispatch({ queue: [], index: -1 }, {}, { cmd: "lyrics" });
  assert.equal(resp.ok, true);
  assert.equal(resp.found, false);
  assert.equal(resp.text, "");
});

test("parseVtt extracts timed lines", () => {
  const lines = parseVtt(`WEBVTT

00:00:01.000 --> 00:00:03.500
Hello there

00:00:03.500 --> 00:00:06.000
Second line
`);
  assert.equal(lines.length, 2);
  assert.equal(lines[0].text, "Hello there");
  assert.equal(lines[0].start, 1);
  assert.equal(lines[1].start, 3.5);
});

test("currentLyricIndex uses timed starts when present", () => {
  const lines = [
    { text: "a", start: 0 },
    { text: "b", start: 10 },
    { text: "c", start: 20 },
  ];
  assert.equal(currentLyricIndex(lines, 0, 30), 0);
  assert.equal(currentLyricIndex(lines, 10.2, 30), 1);
  assert.equal(currentLyricIndex(lines, 25, 30), 2);
});

test("currentLyricIndex unsynced waits through the intro", () => {
  const lines = [{ text: "a" }, { text: "b" }, { text: "c" }, { text: "d" }];
  assert.equal(currentLyricIndex(lines, 2, 180), -1);
});

test("currentLyricIndex unsynced skips blank lines", () => {
  const lines = [{ text: "a" }, { text: "" }, { text: "b" }, { text: "c" }];
  assert.equal(currentLyricIndex(lines, 90, 180), 2);
});

test("currentLyricIndex unsynced stays on the last sung line in the outro", () => {
  const lines = [{ text: "a" }, { text: "b" }, { text: "c" }];
  assert.equal(currentLyricIndex(lines, 175, 180), 2);
});
