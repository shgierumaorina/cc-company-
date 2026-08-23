const test = require('node:test');
const assert = require('node:assert');
const { createApp } = require('./server');
const { createState } = require('./lib/state');

function setupApp({ sessions = [], captureOutput = 'hello', sendKeysError = null } = {}) {
  const state = createState();
  state.setAgent('agent1', { name: 'A', session: 'cc-agent1', status: 'working', rawOutput: 'hello\nworld', lastChangedAt: new Date() });
  const tmux = {
    listSessions: async () => sessions,
    capturePane: async () => captureOutput,
    sendKeys: async () => {
      if (sendKeysError) throw new Error(sendKeysError);
    },
  };
  const agentsConfig = [
    { id: 'agent1', name: 'A', session: 'cc-agent1' },
    { id: 'agent2', name: 'B', session: 'cc-agent2' },
  ];
  const app = createApp({ state, tmux, agentsConfig });
  return { app, state };
}

test('GET /api/agents returns all agents with summary fields', async () => {
  const { app } = setupApp();
  const server = app.listen(0);
  const { port } = server.address();
  try {
    const res = await fetch(`http://localhost:${port}/api/agents`);
    assert.strictEqual(res.status, 200);
    const body = await res.json();
    assert.strictEqual(body.agents.length, 1); // agent2は未ポーリングなのでstateに無い→一覧には出さない
    assert.strictEqual(body.agents[0].id, 'agent1');
    assert.strictEqual(body.agents[0].status, 'working');
  } finally {
    server.close();
  }
});

test('GET /api/agents/:id/output returns full output for known id', async () => {
  const { app } = setupApp();
  const server = app.listen(0);
  const { port } = server.address();
  try {
    const res = await fetch(`http://localhost:${port}/api/agents/agent1/output`);
    assert.strictEqual(res.status, 200);
    const body = await res.json();
    assert.strictEqual(body.output, 'hello\nworld');
  } finally {
    server.close();
  }
});

test('GET /api/agents/:id/output returns 404 for unknown id', async () => {
  const { app } = setupApp();
  const server = app.listen(0);
  const { port } = server.address();
  try {
    const res = await fetch(`http://localhost:${port}/api/agents/unknown/output`);
    assert.strictEqual(res.status, 404);
  } finally {
    server.close();
  }
});

test('POST /api/agents/:id/send sends text and returns ok', async () => {
  const { app } = setupApp();
  const server = app.listen(0);
  const { port } = server.address();
  try {
    const res = await fetch(`http://localhost:${port}/api/agents/agent1/send`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: 'hello agent' }),
    });
    assert.strictEqual(res.status, 200);
    const body = await res.json();
    assert.strictEqual(body.ok, true);
    assert.strictEqual(body.id, 'agent1');
  } finally {
    server.close();
  }
});

test('POST /api/agents/:id/send returns 400 when text missing', async () => {
  const { app } = setupApp();
  const server = app.listen(0);
  const { port } = server.address();
  try {
    const res = await fetch(`http://localhost:${port}/api/agents/agent1/send`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    assert.strictEqual(res.status, 400);
  } finally {
    server.close();
  }
});

test('POST /api/agents/:id/send returns 404 for unknown id', async () => {
  const { app } = setupApp();
  const server = app.listen(0);
  const { port } = server.address();
  try {
    const res = await fetch(`http://localhost:${port}/api/agents/unknown/send`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: 'hi' }),
    });
    assert.strictEqual(res.status, 404);
  } finally {
    server.close();
  }
});

test('POST /api/agents/broadcast sends to all configured agents and reports per-agent result', async () => {
  const { app } = setupApp({ sendKeysError: null });
  const server = app.listen(0);
  const { port } = server.address();
  try {
    const res = await fetch(`http://localhost:${port}/api/agents/broadcast`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: 'hi all' }),
    });
    assert.strictEqual(res.status, 200);
    const body = await res.json();
    assert.strictEqual(body.ok, true);
    assert.strictEqual(body.results.length, 2);
  } finally {
    server.close();
  }
});
