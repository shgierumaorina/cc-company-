const pty = require('node-pty');

function spawnAgentProcess({ command, args, cwd, cols, rows }) {
  return pty.spawn(command, args, {
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

module.exports = { spawnAgentProcess, writeToProcess };
