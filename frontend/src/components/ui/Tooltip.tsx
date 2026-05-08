import { forwardRef, type ReactNode } from 'react';
import * as RadixTooltip from '@radix-ui/react-tooltip';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type TooltipSide = 'top' | 'right' | 'bottom' | 'left';

interface TooltipProps {
  /** Text content of the tooltip bubble */
  content: string;
  /** The trigger element — wrapped with asChild so no extra DOM node is added */
  children: ReactNode;
  /** Which side of the trigger to place the tooltip. Default: 'top' */
  side?: TooltipSide;
  /** Delay before the tooltip opens, in ms. Default: 300 */
  delayDuration?: number;
  /** Alignment along the trigger's axis */
  align?: 'start' | 'center' | 'end';
  /** Pixel offset from trigger. Default: 6 */
  sideOffset?: number;
}

// ---------------------------------------------------------------------------
// TooltipProvider — wraps the app (or a subtree); controls global delay
// Re-exported so consumers can place it high in the tree once.
// ---------------------------------------------------------------------------

const TooltipProvider = RadixTooltip.Provider;

// ---------------------------------------------------------------------------
// Tooltip content (inner bubble)
// ---------------------------------------------------------------------------

const TooltipContent = forwardRef<
  React.ElementRef<typeof RadixTooltip.Content>,
  React.ComponentPropsWithoutRef<typeof RadixTooltip.Content>
>(({ className = '', sideOffset = 6, ...props }, ref) => (
  <RadixTooltip.Content
    ref={ref}
    sideOffset={sideOffset}
    className={[
      // Surface
      'bg-bg-elevated border border-border rounded-md',
      // Typography
      'px-3 py-1.5 text-sm text-txt-primary',
      // Shadow for depth
      'shadow-md',
      // Layer — z-tooltip (70) from design tokens
      'z-[70]',
      // Enter/exit animations — Radix adds data-state attributes
      'data-[state=delayed-open]:animate-fade-in',
      'data-[state=closed]:animate-fade-out',
      'motion-reduce:data-[state=delayed-open]:animate-none',
      'motion-reduce:data-[state=closed]:animate-none',
      className,
    ]
      .filter(Boolean)
      .join(' ')}
    {...props}
  >
    {props.children}
    {/* Arrow — styled to match the border color */}
    <RadixTooltip.Arrow
      width={10}
      height={5}
      className="fill-border"
    />
  </RadixTooltip.Content>
));

TooltipContent.displayName = 'TooltipContent';

// ---------------------------------------------------------------------------
// Tooltip — composed convenience wrapper
// ---------------------------------------------------------------------------

function Tooltip({
  content,
  children,
  side = 'top',
  delayDuration = 300,
  align = 'center',
  sideOffset = 6,
}: TooltipProps) {
  return (
    <RadixTooltip.Root delayDuration={delayDuration}>
      {/*
        asChild merges Tooltip.Trigger props onto the immediate child element
        so we don't introduce a wrapping <button> around an existing element.
        This preserves the child's semantics and event handlers.
      */}
      <RadixTooltip.Trigger asChild>
        {children}
      </RadixTooltip.Trigger>

      <RadixTooltip.Portal>
        <TooltipContent side={side} align={align} sideOffset={sideOffset}>
          {content}
        </TooltipContent>
      </RadixTooltip.Portal>
    </RadixTooltip.Root>
  );
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

export { Tooltip, TooltipProvider, TooltipContent };
export type { TooltipProps, TooltipSide };
