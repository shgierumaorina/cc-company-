const test = require('node:test');
const assert = require('node:assert');
const { determineStatus, matchesWaitingInputPattern } = require('./poller');

test('determineStatus: not_running when session does not exist', () => {
  const status = determineStatus({ sessionExists: false, captureError: false, outputChanged: false, output: '', secondsSinceChange: 0, idleThresholdSec: 60, staleThresholdSec: 300 });
  assert.strictEqual(status, 'not_running');
});

test('determineStatus: unresponsive when capture errors', () => {
  const status = determineStatus({ sessionExists: true, captureError: true, outputChanged: false, output: '', secondsSinceChange: 0, idleThresholdSec: 60, staleThresholdSec: 300 });
  assert.strictEqual(status, 'unresponsive');
});

test('determineStatus: working when output changed', () => {
  const status = determineStatus({ sessionExists: true, captureError: false, outputChanged: true, output: 'some output', secondsSinceChange: 0, idleThresholdSec: 60, staleThresholdSec: 300 });
  assert.strictEqual(status, 'working');
});

test('determineStatus: waiting_input when output ends with prompt pattern', () => {
  const status = determineStatus({ sessionExists: true, captureError: false, outputChanged: false, output: 'Do you want to proceed? (y/n)', secondsSinceChange: 5, idleThresholdSec: 60, staleThresholdSec: 300 });
  assert.strictEqual(status, 'waiting_input');
});

test('determineStatus: idle when unchanged past idle threshold', () => {
  const status = determineStatus({ sessionExists: true, captureError: false, outputChanged: false, output: 'nothing special', secondsSinceChange: 70, idleThresholdSec: 60, staleThresholdSec: 300 });
  assert.strictEqual(status, 'idle');
});

test('determineStatus: stale when unchanged past stale threshold', () => {
  const status = determineStatus({ sessionExists: true, captureError: false, outputChanged: false, output: 'nothing special', secondsSinceChange: 400, idleThresholdSec: 60, staleThresholdSec: 300 });
  assert.strictEqual(status, 'stale');
});

test('determineStatus: idle (not working) when unchanged and below idle threshold', () => {
  const status = determineStatus({ sessionExists: true, captureError: false, outputChanged: false, output: 'nothing special', secondsSinceChange: 5, idleThresholdSec: 60, staleThresholdSec: 300 });
  assert.strictEqual(status, 'idle');
});

test('matchesWaitingInputPattern detects common prompt strings', () => {
  assert.strictEqual(matchesWaitingInputPattern('foo\n> '), true);
  assert.strictEqual(matchesWaitingInputPattern('foo\n❯ '), true);
  assert.strictEqual(matchesWaitingInputPattern('Continue? (y/n)'), true);
  assert.strictEqual(matchesWaitingInputPattern('Do you want to proceed?'), true);
  assert.strictEqual(matchesWaitingInputPattern('normal output line'), false);
});
