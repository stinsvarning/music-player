export const BANDS_HZ = [60, 170, 310, 600, 1000, 3000, 6000, 12000, 14000, 16000];

export const PRESETS = {
  Flat: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
  Rock: [5, 4, 2, -1, -2, 2, 4, 5, 5, 5],
  Jazz: [4, 3, 1, 2, -2, -2, 0, 1, 2, 3],
  Pop: [-1, 2, 4, 4, 1, -1, -2, -2, -1, -1],
  "Bass Boost": [8, 6, 4, 2, 0, 0, 0, 0, 0, 0],
};

export function lavfiEqualizer(gains) {
  const bands = BANDS_HZ.map((hz, i) => {
    const g = Number(gains[i] ?? 0);
    return `equalizer=f=${hz}:t=q:w=1.2:g=${g}`;
  });
  return `lavfi=[${bands.join(",")}]`;
}
