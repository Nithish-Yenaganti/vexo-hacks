import { byId, formatTime, request } from './shared.js';

const video = byId('video');
const enable = byId('enable');
const sound = byId('sound');
const status = byId('status');
const playback = byId('playback');
const motionState = byId('motion-state');
const token = location.hash.slice(1);
const id = globalThis.crypto?.randomUUID?.() || String(Math.random());
const headers = { 'x-pair-token': token, 'x-phone-id': id };

let samples = [];
let offset = 0;
let started = false;
let lastUpload = 0;
let lastSensorEvent = 0;
let polling = false;
let pollTimer;
let currentTransfer;
let resetVersion;
let applied = false;

function onMotion(event) {
  lastSensorEvent = Date.now();
  const rate = event.rotationRate;
  if (!rate || ![rate.alpha, rate.beta, rate.gamma].every(Number.isFinite)) return;
  const now = Date.now();
  const time = event.timeStamp > 0 && event.timeStamp <= performance.now()
    ? performance.timeOrigin + event.timeStamp : now;
  samples.push([time + offset, Math.hypot(rate.alpha, rate.beta, rate.gamma)]);
  if (samples.length > 60) samples.shift();
}

function describeMotion(message, detail) {
  if (motionState.textContent !== message) motionState.textContent = message;
  if (detail && status.textContent !== detail) status.textContent = detail;
}

async function startPlayback() {
  let timer;
  try {
    await Promise.race([
      video.play(),
      new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('Playback timed out')), 2500); }),
    ]);
  } finally {
    clearTimeout(timer);
  }
}

async function playTransfer(transfer) {
  if (!transfer || applied) return;
  try {
    video.currentTime = transfer.time;
    try {
      await startPlayback();
    } catch (error) {
      if (video.muted) throw error;
      video.muted = true;
      await startPlayback();
    }
  } catch {
    video.pause();
    await request('/api/phone/ack', { headers, data: { id: transfer.id, playing: false } });
    enable.hidden = false;
    enable.disabled = false;
    enable.textContent = 'Play on phone';
    status.textContent = 'Tap to resume the video at ' + formatTime(transfer.time) + '.';
    return;
  }
  if (currentTransfer?.id !== transfer.id) {
    video.pause();
    return;
  }
  await request('/api/phone/ack', { headers, data: { id: transfer.id, playing: true } });
  applied = true;
  enable.hidden = true;
  video.controls = true;
  playback.textContent = 'Received at ' + formatTime(transfer.time);
  sound.hidden = !video.muted;
  status.textContent = 'The video moved from the laptop to this phone.';
}

async function poll() {
  if (!started || polling) return;
  clearTimeout(pollTimer);
  polling = true;
  try {
    const batch = samples.splice(0);
    const state = batch.length
      ? await request('/api/phone/samples', { headers, data: batch })
      : await request('/api/phone/state', { headers });
    if (!started) return;
    if (batch.length) lastUpload = Date.now();
    if (resetVersion !== state.reset) {
      resetVersion = state.reset;
      currentTransfer = undefined;
      applied = false;
      video.pause();
      video.controls = false;
      sound.hidden = true;
      playback.textContent = 'Standing by';
    }
    if (state.transfer?.status === 'pending' && state.transfer.id !== currentTransfer?.id) {
      currentTransfer = state.transfer;
      await playTransfer(currentTransfer);
    }
    if (applied) return;
    if (Date.now() - lastUpload < 1800) {
      describeMotion('Motion live', currentTransfer ? undefined :
        'The laptop is receiving motion. Keep Safari open here and start the video on the laptop.');
    } else if (Date.now() - lastSensorEvent < 2200) {
      describeMotion('No gyroscope data', 'Move the phone. If this stays here, tap Retry motion.');
    } else {
      describeMotion('Waiting for Safari motion', 'Keep this tab on screen and twist the phone. Tap Retry motion if it stays here.');
    }
  } catch (error) {
    describeMotion('Connection interrupted', error.message || 'Keep both devices on the same Wi-Fi.');
    if (/session was replaced|fresh pairing link/.test(error.message)) {
      started = false;
      window.removeEventListener('devicemotion', onMotion);
      enable.hidden = false;
      enable.textContent = 'Enable motion';
    }
  } finally {
    polling = false;
    if (started) pollTimer = setTimeout(poll, 100);
  }
}

document.addEventListener('visibilitychange', () => {
  if (document.hidden) {
    samples = [];
    lastUpload = 0;
  } else if (started) {
    void poll();
  }
});

sound.addEventListener('click', async () => {
  video.muted = false;
  try {
    await startPlayback();
    sound.hidden = true;
  } catch (error) {
    status.textContent = error.message;
  }
});

enable.addEventListener('click', async () => {
  if (started && currentTransfer) {
    try { await playTransfer(currentTransfer); } catch (error) { status.textContent = error.message; }
    return;
  }
  const wasStarted = started;
  started = false;
  enable.disabled = true;
  describeMotion('Requesting motion access', 'Tap Allow if Safari asks.');
  try {
    if (!token) throw new Error('Open the complete receiver link from the laptop.');
    if (!isSecureContext || !window.DeviceMotionEvent) throw new Error('Open the trusted HTTPS receiver link on your phone.');
    // Start permission and playback unlock in the original click.
    const motionPermission = typeof DeviceMotionEvent.requestPermission === 'function'
      ? DeviceMotionEvent.requestPermission() : Promise.resolve('granted');
    if (!wasStarted) video.muted = false;
    const prime = wasStarted ? Promise.resolve() : startPlayback().then(() => { video.pause(); }).catch(() => {});
    if (await motionPermission !== 'granted') throw new Error('Motion access was declined. Reload in Safari to try again.');
    await prime;
    while (polling) await new Promise(resolve => setTimeout(resolve, 50));
    let bestRoundTrip = Infinity;
    for (let attempt = 0; attempt < 4; attempt++) {
      const sent = Date.now();
      const state = await request(attempt === 0 ? '/api/phone/ready' : '/api/phone/state', {
        headers, data: attempt === 0 ? {} : undefined,
      });
      const arrived = Date.now();
      if (arrived - sent < bestRoundTrip) {
        bestRoundTrip = arrived - sent;
        offset = state.now - (sent + arrived) / 2;
      }
      resetVersion = state.reset;
    }
    window.addEventListener('devicemotion', onMotion);
    samples = [];
    lastUpload = 0;
    lastSensorEvent = 0;
    started = true;
    enable.hidden = false;
    enable.textContent = 'Retry motion';
    poll();
  } catch (error) {
    describeMotion('Motion is off', error.message);
  } finally {
    enable.disabled = false;
  }
});
