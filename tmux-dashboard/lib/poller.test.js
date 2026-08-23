const test = require('node:test');
const assert = require('node:assert');
const { determineStatus, matchesWaitingInputPattern, pollOnce } = require('./poller');
const { createState } = require('./state');

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

test('pollOnce marks not_running when session missing, and working on first-time output', async () => {
  const state = createState();
  const tmux = {
    listSessions: async () => ['cc-agent2'],
    capturePane: async (session) => `output for ${session}`,
  };
  const agentsConfig = [
    { id: 'agent1', name: 'A', session: 'cc-agent1' },
    { id: 'agent2', name: 'B', session: 'cc-agent2' },
  ];
  const now = new Date('2026-08-23T00:00:00.000Z');

  const changed = await pollOnce({ agentsConfig, tmux, state, outputLines: 200, idleThresholdSec: 60, staleThresholdSec: 300, now });

  assert.deepStrictEqual(changed.sort(), ['agent1', 'agent2']);
  assert.strictEqual(state.getAgent('agent1').status, 'not_running');
  assert.strictEqual(state.getAgent('agent2').status, 'working');
});

test('pollOnce keeps idle status and does not report change when output unchanged and no threshold crossed', async () => {
  const state = createState();
  state.setAgent('agent1', { name: 'A', session: 'cc-agent1', status: 'idle', rawOutput: 'same output', lastChangedAt: new Date('2026-08-23T00:00:00.000Z') });
  const tmux = {
    listSessions: async () => ['cc-agent1'],
    capturePane: async () => 'same output',
  };
  const agentsConfig = [{ id: 'agent1', name: 'A', session: 'cc-agent1' }];
  const now = new Date('2026-08-23T00:00:05.000Z');

  const changed = await pollOnce({ agentsConfig, tmux, state, outputLines: 200, idleThresholdSec: 60, staleThresholdSec: 300, now });

  assert.deepStrictEqual(changed, []);
  assert.strictEqual(state.getAgent('agent1').status, 'idle');
});
