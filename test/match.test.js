import assert from 'node:assert/strict';
import test from 'node:test';
import { alignBandClock, matchMotion } from '../public/match.js';

function trace(pulses, delay = 0, multiplier = 1) {
  return Array.from({ length: 100 }, (_, i) => {
    const time = i * 20;
    const speed = pulses.reduce((sum, [center, height, width]) =>
      sum + height * Math.exp(-(((time - center) / width) ** 2) / 2), 4);
    return [time + delay, speed * multiplier];
  });
}

const twist = [[1310, 210, 53], [1500, 130, 76]];
const wrist = trace(twist);

test('matches a shared twist despite timing and amplitude differences', () => {
  assert.ok(matchMotion(wrist, trace(twist, 82, 1.1)) > 0.9);
});

test('keeps playback on the laptop when only the phone is twisted', () => {
  assert.equal(matchMotion(trace([]), trace(twist)), 0);
});

test('rejects distinct movement during the same time window', () => {
  assert.ok(matchMotion(wrist, trace([[1320, 105, 210], [1690, 230, 65]])) < 0.84);
});

test('aligns a drifting band clock without treating Bluetooth packet delay as motion', () => {
  const delayedWrist = wrist.map(([time, speed], i) => [
    time - 650,
    speed,
    time + (i % 3 === 0 ? 0 : 30),
  ]);
  assert.ok(matchMotion(alignBandClock(delayedWrist), trace(twist)) > 0.9);
});
