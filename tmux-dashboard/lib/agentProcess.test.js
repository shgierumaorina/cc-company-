const test = require('node:test');
const assert = require('node:assert');
const { spawnAgentProcess, writeToProcess, resolveCommandPath } = require('./agentProcess');

test('resolveCommandPath returns absolute paths unchanged', () => {
  assert.strictEqual(resolveCommandPath('C:\\Windows\\System32\\cmd.exe'), 'C:\\Windows\\System32\\cmd.exe');
});

test('resolveCommandPath resolves a bare command name to its full path via PATH search', () => {
  const resolved = resolveCommandPath('cmd.exe');
  assert.ok(resolved.toLowerCase().endsWith('cmd.exe'));
  assert.notStrictEqual(resolved, 'cmd.exe');
});

test('resolveCommandPath falls back to the original string when not found', () => {
  const resolved = resolveCommandPath('this-command-does-not-exist-xyz');
  assert.strictEqual(resolved, 'this-command-does-not-exist-xyz');
});

test('spawnAgentProcess captures stdout from the spawned process', async () => {
  const proc = spawnAgentProcess({ command: 'cmd.exe', args: ['/c', 'echo HELLO_PTY_TEST'], cwd: process.cwd(), cols: 80, rows: 30 });
  const output = await new Promise((resolve) => {
    let buf = '';
    proc.onData((d) => { buf += d; });
    proc.onExit(() => resolve(buf));
  });
  proc.kill();
  assert.ok(output.includes('HELLO_PTY_TEST'));
});

test('writeToProcess sends text followed by a carriage return to a running shell', async () => {
  const proc = spawnAgentProcess({ command: 'cmd.exe', args: [], cwd: process.cwd(), cols: 80, rows: 30 });
  const output = await new Promise((resolve) => {
    let buf = '';
    let exitRequested = false;
    proc.onData((d) => {
      buf += d;
      if (!exitRequested && buf.includes('HELLO_FROM_WRITE')) {
        exitRequested = true;
        proc.write('exit\r');
      }
    });
    proc.onExit(() => resolve(buf));
    setTimeout(() => writeToProcess(proc, 'echo HELLO_FROM_WRITE'), 800);
  });
  proc.kill();
  assert.ok(output.includes('HELLO_FROM_WRITE'));
});
