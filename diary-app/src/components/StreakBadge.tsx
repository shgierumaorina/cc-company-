interface StreakBadgeProps {
  streak: number;
}

export default function StreakBadge({ streak }: StreakBadgeProps) {
  return (
    <div className="streak-badge">
      <span className="streak-flame">🔥</span>
      <span className="streak-count">{streak}</span>
      <span className="streak-label">日連続</span>
    </div>
  );
}
