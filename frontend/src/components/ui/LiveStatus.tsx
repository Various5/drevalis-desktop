import { Badge } from './Badge';

interface LiveStatusProps {
  connected: boolean;
  label?: string;
  className?: string;
}

function LiveStatus({ connected, label, className = '' }: LiveStatusProps) {
  if (connected) {
    return (
      <Badge variant="success" dot className={className}>
        {label ?? 'Live'}
      </Badge>
    );
  }
  return (
    <Badge variant="warning" dot className={className}>
      {label ?? 'Reconnecting\u2026'}
    </Badge>
  );
}

export { LiveStatus };
export type { LiveStatusProps };
