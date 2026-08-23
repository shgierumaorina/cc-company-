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

module.exports = { matchesWaitingInputPattern, determineStatus };
