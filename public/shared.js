export const byId = id => document.getElementById(id);

export async function request(path, { headers = {}, data } = {}) {
  const options = data === undefined ? { headers } : {
    method: 'POST',
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  };
  const response = await fetch(path, { ...options, cache: 'no-store', signal: AbortSignal.timeout(4000) });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Connection failed.');
  return result;
}

export function formatTime(seconds) {
  const whole = Math.floor(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`;
}
