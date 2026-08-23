const { execFile } = require('node:child_process');

function buildListSessionsArgs() {
  return ['-e', 'tmux', 'list-sessions', '-F', '#S'];
}

function buildCapturePaneArgs(session, lines) {
  return ['-e', 'tmux', 'capture-pane', '-t', session, '-p', '-S', `-${lines}`];
}

function buildSendKeysArgs(session, text) {
  return ['-e', 'tmux', 'send-keys', '-t', session, text, 'Enter'];
}

function runWsl(args) {
  return new Promise((resolve, reject) => {
    execFile('wsl', args, { maxBuffer: 1024 * 1024 * 10 }, (error, stdout, stderr) => {
      if (error) {
        reject(new Error(stderr || error.message));
        return;
      }
      resolve(stdout);
    });
  });
}

async function listSessions() {
  try {
    const stdout = await runWsl(buildListSessionsArgs());
    return stdout.split('\n').map((s) => s.trim()).filter(Boolean);
  } catch (err) {
    return [];
  }
}

async function capturePane(session, lines) {
  return runWsl(buildCapturePaneArgs(session, lines));
}

async function sendKeys(session, text) {
  await runWsl(buildSendKeysArgs(session, text));
}

module.exports = {
  buildListSessionsArgs,
  buildCapturePaneArgs,
  buildSendKeysArgs,
  listSessions,
  capturePane,
  sendKeys,
};
