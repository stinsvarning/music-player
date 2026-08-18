import assert from "node:assert/strict";
import { test } from "node:test";
import { playlistEditId, textOf } from "../src/text.js";

test("textOf flattens youtubei Text-like objects", () => {
  assert.equal(textOf("Liked Music"), "Liked Music");
  assert.equal(textOf({ text: "Liked Music", runs: [{ text: "Liked" }, { text: " Music" }] }), "Liked Music");
  assert.equal(textOf({ runs: [{ text: "Chill" }, { text: " Mix" }] }), "Chill Mix");
  assert.equal(textOf({ name: "Weezer" }), "Weezer");
  assert.equal(textOf(null), "");
});

test("playlistEditId strips the VL prefix used by YouTube Music", () => {
  assert.equal(playlistEditId("VLPL123"), "PL123");
  assert.equal(playlistEditId("LM"), "LM");
  assert.equal(playlistEditId("VLLM"), "LM");
});

