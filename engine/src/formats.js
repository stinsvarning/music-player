export function pickAudioFormat(formats) {
  if (!Array.isArray(formats) || formats.length === 0) {
    return null;
  }
  const audioOnly = formats.filter((f) => f && f.has_audio && !f.has_video);
  const pool = audioOnly.length ? audioOnly : formats.filter((f) => f && f.has_audio);
  if (!pool.length) {
    return null;
  }
  const m4a = pool.find((f) => f.itag === 140);
  if (m4a) {
    return m4a;
  }
  return [...pool].sort((a, b) => (b.bitrate || 0) - (a.bitrate || 0))[0];
}
