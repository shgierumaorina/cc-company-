const express = require('express');
const cors = require('cors');
const { formatAgentSummary } = require('./lib/state');

function findAgentConfig(agentsConfig, id) {
  return agentsConfig.find((a) => a.id === id);
}

function createApp({ state, tmux, agentsConfig }) {
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
    res.json({ id: req.params.id, session: data.session, output: data.rawOutput });
  });

  app.post('/api/agents/:id/send', async (req, res) => {
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
      res.status(409).json({ error: 'session not running' });
      return;
    }
    try {
      await tmux.sendKeys(agentConfig.session, text);
      res.json({ ok: true, id, sentAt: new Date().toISOString() });
    } catch (err) {
      res.status(500).json({ error: err.message });
    }
  });

  app.post('/api/agents/broadcast', async (req, res) => {
    const { text } = req.body || {};
    if (typeof text !== 'string' || text.length === 0) {
      res.status(400).json({ error: 'text is required' });
      return;
    }
    const results = await Promise.all(
      agentsConfig.map(async (agentConfig) => {
        try {
          await tmux.sendKeys(agentConfig.session, text);
          return { id: agentConfig.id, ok: true };
        } catch (err) {
          return { id: agentConfig.id, ok: false, error: err.message };
        }
      }),
    );
    res.json({ ok: true, results });
  });

  return app;
}

module.exports = { createApp };
