const path = require('node:path');
const { execSync } = require('node:child_process');
const pty = require('node-pty');

function resolveCommandPath(command) {
  if (path.isAbsolute(command)) return command;
  try {
    const finder = process.platform === 'win32' ? 'where' : 'which';
    const output = execSync(`${finder} ${command}`, { encoding: 'utf8' });
    const first = output.split(/\r?\n/).find((line) => line.trim().length > 0);
    return first ? first.trim() : command;
  } catch (err) {
    return command;
  }
}

function spawnAgentProcess({ command, args, cwd, cols, rows }) {
  return pty.spawn(resolveCommandPath(command), args, {
    name: 'xterm-color',
    cols,
    rows,
    cwd,
    env: process.env,
  });
}

function writeToProcess(ptyProcess, text) {
  ptyProcess.write(text + '\r');
}

module.exports = { spawnAgentProcess, writeToProcess, resolveCommandPath };
