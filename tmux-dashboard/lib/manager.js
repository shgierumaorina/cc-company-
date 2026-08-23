const { determineStatus } = require('./poller');
const { spawnAgentProcess, writeToProcess } = require('./agentProcess');

const PTY_COLS = 120;
const PTY_ROWS = 30;

function createManager({ agentsConfig, state, config, spawn = spawnAgentProcess, write = writeToProcess }) {
  const processes = new Map();

  function spawnAll() {
    const now = new Date();
    for (const agent of agentsConfig) {
      try {
        const proc = spawn({ command: 'claude', args: [], cwd: agent.cwd, cols: PTY_COLS, rows: PTY_ROWS });
        processes.set(agent.id, proc);
        state.setAgent(agent.id, {
          name: agent.name,
          cwd: agent.cwd,
          status: 'idle',
          rawOutput: '',
          lastChangedAt: now,
          changedSinceTick: false,
        });

        proc.onData((data) => {
          const prev = state.getAgent(agent.id);
          if (!prev) return;
          const lines = (prev.rawOutput + data).split('\n');
          const trimmed = lines.slice(-config.OUTPUT_LINES).join('\n');
          state.setAgent(agent.id, {
            ...prev,
            rawOutput: trimmed,
            lastChangedAt: new Date(),
            changedSinceTick: true,
          });
        });

        proc.onExit(() => {
          const prev = state.getAgent(agent.id);
          if (!prev) return;
          state.setAgent(agent.id, { ...prev, status: 'not_running' });
        });
      } catch (err) {
        state.setAgent(agent.id, {
          name: agent.name,
          cwd: agent.cwd,
          status: 'unresponsive',
          rawOutput: '',
          lastChangedAt: now,
          changedSinceTick: false,
        });
      }
    }
  }

  function tick() {
    const now = new Date();
    const changed = [];
    for (const agent of agentsConfig) {
      const prev = state.getAgent(agent.id);
      if (!prev || prev.status === 'not_running' || prev.status === 'unresponsive') continue;
      const secondsSinceChange = (now.getTime() - prev.lastChangedAt.getTime()) / 1000;
      const status = determineStatus({
        sessionExists: true,
        captureError: false,
        outputChanged: prev.changedSinceTick,
        output: prev.rawOutput,
        secondsSinceChange,
        idleThresholdSec: config.IDLE_THRESHOLD_SEC,
        staleThresholdSec: config.STALE_THRESHOLD_SEC,
      });
      if (status !== prev.status || prev.changedSinceTick) changed.push(agent.id);
      state.setAgent(agent.id, { ...prev, status, changedSinceTick: false });
    }
    return changed;
  }

  function sendToAgent(id, text) {
    const proc = processes.get(id);
    if (!proc) {
      throw new Error('agent process not found');
    }
    write(proc, text);
  }

  function start(onChange) {
    spawnAll();
    const timer = setInterval(() => {
      const changed = tick();
      if (changed.length > 0) onChange(changed);
    }, config.POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }

  return { start, sendToAgent, spawnAll, tick };
}

module.exports = { createManager };
