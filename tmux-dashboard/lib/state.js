function createState() {
  const agents = new Map();
  return {
    setAgent(id, data) {
      agents.set(id, data);
    },
    getAgent(id) {
      return agents.get(id);
    },
    getAllIds() {
      return Array.from(agents.keys());
    },
  };
}

function formatAgentSummary(id, data, now) {
  const lines = data.rawOutput ? data.rawOutput.split('\n') : [];
  const preview = lines.slice(-5).join('\n');
  const elapsedSec = Math.floor((now.getTime() - data.lastChangedAt.getTime()) / 1000);
  return {
    id,
    name: data.name,
    cwd: data.cwd,
    status: data.status,
    lastOutputPreview: preview,
    lastChangedAt: data.lastChangedAt.toISOString(),
    elapsedSec,
  };
}

module.exports = { createState, formatAgentSummary };
