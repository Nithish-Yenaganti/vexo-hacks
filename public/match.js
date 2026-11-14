const step = 20;
const windowSize = 26;

function grid(samples, start) {
  let index = 0;
  return Array.from({ length: windowSize }, (_, i) => {
    const time = start + i * step;
    while (index + 1 < samples.length && samples[index + 1][0] < time) index++;
    const left = samples[index];
    const right = samples[index + 1];
    if (!left || !right || left[0] > time || right[0] <= left[0] || right[0] - left[0] > 90) return NaN;
    const weight = (time - left[0]) / (right[0] - left[0]);
    return left[1] + (right[1] - left[1]) * weight;
  });
}

function compare(a, b) {
  const pairs = a.map((value, i) => [value, b[i]]).filter(pair => pair.every(Number.isFinite));
  if (pairs.length < 21) return 0;
  const count = pairs.length;
  let sx = 0, sy = 0, sxx = 0, syy = 0, sxy = 0, active = 0;
  for (const [x, y] of pairs) {
    sx += x;
    sy += y;
    sxx += x * x;
    syy += y * y;
    sxy += x * y;
    if (x > 55 && y > 55) active++;
  }
  const xx = sxx - sx * sx / count;
  const yy = syy - sy * sy / count;
  const ratio = Math.sqrt(xx / yy);
  if (active < 6 || Math.min(xx, yy) < count * 20 ** 2 || ratio < 0.45 || ratio > 2.2) return 0;
  const correlation = (sxy - sx * sy / count) / Math.sqrt(xx * yy);
  const energySimilarity = 2 * sxy / (sxx + syy);
  return Math.max(0, Math.min(1, correlation * energySimilarity));
}

// Speed magnitude is independent of how the two sensors are oriented.
export function matchMotion(wrist, phone) {
  if (wrist.length < 15 || phone.length < 15) return 0;
  const end = Math.min(wrist.at(-1)[0], phone.at(-1)[0]);
  let score = 0;
  for (let back = 40; back <= 520; back += 60) {
    const start = end - back - (windowSize - 1) * step;
    const wristGrid = grid(wrist, start);
    for (let lag = -160; lag <= 160; lag += step) {
      score = Math.max(score, compare(wristGrid, grid(phone, start + lag)));
    }
  }
  return score;
}

// The band's oscillator can drift relative to the phone during a long session.
export function alignBandClock(samples) {
  if (!samples.length) return [];
  const offset = Math.min(...samples.map(([time, , arrival]) => arrival - time));
  return samples.map(([time, speed]) => [time + offset, speed]);
}
