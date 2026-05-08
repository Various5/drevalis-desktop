// Shared sub-components used by every Help section file.
// Import only from this file — never from the monolith directly.

import { useState, type ReactNode } from 'react';
import {
  Lightbulb,
  AlertTriangle,
  Info,
  Link2,
  CheckSquare,
  type LucideIcon,
} from 'lucide-react';

// ---------------------------------------------------------------------------
// Inline primitive components
// ---------------------------------------------------------------------------

export function Kbd({ children }: { children: string }) {
  return (
    <kbd className="px-1.5 py-0.5 text-xs font-mono bg-bg-elevated border border-border rounded text-txt-primary">
      {children}
    </kbd>
  );
}

export function Tip({ children }: { children: ReactNode }) {
  return (
    <div className="flex gap-3 p-3 rounded-md bg-green-500/10 border-l-2 border-green-500 my-4">
      <Lightbulb size={14} className="text-green-400 mt-0.5 shrink-0" />
      <p className="text-sm text-txt-secondary leading-relaxed">{children}</p>
    </div>
  );
}

export function Warning({ children }: { children: ReactNode }) {
  return (
    <div className="flex gap-3 p-3 rounded-md bg-amber-500/10 border-l-2 border-amber-500 my-4">
      <AlertTriangle size={14} className="text-amber-400 mt-0.5 shrink-0" />
      <p className="text-sm text-txt-secondary leading-relaxed">{children}</p>
    </div>
  );
}

export function InfoBox({ children }: { children: ReactNode }) {
  return (
    <div className="flex gap-3 p-3 rounded-md bg-blue-500/10 border-l-2 border-blue-500 my-4">
      <Info size={14} className="text-blue-400 mt-0.5 shrink-0" />
      <p className="text-sm text-txt-secondary leading-relaxed">{children}</p>
    </div>
  );
}

export function CodeBlock({ children }: { children: ReactNode }) {
  return (
    <pre className="bg-bg-elevated border border-border rounded-md p-4 text-xs font-mono text-txt-secondary overflow-x-auto my-3 leading-relaxed">
      {children}
    </pre>
  );
}

export function CopyLinkButton({ id, label }: { id: string; label: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      const url = `${window.location.origin}/help#${id}`;
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked — skip silently */
    }
  };
  return (
    <button
      type="button"
      onClick={copy}
      className="opacity-0 group-hover:opacity-100 transition-opacity rounded p-1 text-txt-muted hover:text-accent"
      aria-label={`Copy link to ${label}`}
      title={copied ? 'Link copied!' : 'Copy link'}
    >
      {copied ? <CheckSquare size={12} /> : <Link2 size={12} />}
    </button>
  );
}

export function SectionHeading({
  id,
  icon: Icon,
  title,
}: {
  id: string;
  icon: LucideIcon;
  title: string;
}) {
  return (
    <div id={id} className="group flex items-center gap-3 mb-5 pt-2 scroll-mt-4">
      <div className="w-9 h-9 rounded-lg bg-accent/20 flex items-center justify-center shrink-0">
        <Icon size={17} className="text-accent" />
      </div>
      <h2 className="text-xl font-semibold text-txt-primary">{title}</h2>
      <CopyLinkButton id={id} label={title} />
    </div>
  );
}

export function SubHeading({ id, title }: { id: string; title: string }) {
  return (
    <h3
      id={id}
      className="group flex items-center gap-2 text-md font-semibold text-txt-primary mt-8 mb-3 scroll-mt-6"
    >
      <span>{title}</span>
      <CopyLinkButton id={id} label={title} />
    </h3>
  );
}

export function StepBadge({ step, color }: { step: string; color: string }) {
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold"
      style={{ background: `${color}22`, color }}
    >
      {step}
    </span>
  );
}
