import assert from "node:assert/strict";
import { test } from "node:test";
import { Youtube } from "../src/youtube.js";

function fakeSession(getInfo) {
  const yt = new Youtube();
  yt.loggedIn = true;
  yt.yt = {
    music: { getInfo },
    session: {
      player: {},
      po_token: "old",
      context: { client: { visitorData: "" } },
    },
  };
  return yt;
}

function audioFormat(url) {
  return {
    has_audio: true,
    has_video: false,
    itag: 140,
    audio_quality: "AUDIO_QUALITY_MEDIUM",
    average_bitrate: 128000,
    decipher: async () => url,
  };
}

test("streamUrl retries after empty formats then returns audio", async () => {
  let calls = 0;
  const yt = fakeSession(async () => {
    calls += 1;
    if (calls === 1) {
      return { streaming_data: { adaptive_formats: [], formats: [] } };
    }
    return { streaming_data: { adaptive_formats: [audioFormat("https://fresh.example/a")], formats: [] } };
  });
  assert.equal(await yt.streamUrl("abc"), "https://fresh.example/a");
  assert.equal(calls, 2);
});

test("streamUrl retries when getInfo throws once", async () => {
  let calls = 0;
  const yt = fakeSession(async () => {
    calls += 1;
    if (calls === 1) {
      throw new Error("bot check");
    }
    return { streaming_data: { adaptive_formats: [audioFormat("https://fresh.example/b")], formats: [] } };
  });
  assert.equal(await yt.streamUrl("abc"), "https://fresh.example/b");
  assert.equal(calls, 2);
});

test("streamUrl recreates the Innertube session after two empty format lists", async () => {
  let calls = 0;
  const yt = fakeSession(async () => {
    calls += 1;
    return { streaming_data: { adaptive_formats: [], formats: [] } };
  });
  yt._cookie = "SAPISID=1";
  yt.connect = async () => {
    yt.yt.music.getInfo = async () => ({
      streaming_data: { adaptive_formats: [audioFormat("https://fresh.example/c")], formats: [] },
    });
  };
  assert.equal(await yt.streamUrl("abc"), "https://fresh.example/c");
  assert.equal(calls, 2);
});

test("streamUrl fails after retries still have no audio", async () => {
  let calls = 0;
  const yt = fakeSession(async () => {
    calls += 1;
    return { streaming_data: { adaptive_formats: [], formats: [] } };
  });
  await assert.rejects(() => yt.streamUrl("abc"), /no audio format/);
  assert.equal(calls, 3);
});
