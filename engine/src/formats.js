function qualityRank(format) {
  const label = String(format.audio_quality || "").toUpperCase();
  if (label.includes("HIGH")) return 3;
  if (label.includes("MEDIUM") || label.includes("NORMAL")) return 2;
  if (label.includes("LOW")) return 1;
  return 0;
}

function bitrateOf(format) {
  return Number(format.average_bitrate || format.bitrate || 0);
}

export function pickAudioFormat(formats) {
  if (!Array.isArray(formats) || formats.length === 0) {
    return null;
  }
  const audioOnly = formats.filter((f) => f && f.has_audio && !f.has_video);
  const pool = audioOnly.length ? audioOnly : formats.filter((f) => f && f.has_audio);
  if (!pool.length) {
    return null;
  }
  return [...pool].sort((a, b) => {
    const quality = qualityRank(b) - qualityRank(a);
    if (quality) return quality;
    return bitrateOf(b) - bitrateOf(a);
  })[0];
}
