const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const express = require('express');
const cors = require('cors');
const { WebSocketServer } = require('ws');
const { formatAgentSummary, createState } = require('./lib/state');
const { createManager } = require('./lib/manager');

function findAgentConfig(agentsConfig, id) {
  return agentsConfig.find((a) => a.id === id);
}

function createApp({ state, manager, agentsConfig }) {
  const app = express();
  app.use(cors());
  app.use(express.json());

  app.get('/api/agents', (req, res) => {
    const now = new Date();
    const agents = state
      .getAllIds()
      .map((id) => formatAgentSummary(id, state.getAgent(id), now));
    res.json({ agents });
  });

  app.get('/api/agents/:id/output', (req, res) => {
    const data = state.getAgent(req.params.id);
    if (!data) {
      res.status(404).json({ error: 'agent not found' });
      return;
    }
    res.json({ id: req.params.id, cwd: data.cwd, output: data.rawOutput });
  });

  app.post('/api/agents/:id/send', (req, res) => {
    const { id } = req.params;
    const { text } = req.body || {};
    if (typeof text !== 'string' || text.length === 0) {
      res.status(400).json({ error: 'text is required' });
      return;
    }
    const agentConfig = findAgentConfig(agentsConfig, id);
    if (!agentConfig) {
      res.status(404).json({ error: 'agent not found' });
      return;
    }
    const data = state.getAgent(id);
    if (data && data.status === 'not_running') {
      res.status(409).json({ error: 'process not running' });
      return;
    }
    try {
      manager.sendToAgent(id, text);
      res.json({ ok: true, id, sentAt: new Date().toISOString() });
    } catch (err) {
      res.status(500).json({ error: err.message });
    }
  });

  app.post('/api/agents/broadcast', (req, res) => {
    const { text } = req.body || {};
    if (typeof text !== 'string' || text.length === 0) {
      res.status(400).json({ error: 'text is required' });
      return;
    }
    const results = agentsConfig.map((agentConfig) => {
      try {
        manager.sendToAgent(agentConfig.id, text);
        return { id: agentConfig.id, ok: true };
      } catch (err) {
        return { id: agentConfig.id, ok: false, error: err.message };
      }
    });
    res.json({ ok: true, results });
  });

  return app;
}

function attachWebSocketServer({ httpServer, state, agentsConfig }) {
  const wss = new WebSocketServer({ server: httpServer, path: '/ws' });

  wss.on('connection', (ws) => {
    const now = new Date();
    const agents = state
      .getAllIds()
      .map((id) => formatAgentSummary(id, state.getAgent(id), now));
    ws.send(JSON.stringify({ type: 'snapshot', agents }));
  });

  function broadcastUpdate(changedIds) {
    const now = new Date();
    const agents = changedIds
      .filter((id) => state.getAgent(id))
      .map((id) => formatAgentSummary(id, state.getAgent(id), now));
    if (agents.length === 0) return;
    const payload = JSON.stringify({ type: 'update', agents });
    wss.clients.forEach((client) => {
      if (client.readyState === client.OPEN) client.send(payload);
    });
  }

  return { wss, broadcastUpdate };
}

function main() {
  const configPath = path.join(__dirname, 'config.json');
  const agentsPath = path.join(__dirname, 'agents.json');
  const config = JSON.parse(fs.readFileSync(configPath, 'utf8'));
  const agentsConfig = JSON.parse(fs.readFileSync(agentsPath, 'utf8'));

  const state = createState();
  const manager = createManager({ agentsConfig, state, config });
  const app = createApp({ state, manager, agentsConfig });
  const httpServer = http.createServer(app);
  const { broadcastUpdate } = attachWebSocketServer({ httpServer, state, agentsConfig });

  manager.start(broadcastUpdate);

  httpServer.listen(config.PORT, () => {
    console.log(`tmux-dashboard server listening on port ${config.PORT}`);
  });
}

if (require.main === module) {
  main();
}

module.exports = { createApp, attachWebSocketServer, main };
