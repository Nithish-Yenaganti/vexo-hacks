import http from 'node:http';
import https from 'node:https';
import { execFileSync } from 'node:child_process';
import { randomBytes, randomUUID } from 'node:crypto';
import { createReadStream, existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { networkInterfaces } from 'node:os';
import { isIP } from 'node:net';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(fileURLToPath(import.meta.url));
const httpPort = Number(process.env.PORT || 8787);
const httpsPort = Number(process.env.HTTPS_PORT || 8443);
const requestedHost = process.env.PHONE_HOST;
if (requestedHost && !/^[a-zA-Z0-9.-]+$/.test(requestedHost)) throw new Error('PHONE_HOST must be an IPv4 address or hostname.');

function receiverHost() {
  const addresses = Object.values(networkInterfaces()).flat()
    .filter(entry => entry.family === 'IPv4' && !entry.internal)
    .map(entry => entry.address);
  return requestedHost || addresses.find(address => address.startsWith('172.20.10.')) || addresses[0];
}

const phoneToken = randomBytes(12).toString('hex');
const mime = { html: 'text/html', js: 'text/javascript', css: 'text/css', mp4: 'video/mp4', crt: 'application/x-x509-ca-cert' };

let phoneId = null;
let phoneSeen = 0;
let phoneBatches = [];
let nextBatch = 0;
let transfer = null;
let reset = 0;

function json(res, value, status = 200) {
  res.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
  res.end(JSON.stringify(value));
}

async function body(req) {
  let data = '';
  for await (const chunk of req) {
    data += chunk;
    if (data.length > 16000) throw new Error('Request too large');
  }
  return JSON.parse(data);
}

function sendFile(req, res, file) {
  if (!existsSync(file)) return json(res, { error: 'Not found' }, 404);
  const size = statSync(file).size;
  const type = mime[file.split('.').at(-1)] || 'application/octet-stream';
  const headers = { 'Content-Type': type, 'Cache-Control': type === 'video/mp4' ? 'private, max-age=3600' : 'no-store', 'Accept-Ranges': 'bytes' };
  const range = req.headers.range;
  if (range) {
    const parts = /^bytes=(\d+)-(\d*)$/.exec(range);
    const start = parts && Number(parts[1]);
    const end = parts && Math.min(parts[2] ? Number(parts[2]) : size - 1, size - 1);
    if (!parts || start > end) {
      res.writeHead(416, { 'Content-Range': `bytes */${size}` });
      return res.end();
    }
    res.writeHead(206, { ...headers, 'Content-Range': `bytes ${start}-${end}/${size}`, 'Content-Length': end - start + 1 });
    return req.method === 'HEAD' ? res.end() : createReadStream(file, { start, end }).pipe(res);
  }
  res.writeHead(200, { ...headers, 'Content-Length': size });
  return req.method === 'HEAD' ? res.end() : createReadStream(file).pipe(res);
}

async function handle(req, res, phoneOnly) {
  const { pathname, searchParams } = new URL(req.url, 'http://localhost');
  const isPost = req.method === 'POST';
  if (pathname.startsWith('/api/phone/')) {
    if (req.headers['x-pair-token'] !== phoneToken) return json(res, { error: 'Open the fresh pairing link from the laptop.' }, 403);
    const currentPhone = req.headers['x-phone-id'];
    if (!currentPhone) return json(res, { error: 'Missing phone session' }, 400);

    if (pathname === '/api/phone/ready' && isPost) {
      if (currentPhone !== phoneId && transfer?.status === 'pending') transfer.status = 'failed';
      if (currentPhone !== phoneId) phoneBatches = [];
      phoneSeen = 0;
      phoneId = currentPhone;
    } else if (currentPhone !== phoneId) {
      return json(res, { error: 'This phone session was replaced. Enable motion again.' }, 409);
    } else if (pathname === '/api/phone/samples' && isPost) {
      const samples = await body(req);
      if (!Array.isArray(samples) || samples.length > 60) throw new Error('Invalid motion batch');
      if (phoneId !== currentPhone) return json(res, { error: 'Phone session changed' }, 409);
      const valid = samples.filter(sample => Array.isArray(sample) && sample.length === 2 &&
        sample.every(Number.isFinite) && sample[1] >= 0 && sample[1] <= 4000);
      if (valid.length) {
        phoneBatches.push({ id: ++nextBatch, samples: valid });
        phoneBatches = phoneBatches.slice(-32);
        phoneSeen = Date.now();
      }
    } else if (pathname === '/api/phone/ack' && isPost) {
      const ack = await body(req);
      if (phoneId === currentPhone && transfer?.id === ack.id && ['pending', 'blocked'].includes(transfer.status)) {
        transfer.status = ack.playing ? 'playing' : 'blocked';
      }
    } else if (pathname !== '/api/phone/state') {
      return json(res, { error: 'Not found' }, 404);
    }
    return json(res, { now: Date.now(), transfer, reset });
  }

  if (pathname.startsWith('/api/host/') && !phoneOnly) {
    if (pathname === '/api/host/config') {
      const phoneHost = receiverHost();
      const phoneUrl = phoneHost ? `https://${phoneHost}:${httpsPort}/phone#${phoneToken}` : '';
      return json(res, { phoneUrl, certificateUrl: phoneHost ? `http://${phoneHost}:${httpPort}/local-ca.crt` : '',
        setupUrl: phoneHost ? `http://${phoneHost}:${httpPort}/setup#${phoneToken}` : '' });
    }
    if (pathname === '/api/host/state') {
      const after = Number(searchParams.get('after')) || 0;
      return json(res, { phoneReady: Date.now() - phoneSeen < 2000, batches: phoneBatches.filter(batch => batch.id > after), transfer });
    }
    if (pathname === '/api/host/transfer' && isPost) {
      const { time } = await body(req);
      if (!phoneId || Date.now() - phoneSeen >= 2000) return json(res, { error: 'Phone motion is offline.' }, 409);
      if (!Number.isFinite(time) || time < 0) throw new Error('Invalid playback position');
      if (!transfer) transfer = { id: randomUUID(), time, status: 'pending' };
      return json(res, { transfer });
    }
    if (pathname === '/api/host/reset' && isPost) {
      transfer = null;
      phoneBatches = [];
      reset += 1;
      return json(res, { reset });
    }
  }
  if (pathname === '/setup') return sendFile(req, res, resolve(root, 'public/setup.html'));
  if (pathname === '/setup.js') return sendFile(req, res, resolve(root, 'public/setup.js'));
  if (pathname === '/api/receiver-port') return json(res, { httpsPort });
  if (pathname === '/local-ca.crt') return sendFile(req, res, resolve(root, 'tmp/tls/ca.crt'));

  const route = pathname === '/' && !phoneOnly ? '/index.html' : pathname === '/phone' ? '/phone.html' : pathname;
  const isPublic = ['/phone.html', '/phone.js', '/shared.js', '/style.css', '/demo.mp4'].includes(route);
  const isHost = ['/index.html', '/host.js', '/match.js'].includes(route) || /^\/vendor\/vexo-open\/src\/(?:transports\/)?[\w-]+\.js$/.test(route);
  if (!isPublic && (phoneOnly || !isHost)) return json(res, { error: 'Not found' }, 404);
  return sendFile(req, res, resolve(root, route.startsWith('/vendor/') ? '.' + route : 'public' + route));
}

function serve(phoneOnly) {
  return (req, res) => {
    handle(req, res, phoneOnly).catch(error => {
      if (!res.headersSent) json(res, { error: error.message }, 400);
      else res.end();
    });
  };
}

function certificates(phoneHost) {
  const dir = resolve(root, 'tmp/tls');
  mkdirSync(dir, { recursive: true, mode: 0o700 });
  const run = (...args) => execFileSync('openssl', args, { cwd: dir, stdio: 'ignore' });
  if (!existsSync(resolve(dir, 'ca.key')) || !existsSync(resolve(dir, 'ca.crt'))) {
    run('req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '30', '-subj', '/CN=Grab the Screen local demo CA',
      '-addext', 'basicConstraints=critical,CA:TRUE', '-addext', 'keyUsage=critical,keyCertSign,cRLSign', '-keyout', 'ca.key', '-out', 'ca.crt');
  }
  const name = isIP(phoneHost) === 4 ? `IP:${phoneHost}` : `DNS:${phoneHost}`;
  writeFileSync(resolve(dir, 'server.ext'), `subjectAltName=${name}\nextendedKeyUsage=serverAuth\nbasicConstraints=critical,CA:FALSE\n`);
  run('req', '-new', '-newkey', 'rsa:2048', '-nodes', '-subj', '/CN=Grab the Screen receiver', '-keyout', 'server.key', '-out', 'server.csr');
  run('x509', '-req', '-days', '7', '-in', 'server.csr', '-CA', 'ca.crt', '-CAkey', 'ca.key', '-CAcreateserial', '-extfile', 'server.ext', '-out', 'server.crt');
  return { key: readFileSync(resolve(dir, 'server.key')), cert: readFileSync(resolve(dir, 'server.crt')) };
}

const hostHandler = serve(false);
const receiverHandler = serve(true);
http.createServer((req, res) => {
  const isLocal = req.socket.remoteAddress === '127.0.0.1' &&
    [`localhost:${httpPort}`, `127.0.0.1:${httpPort}`].includes(req.headers.host);
  (isLocal ? hostHandler : receiverHandler)(req, res);
}).listen(httpPort, '0.0.0.0', () => console.log(`Laptop: http://localhost:${httpPort}`));

let certificateHost = receiverHost() || 'localhost';
const receiver = https.createServer(certificates(certificateHost), receiverHandler);
receiver.listen(httpsPort, '0.0.0.0');

function updateReceiver() {
  const host = receiverHost();
  if (!host) return;
  if (host !== certificateHost) {
    receiver.setSecureContext(certificates(host));
    certificateHost = host;
  }
  if (host !== displayedHost) {
    console.log(`Phone setup: http://${host}:${httpPort}/setup#${phoneToken}`);
    displayedHost = host;
  }
}

let displayedHost;
updateReceiver();
setInterval(() => {
  try { updateReceiver(); } catch (error) { console.error('Receiver HTTPS:', error.message); }
}, 1000).unref();
