import assert from "node:assert/strict";
import { test } from "node:test";
import { parseLyrics } from "../src/lyrics.js";
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
  assert.deepEqual(out.lines, [{ text: "Line one" }, { text: "Line two" }]);
  assert.equal(Object.hasOwn(out.lines[0], "start"), false);
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

test("Youtube.lyrics keeps the lyric sheet and does not fetch captions", async () => {
  let infoCalls = 0;
  const yt = new Youtube();
  yt.loggedIn = true;
  yt.yt = {
    music: {
      getLyrics: async () => ({
        description: { runs: [{ text: "Official line" }] },
        footer: { text: "Musixmatch" },
      }),
      getInfo: async () => {
        infoCalls += 1;
        return {
          captions: {
            caption_tracks: [{ base_url: "https://example.invalid/captions" }],
          },
        };
      },
    },
  };
  const out = await yt.lyrics("abc");
  assert.equal(infoCalls, 0);
  assert.equal(out.found, true);
  assert.equal(out.text, "Official line");
  assert.equal(out.footer, "Musixmatch");
  assert.deepEqual(out.lines, [{ text: "Official line" }]);
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
