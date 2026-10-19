// Bounded Chromium startup and shutdown for native planning diagnostics.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {setTimeout: pause} = require('node:timers/promises');

const DEVTOOLS_FILE = 'DevToolsActivePort';
const SPAWN_CODES = new Set(['ENOENT', 'EACCES', 'EPERM', 'EMFILE', 'ENFILE', 'ENOMEM', 'EAGAIN']);
const SIGNALS = new Set(Object.keys(os.constants.signals));
const STARTUP_REASONS = [
  ['sandbox', /no usable sandbox|suid sandbox|failed to move to new namespace/i],
  ['resource_limit', /out of memory|cannot allocate memory|pthread_create|resource temporarily unavailable/i],
  ['disk_space', /no space left on device/i],
  ['profile_lock', /processsingleton|singletonlock|profile appears to be in use/i],
  ['crashpad', /crashpad_handler/i],
  ['devtools_announced', /devtools listening on ws:\/\//i],
];

/** Read only a complete loopback DevTools handshake; partial writes stay pending. */
function readDevToolsPort(profile) {
  let contents;
  try {
    contents = fs.readFileSync(path.join(profile, DEVTOOLS_FILE), 'utf8');
  } catch (error) {
    if (error.code === 'ENOENT') return null;
    throw error;
  }
  const [number, endpoint] = contents.trim().split(/\r?\n/);
  if (!/^[1-9][0-9]{0,4}$/.test(number)
      || !endpoint?.startsWith('/devtools/browser/')
      || endpoint.length <= '/devtools/browser/'.length) return null;
  const port = Number(number);
  return port <= 65535 ? port : null;
}

/** Describe only operating-system exit metadata, excluding child output. */
function exitStatus(code, signal) {
  const status = Number.isInteger(code) ? code : 'none';
  const name = SIGNALS.has(signal) ? signal : 'none';
  return `exit=${status}, signal=${name}`;
}

/**
 * Observe one browser process without retrying or changing its sandbox flags.
 *
 * @param {import('node:child_process').ChildProcess} browser Spawned browser.
 * @param {string} profile This invocation's private temporary profile.
 * @param {{timeoutMs?: number, pollMs?: number}} options Bounded test timings.
 * @returns {Promise<number>} The port from a complete DevTools handshake.
 */
async function waitForBrowserPort(browser, profile, {timeoutMs = 20000, pollMs = 100} = {}) {
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1
      || !Number.isSafeInteger(pollMs) || pollMs < 1) {
    throw new RangeError('Browser startup timings must be positive integer milliseconds.');
  }
  const reasons = new Set();
  let tail = '', spawnError = null;
  let exited = browser.exitCode !== null || browser.signalCode !== null;
  let exitCode = browser.exitCode, signal = browser.signalCode;
  const observeError = error => { spawnError = SPAWN_CODES.has(error.code) ? error.code : 'unknown'; };
  const observeExit = (code, name) => { exited = true; exitCode = code; signal = name; };
  const observeStderr = chunk => {
    // Keep a bounded rolling buffer for split messages; never return raw output.
    tail = (tail + chunk.toString()).slice(-4096);
    for (const [name, pattern] of STARTUP_REASONS) {
      if (pattern.test(tail)) reasons.add(name);
    }
  };
  browser.on('error', observeError);
  browser.on('exit', observeExit);
  browser.stderr?.on('data', observeStderr);
  const deadline = Date.now() + timeoutMs;
  const diagnostics = () => [...reasons].sort().join(',') || 'none';
  try {
    while (true) {
      if (spawnError) throw new Error(`The benchmark browser could not start (spawn=${spawnError}, diagnostics=${diagnostics()}).`);
      if (exited) {
        throw new Error(`Headless browser exited before DevTools became ready (${exitStatus(exitCode, signal)}, diagnostics=${diagnostics()}).`);
      }
      const port = readDevToolsPort(profile);
      if (port !== null) return port;
      if (Date.now() >= deadline) {
        const present = fs.existsSync(path.join(profile, DEVTOOLS_FILE));
        throw new Error(`Headless browser did not start (state=running, readiness_file=${present}, diagnostics=${diagnostics()}).`);
      }
      await pause(pollMs);
    }
  } finally {
    browser.off('error', observeError);
    browser.off('exit', observeExit);
    browser.stderr?.off('data', observeStderr);
    // Continue draining after startup without retaining benchmark/browser output.
    browser.stderr?.resume();
  }
}

/** Translate Playwright launch failures into the same allowlisted evidence.
 * @param {unknown} error Browser-driver exception; never include its raw text.
 * @returns {Error} Safe startup context without arguments, paths or child output.
 */
function browserStartupError(error) {
  const message = error instanceof Error ? error.message : '';
  const reasons = STARTUP_REASONS.filter(([, pattern]) => pattern.test(message))
    .map(([name]) => name).sort().join(',') || 'none';
  const code = message.match(/exitCode=(-?[0-9]{1,3})(?:,|\s)/)?.[1];
  const signal = message.match(/signal=([A-Z0-9]+)/)?.[1];
  const spawn = SPAWN_CODES.has(error?.code) ? error.code : 'unknown';
  return new Error(`The benchmark browser could not start (${exitStatus(code === undefined ? null : Number(code), signal)}, spawn=${spawn}, diagnostics=${reasons}).`);
}

/**
 * Require a clean owned browser exit even when its close promise never resolves.
 *
 * @param {import('node:child_process').ChildProcess} browser Owned Chromium child.
 * @param {() => Promise<unknown>} requestClose Request one graceful browser close.
 * @param {{timeoutMs?: number}} options Existing bounded shutdown grace period.
 * @returns {Promise<void>} Resolves only after successful actual process exit.
 */
async function waitForBrowserShutdown(browser, requestClose, {timeoutMs = 1000} = {}) {
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1) {
    throw new RangeError('Browser shutdown timeout must be positive integer milliseconds.');
  }
  const exitError = (code, signal) => new Error(
    `The benchmark browser failed during shutdown (${exitStatus(code, signal)}).`,
  );
  if (browser.exitCode !== null || browser.signalCode !== null) {
    if (browser.exitCode === 0 && browser.signalCode === null) return;
    throw exitError(browser.exitCode, browser.signalCode);
  }
  let resolveExit, rejectExit, timer, requestRejected = false;
  const exited = new Promise((resolve, reject) => {
    resolveExit = resolve;
    rejectExit = reject;
  });
  const onExit = (code, signal) => {
    if (code === 0 && signal === null) resolveExit();
    else rejectExit(exitError(code, signal));
  };
  const onError = error => rejectExit(new Error(
    `The benchmark browser shutdown reported a process error (code=${SPAWN_CODES.has(error.code) ? error.code : 'unknown'}).`,
  ));
  browser.once('exit', onExit);
  browser.once('error', onError);
  try {
    timer = setTimeout(() => rejectExit(new Error(
      `The benchmark browser did not exit within ${timeoutMs} milliseconds (close_request_rejected=${requestRejected}).`,
    )), timeoutMs);
    // A close acknowledgement is neither required nor sufficient for process exit.
    // Observe rejection without exposing protocol details or leaving it unhandled.
    Promise.resolve().then(requestClose).catch(() => { requestRejected = true; });
    await exited;
  } finally {
    clearTimeout(timer);
    browser.off('exit', onExit);
    browser.off('error', onError);
  }
}

module.exports = {waitForBrowserPort, browserStartupError, waitForBrowserShutdown};
