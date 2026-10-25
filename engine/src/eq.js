export const BANDS_HZ = [60, 170, 310, 600, 1000, 3000, 6000, 12000, 14000, 16000];

export function logSpacedHz(low, high, count) {
  const n = Math.max(1, count | 0);
  const start = Math.log(Math.max(1, low));
  const end = Math.log(Math.max(low + 1, high));
  const out = [];
  for (let i = 0; i < n; i += 1) {
    const t = n === 1 ? 0 : i / (n - 1);
    out.push(Math.round(Math.exp(start + (end - start) * t)));
  }
  return out;
}

// Visualizer taps only. The equalizer stays on BANDS_HZ.
export const VIS_BANDS_HZ = logSpacedHz(40, 16000, 10);

export const PRESETS = {
  Flat: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
  Warm: [2, 2, 1, 0, 0, 0, 0, 1, 1, 1],
  Vocal: [0, -2, -2, 0, 2, 3, 1, 0, 0, 0],
  Bass: [4, 3, 1, 0, 0, 0, 0, 0, 0, 0],
  Night: [1, 0, 0, 0, 0, -1, -2, -3, -2, -2],
};

export function preampFor(gains) {
  const peak = Math.max(0, ...(Array.isArray(gains) ? gains : []).map((g) => Number(g) || 0));
  return peak > 0 ? -peak : 0;
}

// The window reads one value per band every 80 ms (BAND_INTERVAL), but mpv hands the
// filters ~20 ms frames, so three of every four astats results were never read.
// Each tap still filters every sample (the bandpass keeps its state), then only
// every fourth frame is measured: the same per-frame RMS values, a quarter of the work.
export const VIS_TAP_EVERY = 4;
const VIS_TAP_SELECT = `not(mod(n\\,${VIS_TAP_EVERY}))`;
// Only the overall RMS is read; astats skips the other measures' output and metadata.
const VIS_TAP_STATS = "metadata=1:reset=1:length=0.08:measure_perchannel=none:measure_overall=RMS_level";

export function lavfiEqualizer(gains, metaDir = "") {
  const stages = [];
  const pre = preampFor(gains);
  if (pre < 0) {
    stages.push(`volume=${pre}dB`);
  }
  for (let i = 0; i < BANDS_HZ.length; i += 1) {
    const g = Number(gains[i] ?? 0);
    // A 0 dB band is a no-op biquad; skipping it saves ten filters on the Flat preset.
    if (g) {
      stages.push(`equalizer=f=${BANDS_HZ[i]}:t=q:w=1.2:g=${g}`);
    }
  }
  const eq = stages.length ? stages.join(",") : "anull";
  if (!metaDir) {
    return `lavfi=[${eq}]`;
  }
  const taps = VIS_BANDS_HZ.map((_, i) => `[s${i}]`).join("");
  const splits = VIS_BANDS_HZ.map((hz, i) => {
    const dest = escapeLavfiPath(spectrumBandFile(metaDir, i));
    return (
      `[s${i}]bandpass=f=${hz}:width_type=q:w=1.2,` +
      `aselect=${VIS_TAP_SELECT},` +
      `astats=${VIS_TAP_STATS},` +
      `ametadata=mode=print:file='${dest}':key=lavfi.astats.Overall.RMS_level:direct=1,` +
      `anullsink`
    );
  }).join(";");
  return `lavfi=[asplit=2[main][spec];[spec]asplit=${VIS_BANDS_HZ.length}${taps};${splits};[main]${eq}]`;
}

export function spectrumBandFile(metaDir, index) {
  return `${String(metaDir).replace(/\/$/, "")}/${index}`;
}

function escapeLavfiPath(filePath) {
  return String(filePath).replaceAll("\\", "/").replaceAll(":", "\\:").replaceAll("'", "\\'");
}

export function dbToUnit(db) {
  if (!Number.isFinite(db)) {
    return 0;
  }
  return Math.max(0, Math.min(1, (db + 70) / 70));
}

export function flattenAfMetadata(meta) {
  if (!meta || typeof meta !== "object") {
    return {};
  }
  const out = { ...meta };
  for (const [key, value] of Object.entries(meta)) {
    if (value && typeof value === "object" && !Array.isArray(value)) {
      for (const [inner, innerVal] of Object.entries(value)) {
        out[inner] = innerVal;
        out[`${key}.${inner}`] = innerVal;
      }
    }
  }
  return out;
}

export function parseAmetadataLog(text) {
  const last = {};
  for (const line of String(text || "").split("\n")) {
    const idx = line.indexOf("=");
    if (idx < 0) {
      continue;
    }
    const key = line.slice(0, idx).trim();
    if (!key.includes("astats")) {
      continue;
    }
    last[key] = line.slice(idx + 1).trim();
  }
  return last;
}

export function bandsFromMetadata(meta) {
  const src = flattenAfMetadata(meta);
  const bands = [];
  for (let i = 1; i <= 10; i += 1) {
    const raw = src[`lavfi.astats.${i}.RMS_level`] ?? src[`lavfi.astats.Overall.RMS_level`];
    bands.push(dbToUnit(Number(raw)));
  }
  return bands;
}
