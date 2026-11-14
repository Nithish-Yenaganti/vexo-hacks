import { Band } from '/vendor/vexo-open/src/index.js';
import { alignBandClock, matchMotion } from './match.js';
import { byId, formatTime, request } from './shared.js';

const video = byId('video');
const connect = byId('connect');
const status = byId('status');
const resetButton = byId('reset');
const testButton = byId('test-transfer');
let band;
let phoneReady = false;
let pending = false;
let handedOff = false;
let outcome = '';
let wrist = [];
let phone = [];
let after = 0;
let lastWrist = 0;
let setupUrl = '';
let bestScore = 0;
const simulation = new URLSearchParams(location.search).has('sim');
if (simulation) connect.textContent = 'Connect simulator';

function describe() {
  byId('phone-status').textContent = phoneReady ? 'Receiving motion' : 'Waiting for phone motion';
  if (outcome) status.textContent = outcome;
  else if (band && phoneReady) status.textContent = 'Ready. Play the video, then pick up and twist your phone.';
  else if (band) status.textContent = 'Open the receiver link on your phone and enable motion.';
  else status.textContent = 'Pair the band and enable motion on your phone.';
}

connect.addEventListener('click', async () => {
  connect.disabled = true;
  byId('band-status').textContent = 'Connecting…';
  try {
    band = await Band.connect(simulation ? 42 : null, { transport: simulation ? 'sim' : 'ble' });
    band.on('disconnect', () => {
      band = null;
      wrist = [];
      lastWrist = 0;
      connect.disabled = false;
      connect.textContent = simulation ? 'Connect simulator' : 'Pair band';
      byId('band-status').textContent = 'Disconnected. Double-tap the band and pair again.';
      describe();
    });
    band.on('motion', sample => {
      const time = Number.isFinite(sample.time) ? sample.time : Date.now();
      const speed = Math.hypot(sample.gx, sample.gy, sample.gz);
      if (!Number.isFinite(speed)) return;
      if (wrist.length && time <= wrist.at(-1)[0]) return;
      lastWrist = Date.now();
      wrist.push([time, speed, lastWrist]);
      while (wrist.length && wrist[0][0] < time - 3000) wrist.shift();
    });
    await band.configure({ motion: 50, sensors: 'both', audio: false, micLevel: false });
    connect.textContent = 'Paired';
    byId('band-status').textContent = band.name + ' · live motion';
    describe();
  } catch (error) {
    await band?.disconnect().catch(() => {});
    band = null;
    connect.disabled = false;
    byId('band-status').textContent = window.isSecureContext && !navigator.bluetooth && !simulation
      ? 'Open this page in Chrome or Edge for Bluetooth.'
      : error.message;
    describe();
  }
});

async function handoff(score) {
  pending = true;
  resetButton.disabled = false;
  const time = video.currentTime;
  video.pause();
  video.controls = false;
  outcome = score === undefined ? 'Testing phone playback…' : 'Motion matched. Sending playback to your phone…';
  describe();
  try {
    const { transfer } = await request('/api/host/transfer', { data: { time } });
    if (transfer.status !== 'pending') throw new Error('Reset the previous handoff and try again.');
    if (score !== undefined) byId('score').textContent = score.toFixed(2);
  } catch (error) {
    pending = false;
    video.controls = true;
    outcome = error.message;
    await video.play().catch(() => {});
    describe();
  }
}

async function poll() {
  try {
    const state = await request('/api/host/state?after=' + after);
    phoneReady = state.phoneReady;
    for (const batch of state.batches) {
      after = batch.id;
      phone.push(...batch.samples);
    }
    const newestAllowed = Date.now() + 300;
    phone = phone.filter(([time]) => time >= Date.now() - 3200 && time <= newestAllowed).sort((a, b) => a[0] - b[0]);
    if (pending && state.transfer?.status === 'playing') {
      pending = false;
      handedOff = true;
      outcome = 'Handoff complete. The phone picked up where the laptop paused.';
      byId('playback').textContent = 'Sent at ' + formatTime(state.transfer.time);
      const linkedBand = band;
      if (linkedBand) {
        void linkedBand.setLed('#9dff54').then(() => {
          setTimeout(() => { if (band === linkedBand) void linkedBand.ledOff().catch(() => {}); }, 850);
        }).catch(() => {});
      }
    } else if (pending && state.transfer?.status === 'blocked') {
      outcome = 'Tap Play on the phone to finish the handoff.';
    } else if (pending && (state.transfer?.status === 'failed' || !phoneReady)) {
      outcome = 'Phone motion disconnected. Reset to replay on the laptop.';
    }
    testButton.disabled = !phoneReady || pending || handedOff;
    const bandReceiving = Boolean(band) && Date.now() - lastWrist < 700;
    byId('motion-inputs').textContent = (bandReceiving ? 'Band live' : 'Band waiting') + ' · ' +
      (phoneReady ? 'Phone live' : 'Phone waiting');
    if (bandReceiving && phoneReady && !pending && !handedOff) {
      const score = matchMotion(alignBandClock(wrist), phone);
      bestScore = Math.max(bestScore, score);
      byId('score').textContent = 'Best ' + bestScore.toFixed(2) + ' / 0.84';
      if (score >= 0.84 && !video.paused && !video.ended) await handoff(score);
    }
    describe();
  } catch (error) {
    status.textContent = 'Laptop server unavailable. ' + error.message;
  } finally {
    setTimeout(poll, 120);
  }
}

testButton.addEventListener('click', () => {
  if (phoneReady && !pending && !handedOff) void handoff();
});

resetButton.addEventListener('click', async () => {
  try {
    await request('/api/host/reset', { data: {} });
    pending = false;
    handedOff = false;
    outcome = '';
    wrist = [];
    phone = [];
    bestScore = 0;
    resetButton.disabled = true;
    video.controls = true;
    video.currentTime = 0;
    byId('score').textContent = 'Waiting';
    byId('playback').textContent = 'Ready to play';
    describe();
  } catch (error) {
    status.textContent = error.message;
  }
});

video.addEventListener('playing', () => {
  bestScore = 0;
  byId('playback').textContent = 'Playing on laptop';
});
video.addEventListener('pause', () => { if (!handedOff) byId('playback').textContent = 'Paused at ' + formatTime(video.currentTime); });
byId('copy').addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText(setupUrl);
    byId('copy').textContent = 'Copied';
  } catch {
    status.textContent = 'Copy the receiver address shown below.';
  }
});
async function updatePhoneLink() {
  try {
    const config = await request('/api/host/config');
    if (config.setupUrl === setupUrl) return;
    setupUrl = config.setupUrl;
    byId('setup-link').href = setupUrl;
    byId('setup-link').textContent = setupUrl;
    byId('phone-link').href = config.phoneUrl;
    byId('phone-link').textContent = config.phoneUrl ? 'Open receiver directly · HTTPS' : '';
    byId('copy').textContent = 'Copy setup link';
    byId('copy').disabled = !setupUrl;
  } catch (error) {
    status.textContent = error.message;
  }
}
updatePhoneLink();
setInterval(updatePhoneLink, 1500);
poll();
