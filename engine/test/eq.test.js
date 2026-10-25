import assert from "node:assert/strict";
import { test } from "node:test";
import {
  BANDS_HZ,
  PRESETS,
  VIS_BANDS_HZ,
  bandsFromMetadata,
  dbToUnit,
  flattenAfMetadata,
  lavfiEqualizer,
  parseAmetadataLog,
  preampFor,
  VIS_TAP_EVERY,
} from "../src/eq.js";

test("equalizer graph is ten bands, skipping the ones at 0 dB", () => {
  assert.equal(BANDS_HZ.length, 10);
  assert.equal([...lavfiEqualizer([1, 1, 1, 1, 1, 1, 1, 1, 1, 1]).matchAll(/equalizer=/g)].length, 10);
  assert.equal([...lavfiEqualizer([0, 2, 0, -1, 0, 0, 0, 0, 0, 0]).matchAll(/equalizer=/g)].length, 2);
  assert.equal(lavfiEqualizer([0, 0, 0, 0, 0, 0, 0, 0, 0, 0]), "lavfi=[anull]");
});

test("YTM presets are modest and named for listening, not genre theater", () => {
  assert.deepEqual(Object.keys(PRESETS), ["Flat", "Warm", "Vocal", "Bass", "Night"]);
  assert.deepEqual(PRESETS.Flat, [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]);
  assert.ok(Math.max(...PRESETS.Bass) <= 4);
  assert.ok(PRESETS.Warm[0] > 0 && PRESETS.Warm[0] <= 2);
  assert.ok(PRESETS.Vocal[4] > 0 && PRESETS.Vocal[2] < 0);
  assert.ok(PRESETS.Night[6] < 0 && PRESETS.Night[7] < 0);
});

test("preamp cancels the peak boost so the sum is not above 0 dB", () => {
  for (const [name, bands] of Object.entries(PRESETS)) {
    const pre = preampFor(bands);
    assert.ok(pre <= 0, name);
    assert.ok(Math.max(0, ...bands) + pre <= 0, name);
  }
  assert.equal(preampFor([0, 0, 3, -2]), -3);
  assert.equal(preampFor([0, 0, 0, 0]), 0);
});

test("lavfi graph inserts a preamp before the equalizer when bands boost", () => {
  const graph = lavfiEqualizer([0, 4, 0, 0, 0, 0, 0, 0, 0, 0]);
  assert.match(graph, /volume=-4dB/);
  assert.match(graph, /equalizer=f=170:t=q:w=1.2:g=4/);
  assert.ok(graph.indexOf("volume=") < graph.indexOf("equalizer="));
});

test("lavfi graph keeps the equalizer and adds a spectrum tap", () => {
  const graph = lavfiEqualizer([3, 0, 0, 0, 0, 0, 0, 0, 0, 0], "/tmp/spectrum");
  assert.match(graph, /^lavfi=\[/);
  assert.match(graph, /equalizer=f=60/);
  assert.match(lavfiEqualizer(PRESETS.Flat, "/tmp/spectrum"), /\[main\]anull\]$/);
  assert.match(graph, /astats=metadata=1/);
  assert.match(graph, /anullsink/);
  assert.match(graph, /ametadata=mode=print:file='\/tmp\/spectrum\/0'/);
  assert.match(graph, new RegExp(`bandpass=f=${VIS_BANDS_HZ[0]}`));
  assert.doesNotMatch(graph, /bandpass=f=12000/);
});

test("spectrum taps filter every sample but only measure the frames the window reads", () => {
  const graph = lavfiEqualizer(PRESETS.Flat, "/tmp/spectrum");
  const taps = graph.split(";").filter((part) => part.includes("bandpass="));
  assert.equal(taps.length, VIS_BANDS_HZ.length);
  for (const tap of taps) {
    // bandpass first (it is stateful), then the frame pick, then the RMS-only stats
    assert.ok(tap.indexOf("bandpass=") < tap.indexOf("aselect="), tap);
    assert.ok(tap.indexOf("aselect=") < tap.indexOf("astats="), tap);
    assert.match(tap, new RegExp(`aselect=not\\(mod\\(n\\\\,${VIS_TAP_EVERY}\\)\\)`));
    assert.match(tap, /measure_perchannel=none:measure_overall=RMS_level/);
  }
  assert.equal(VIS_TAP_EVERY, 4); // 4 x ~20 ms mpv frames = the window's 80 ms poll
});

test("visualizer bands are log spaced and separate from the equalizer", () => {
  assert.equal(VIS_BANDS_HZ.length, 10);
  assert.equal(VIS_BANDS_HZ[0], 40);
  assert.equal(VIS_BANDS_HZ.at(-1), 16000);
  const visSpread = VIS_BANDS_HZ.at(-1) - VIS_BANDS_HZ.at(-3);
  const eqSpread = BANDS_HZ.at(-1) - BANDS_HZ.at(-3);
  assert.ok(visSpread > eqSpread);
  for (let i = 1; i < VIS_BANDS_HZ.length; i += 1) {
    assert.ok(VIS_BANDS_HZ[i] > VIS_BANDS_HZ[i - 1]);
  }
});

test("dbToUnit maps silence and peaks", () => {
  assert.equal(dbToUnit(Number.NEGATIVE_INFINITY), 0);
  assert.equal(dbToUnit(-120), 0);
  assert.ok(dbToUnit(-12) > 0.7);
  assert.equal(dbToUnit(0), 1);
});

test("bandsFromMetadata reads per-channel RMS", () => {
  const meta = {};
  for (let i = 1; i <= 10; i++) {
    meta[`lavfi.astats.${i}.RMS_level`] = i === 1 ? -6 : -80;
  }
  const bands = bandsFromMetadata(meta);
  assert.equal(bands.length, 10);
  assert.ok(bands[0] > 0.8);
  assert.ok(bands[1] < 0.2);
});

test("flattenAfMetadata unwraps nested lavfi maps", () => {
  const flat = flattenAfMetadata({
    lavfi: { "astats.1.RMS_level": -8 },
    "lavfi.astats.2.RMS_level": -9,
  });
  assert.equal(flat["lavfi.astats.2.RMS_level"], -9);
  assert.equal(flat["astats.1.RMS_level"], -8);
});

test("parseAmetadataLog keeps the latest astats values", () => {
  const meta = parseAmetadataLog(`
frame:0 pts:0
lavfi.astats.1.RMS_level=-40
lavfi.astats.2.RMS_level=-80
frame:1 pts:1
lavfi.astats.1.RMS_level=-6
lavfi.astats.2.RMS_level=-70
`);
  assert.equal(meta["lavfi.astats.1.RMS_level"], "-6");
  assert.ok(bandsFromMetadata(meta)[0] > 0.8);
});
