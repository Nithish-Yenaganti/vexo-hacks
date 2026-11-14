import { byId, request } from './shared.js';

if (!location.hash) {
  byId('status').textContent = 'Open the full setup link shown on the laptop.';
} else {
  try {
    const { httpsPort } = await request('/api/receiver-port');
    byId('receiver-link').href = `https://${location.hostname}:${httpsPort}/phone${location.hash}`;
  } catch (error) {
    byId('status').textContent = error.message;
  }
}
