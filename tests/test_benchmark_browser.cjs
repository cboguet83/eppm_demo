const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {EventEmitter} = require('node:events');
const {PassThrough} = require('node:stream');
const {spawn} = require('node:child_process');
const {setTimeout: pause} = require('node:timers/promises');
const {waitForBrowserPort, browserStartupError} = require('../scripts/benchmark_browser.cjs');

test('Playwright launch errors preserve only allowlisted startup evidence', () => {
  const failure = Object.assign(new Error('No usable sandbox! private-startup-marker <process did exit: exitCode=23, signal=SIGTERM>'), {code:'EACCES'});
  const safe = browserStartupError(failure);
  assert.match(safe.message, /exit=23, signal=SIGTERM, spawn=EACCES, diagnostics=sandbox/);
  assert.doesNotMatch(safe.message, /private-startup-marker/);
  assert.equal(safe.cause, undefined);
  assert.match(browserStartupError({code:'private-startup-marker'}).message, /spawn=unknown, diagnostics=none/);
  assert.match(browserStartupError(null).message, /exit=none, signal=none/);
});

function privateProfile(t) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'eppm-browser-readiness-test-'));
  t.after(() => fs.rmSync(directory, {recursive: true, force: true}));
  return directory;
}

function browserProcess(t) {
  const child = new EventEmitter();
  child.exitCode = null;
  child.signalCode = null;
  child.stderr = new PassThrough();
  t.after(() => child.stderr.destroy());
  return child;
}

test('a complete handshake returns its port and removes startup observers', async t => {
  const profile = privateProfile(t), browser = browserProcess(t);
  fs.writeFileSync(path.join(profile, 'DevToolsActivePort'), '45678\n/devtools/browser/test-id\n');

  assert.equal(await waitForBrowserPort(browser, profile), 45678);
  assert.equal(browser.listenerCount('error'), 0);
  assert.equal(browser.listenerCount('exit'), 0);
  assert.equal(browser.stderr.listenerCount('data'), 0);
});

test('invalid timing inputs fail before accepting readiness or installing observers', async t => {
  const profile = privateProfile(t), browser = browserProcess(t);
  fs.writeFileSync(path.join(profile, 'DevToolsActivePort'), '45678\n/devtools/browser/test-id\n');
  for (const options of [
    {timeoutMs: 0}, {timeoutMs: NaN}, {timeoutMs: Infinity},
    {pollMs: 0}, {pollMs: -1}, {pollMs: 1.5},
  ]) {
    await assert.rejects(waitForBrowserPort(browser, profile, options), RangeError);
  }
  assert.equal(browser.listenerCount('error'), 0);
  assert.equal(browser.listenerCount('exit'), 0);
});

test('partial or invalid handshakes do not release readiness', async t => {
  const profile = privateProfile(t), browser = browserProcess(t);
  const file = path.join(profile, 'DevToolsActivePort');
  fs.writeFileSync(file, '45678\n');
  let completed = false;
  const ready = waitForBrowserPort(browser, profile, {timeoutMs: 2000, pollMs: 1})
    .then(port => { completed = true; return port; });
  await pause(5);
  assert.equal(completed, false);
  fs.writeFileSync(file, '99999\n/devtools/browser/test-id\n');
  await pause(5);
  assert.equal(completed, false);
  fs.writeFileSync(file, '45678\n/devtools/browser/test-id\n');
  assert.equal(await ready, 45678);
});

test('spawn errors report only allowlisted error codes', async t => {
  const browser = browserProcess(t);
  const ready = waitForBrowserPort(browser, privateProfile(t), {pollMs: 1});
  queueMicrotask(() => browser.emit('error', Object.assign(
    new Error('private-startup-marker'), {code: 'EACCES'},
  )));

  await assert.rejects(ready, error => {
    assert.match(error.message, /spawn=EACCES/);
    assert.doesNotMatch(error.message, /private-startup-marker/);
    return true;
  });
  assert.equal(browser.listenerCount('error'), 0);
});

test('unknown spawn error payloads remain private', async t => {
  const browser = browserProcess(t);
  const ready = waitForBrowserPort(browser, privateProfile(t), {pollMs: 1});
  queueMicrotask(() => browser.emit('error', Object.assign(
    new Error('private-startup-marker'), {code: 'private-startup-marker'},
  )));
  await assert.rejects(ready, error => {
    assert.match(error.message, /spawn=unknown/);
    assert.doesNotMatch(error.message, /private-startup-marker/);
    return true;
  });
});

test('early exits classify split startup stderr without exposing its contents', async t => {
  const browser = browserProcess(t);
  const ready = waitForBrowserPort(browser, privateProfile(t), {pollMs: 1});
  queueMicrotask(() => {
    browser.stderr.write('No usable san');
    browser.stderr.write('dbox! private-startup-marker');
    browser.emit('exit', 23, null);
  });

  await assert.rejects(ready, error => {
    assert.match(error.message, /exit=23, signal=none, diagnostics=sandbox/);
    assert.doesNotMatch(error.message, /private-startup-marker/);
    return true;
  });
});

test('signal exits remain failures and identify resource-limit evidence', async t => {
  const browser = browserProcess(t);
  const ready = waitForBrowserPort(browser, privateProfile(t), {pollMs: 1});
  queueMicrotask(() => {
    browser.stderr.write('pthread_create: Resource temporarily unavailable private-startup-marker');
    browser.emit('exit', null, 'SIGKILL');
  });

  await assert.rejects(ready, error => {
    assert.match(error.message, /exit=none, signal=SIGKILL, diagnostics=resource_limit/);
    assert.doesNotMatch(error.message, /private-startup-marker/);
    return true;
  });
});

test('a live browser without readiness still fails at the bounded deadline', async t => {
  const browser = browserProcess(t);
  await assert.rejects(
    waitForBrowserPort(browser, privateProfile(t), {timeoutMs: 5, pollMs: 1}),
    /state=running, readiness_file=false, diagnostics=none/,
  );
  assert.equal(browser.listenerCount('exit'), 0);
});

test('an already exited process cannot satisfy a stale readiness file', async t => {
  const profile = privateProfile(t), browser = browserProcess(t);
  browser.exitCode = 0;
  fs.writeFileSync(path.join(profile, 'DevToolsActivePort'), '45678\n/devtools/browser/test-id\n');
  await assert.rejects(waitForBrowserPort(browser, profile), /exit=0, signal=none/);
});

test('an actual child exit is reported without waiting for a readiness timeout', async t => {
  const browser = spawn(process.execPath, ['-e',
    "process.stderr.write('No usable sandbox! private-startup-marker'); process.exit(23);",
  ], {stdio: ['ignore', 'ignore', 'pipe']});
  t.after(() => { if (browser.exitCode === null) browser.kill(); });

  await assert.rejects(
    waitForBrowserPort(browser, privateProfile(t), {timeoutMs: 5000, pollMs: 1}),
    error => {
      assert.match(error.message, /exit=23, signal=none, diagnostics=sandbox/);
      assert.doesNotMatch(error.message, /private-startup-marker/);
      return true;
    },
  );
});
