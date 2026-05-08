import { forwardRef } from 'react';
import * as RadixTabs from '@radix-ui/react-tabs';

// ---------------------------------------------------------------------------
// Root
// ---------------------------------------------------------------------------

const Tabs = RadixTabs.Root;

// ---------------------------------------------------------------------------
// TabsList — horizontal tab strip with scrollable overflow on mobile
// ---------------------------------------------------------------------------

const TabsList = forwardRef<
  React.ElementRef<typeof RadixTabs.List>,
  React.ComponentPropsWithoutRef<typeof RadixTabs.List>
>(({ className = '', ...props }, ref) => (
  <RadixTabs.List
    ref={ref}
    className={[
      'flex items-center gap-1 overflow-x-auto scrollbar-hidden',
      'border-b border-white/[0.06]',
      '-mb-px', // overlap border with tab trigger underline
      className,
    ]
      .filter(Boolean)
      .join(' ')}
    {...props}
  />
));
TabsList.displayName = 'TabsList';

// ---------------------------------------------------------------------------
// TabsTrigger — individual tab button
// ---------------------------------------------------------------------------

const TabsTrigger = forwardRef<
  React.ElementRef<typeof RadixTabs.Trigger>,
  React.ComponentPropsWithoutRef<typeof RadixTabs.Trigger> & {
    /** Optional icon (lucide-react component) */
    icon?: React.ComponentType<{ size?: number; className?: string }>;
  }
>(({ className = '', icon: Icon, children, ...props }, ref) => (
  <RadixTabs.Trigger
    ref={ref}
    className={[
      // Layout
      'inline-flex items-center gap-1.5 whitespace-nowrap',
      'px-3 py-2 text-sm font-display font-medium',
      // Base styling
      'text-txt-secondary border-b-2 border-transparent',
      'transition-colors duration-fast',
      // Hover
      'hover:text-txt-primary',
      // Active state (Radix adds data-state="active")
      'data-[state=active]:text-accent data-[state=active]:border-accent',
      // Focus
      'focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-1',
      // Touch target
      'min-h-[44px] md:min-h-0',
      className,
    ]
      .filter(Boolean)
      .join(' ')}
    {...props}
  >
    {Icon && <Icon size={14} className="shrink-0" />}
    {children}
  </RadixTabs.Trigger>
));
TabsTrigger.displayName = 'TabsTrigger';

// ---------------------------------------------------------------------------
// TabsContent — panel content
// ---------------------------------------------------------------------------

const TabsContent = forwardRef<
  React.ElementRef<typeof RadixTabs.Content>,
  React.ComponentPropsWithoutRef<typeof RadixTabs.Content>
>(({ className = '', ...props }, ref) => (
  <RadixTabs.Content
    ref={ref}
    className={[
      'mt-4 focus-visible:outline-none',
      // Enter animation
      'data-[state=active]:animate-fade-in',
      'motion-reduce:data-[state=active]:animate-none',
      className,
    ]
      .filter(Boolean)
      .join(' ')}
    {...props}
  />
));
TabsContent.displayName = 'TabsContent';

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

export { Tabs, TabsList, TabsTrigger, TabsContent };
