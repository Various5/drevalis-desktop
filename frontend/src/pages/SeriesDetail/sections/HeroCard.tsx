import { useEffect, useMemo, useState } from 'react';
import {
  Calendar,
  CheckCircle2,
  Clock,
  Film,
  Globe,
  LayoutTemplate,
  MoreVertical,
  Pencil,
  Trash2,
} from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';

// Sits at the top of the page as the visual anchor for the series.
// Title and description are edited inline — clicking the text swaps
// to an input that blur-commits back to the autosave loop, so the
// user never has to hunt for a save button. Metric chips show the
// at-a-glance status (episode count, total runtime, language,
// format, last activity). The three rare, destructive-ish actions
// (apply template / save as template / delete) hide behind a kebab
// menu so the hero stays clean.

export interface HeroCardProps {
  name: string;
  onNameChange: (next: string) => void;
  description: string;
  onDescriptionChange: (next: string) => void;
  episodeCount: number;
  totalRuntimeSeconds: number;
  language: string;
  contentFormat: string;
  lastActivity: string | null;
  onApplyTemplate: () => void;
  onSaveAsTemplate: () => void;
  savingAsTemplate: boolean;
  saveTemplateSuccess: boolean;
  onDelete: () => void;
}

export function HeroCard({
  name,
  onNameChange,
  description,
  onDescriptionChange,
  episodeCount,
  totalRuntimeSeconds,
  language,
  contentFormat,
  lastActivity,
  onApplyTemplate,
  onSaveAsTemplate,
  savingAsTemplate,
  saveTemplateSuccess,
  onDelete,
}: HeroCardProps) {
  const [editingTitle, setEditingTitle] = useState(false);
  const [editingDesc, setEditingDesc] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  const runtimeLabel = useMemo(() => {
    const mins = Math.round(totalRuntimeSeconds / 60);
    if (mins === 0) return `${totalRuntimeSeconds}s`;
    if (mins < 60) return `${mins}m`;
    const hrs = Math.floor(mins / 60);
    const rem = mins % 60;
    return rem ? `${hrs}h ${rem}m` : `${hrs}h`;
  }, [totalRuntimeSeconds]);

  const lastActivityLabel = useMemo(() => {
    if (!lastActivity) return 'No activity yet';
    try {
      const d = new Date(lastActivity);
      const diffMs = Date.now() - d.getTime();
      const diffH = Math.floor(diffMs / 3_600_000);
      if (diffH < 1) return 'Active in the last hour';
      if (diffH < 24) return `${diffH}h ago`;
      const diffD = Math.floor(diffH / 24);
      if (diffD < 7) return `${diffD}d ago`;
      return d.toLocaleDateString();
    } catch {
      return lastActivity;
    }
  }, [lastActivity]);

  useEffect(() => {
    if (!menuOpen) return;
    const handler = () => setMenuOpen(false);
    window.addEventListener('click', handler);
    return () => window.removeEventListener('click', handler);
  }, [menuOpen]);

  return (
    <Card padding="lg">
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0 space-y-3">
          {editingTitle ? (
            <input
              autoFocus
              value={name}
              onChange={(e) => onNameChange(e.target.value)}
              onBlur={() => setEditingTitle(false)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === 'Escape') {
                  (e.target as HTMLInputElement).blur();
                }
              }}
              className="w-full bg-transparent border-b border-accent/50 focus:border-accent outline-none text-2xl font-semibold text-txt-primary pb-1"
              aria-label="Series name"
            />
          ) : (
            <button
              type="button"
              onClick={() => setEditingTitle(true)}
              className="group flex items-center gap-2 text-left -mx-1 px-1 rounded hover:bg-bg-hover/40 transition-colors duration-fast"
              title="Click to rename"
            >
              <h1 className="text-2xl font-semibold text-txt-primary truncate">
                {name || 'Untitled series'}
              </h1>
              <Pencil
                size={14}
                className="text-txt-muted opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
              />
            </button>
          )}

          {editingDesc ? (
            <textarea
              autoFocus
              value={description}
              onChange={(e) => onDescriptionChange(e.target.value)}
              onBlur={() => setEditingDesc(false)}
              rows={2}
              placeholder="Describe this series..."
              className="w-full bg-bg-elevated border border-border rounded px-3 py-2 text-sm text-txt-secondary outline-none focus:border-accent resize-none"
              aria-label="Series description"
            />
          ) : (
            <button
              type="button"
              onClick={() => setEditingDesc(true)}
              className="group block w-full text-left -mx-1 px-1 py-0.5 rounded hover:bg-bg-hover/40 transition-colors duration-fast"
              title="Click to edit description"
            >
              <p
                className={[
                  'text-sm line-clamp-2',
                  description ? 'text-txt-secondary' : 'text-txt-muted italic',
                ].join(' ')}
              >
                {description || 'Add a short description…'}
              </p>
            </button>
          )}

          <div className="flex flex-wrap items-center gap-2 pt-1">
            <Badge variant="neutral" className="gap-1">
              <Film size={10} />
              {episodeCount} {episodeCount === 1 ? 'episode' : 'episodes'}
            </Badge>
            <Badge variant="neutral" className="gap-1">
              <Clock size={10} />
              {runtimeLabel}
            </Badge>
            <Badge variant="neutral" className="gap-1">
              <Globe size={10} />
              {language}
            </Badge>
            <Badge variant="accent" className="gap-1 capitalize">
              <LayoutTemplate size={10} />
              {contentFormat.replace('_', ' ')}
            </Badge>
            <Badge variant="neutral" className="gap-1">
              <Calendar size={10} />
              {lastActivityLabel}
            </Badge>
          </div>
        </div>

        <div className="relative shrink-0">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              setMenuOpen((v) => !v);
            }}
            className="rounded-md border border-border bg-bg-elevated p-1.5 text-txt-secondary hover:text-txt-primary hover:bg-bg-hover transition-colors duration-fast"
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            aria-label="More actions"
          >
            <MoreVertical size={16} />
          </button>
          {menuOpen && (
            <div
              className="absolute right-0 mt-1 w-56 rounded-lg border border-border bg-bg-surface shadow-lg z-20 py-1 text-sm"
              role="menu"
              onClick={(e) => e.stopPropagation()}
            >
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  setMenuOpen(false);
                  onApplyTemplate();
                }}
                className="flex w-full items-center gap-2 px-3 py-2 text-left text-txt-secondary hover:bg-bg-hover hover:text-txt-primary"
              >
                <LayoutTemplate size={13} />
                Apply Template…
              </button>
              <button
                type="button"
                role="menuitem"
                disabled={savingAsTemplate}
                onClick={() => {
                  setMenuOpen(false);
                  onSaveAsTemplate();
                }}
                className="flex w-full items-center gap-2 px-3 py-2 text-left text-txt-secondary hover:bg-bg-hover hover:text-txt-primary disabled:opacity-50"
              >
                {saveTemplateSuccess ? (
                  <CheckCircle2 size={13} className="text-success" />
                ) : (
                  <LayoutTemplate size={13} />
                )}
                {saveTemplateSuccess
                  ? 'Template saved'
                  : savingAsTemplate
                    ? 'Saving template…'
                    : 'Save as Template'}
              </button>
              <div className="my-1 border-t border-border" />
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  setMenuOpen(false);
                  onDelete();
                }}
                className="flex w-full items-center gap-2 px-3 py-2 text-left text-error hover:bg-error/10"
              >
                <Trash2 size={13} />
                Delete Series
              </button>
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}
