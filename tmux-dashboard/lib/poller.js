const WAITING_INPUT_PATTERNS = [
  /[❯>]\s*$/,
  /\(y\/n\)/i,
  /Do you want/i,
  /continue\?/i,
];

function matchesWaitingInputPattern(output) {
  const trimmed = (output || '').trimEnd();
  return WAITING_INPUT_PATTERNS.some((re) => re.test(trimmed));
}

function determineStatus({ sessionExists, captureError, outputChanged, output, secondsSinceChange, idleThresholdSec, staleThresholdSec }) {
  if (!sessionExists) return 'not_running';
  if (captureError) return 'unresponsive';
  if (outputChanged) return 'working';
  if (matchesWaitingInputPattern(output)) return 'waiting_input';
  if (secondsSinceChange >= staleThresholdSec) return 'stale';
  if (secondsSinceChange >= idleThresholdSec) return 'idle';
  return 'idle';
}

async function pollOnce({ agentsConfig, tmux, state, outputLines, idleThresholdSec, staleThresholdSec, now }) {
  const changed = [];
  const sessions = await tmux.listSessions();

  for (const agent of agentsConfig) {
    const prev = state.getAgent(agent.id);
    const sessionExists = sessions.includes(agent.session);
    let captureError = false;
    let output = prev ? prev.rawOutput : '';

    if (sessionExists) {
      try {
        output = await tmux.capturePane(agent.session, outputLines);
      } catch (err) {
        captureError = true;
      }
    }

    const outputChanged = sessionExists && !captureError && output !== (prev ? prev.rawOutput : undefined);
    const lastChangedAt = outputChanged || !prev ? now : prev.lastChangedAt;
    const secondsSinceChange = (now.getTime() - lastChangedAt.getTime()) / 1000;

    const status = determineStatus({
      sessionExists,
      captureError,
      outputChanged,
      output,
      secondsSinceChange,
      idleThresholdSec,
      staleThresholdSec,
    });

    state.setAgent(agent.id, {
      name: agent.name,
      session: agent.session,
      status,
      rawOutput: output,
      lastChangedAt,
    });

    if (!prev || prev.status !== status || outputChanged) {
      changed.push(agent.id);
    }
  }

  return changed;
}

function startPolling({ agentsConfig, tmux, state, config, onChange }) {
  async function runOnce() {
    const changed = await pollOnce({
      agentsConfig,
      tmux,
      state,
      outputLines: config.OUTPUT_LINES,
      idleThresholdSec: config.IDLE_THRESHOLD_SEC,
      staleThresholdSec: config.STALE_THRESHOLD_SEC,
      now: new Date(),
    });
    if (changed.length > 0) onChange(changed);
  }
  runOnce();
  const timer = setInterval(runOnce, config.POLL_INTERVAL_MS);
  return () => clearInterval(timer);
}

module.exports = { matchesWaitingInputPattern, determineStatus, pollOnce, startPolling };
