const test = require('node:test');
const assert = require('node:assert');
const {
  buildListSessionsArgs,
  buildCapturePaneArgs,
  buildSendKeysArgs,
} = require('./tmux');

test('buildListSessionsArgs returns tmux list-sessions args', () => {
  assert.deepStrictEqual(buildListSessionsArgs(), [
    '-e', 'tmux', 'list-sessions', '-F', '#S',
  ]);
});

test('buildCapturePaneArgs returns tmux capture-pane args with line limit', () => {
  assert.deepStrictEqual(buildCapturePaneArgs('cc-agent1', 200), [
    '-e', 'tmux', 'capture-pane', '-t', 'cc-agent1', '-p', '-S', '-200',
  ]);
});

test('buildSendKeysArgs keeps text as a single array element (no shell join)', () => {
  const args = buildSendKeysArgs('cc-agent1', 'echo "hello"; rm -rf /');
  assert.deepStrictEqual(args, [
    '-e', 'tmux', 'send-keys', '-t', 'cc-agent1',
    'echo "hello"; rm -rf /', 'Enter',
  ]);
});
