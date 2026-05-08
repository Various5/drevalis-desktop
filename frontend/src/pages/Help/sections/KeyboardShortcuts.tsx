import { Keyboard, ChevronRight } from 'lucide-react';
import { SectionHeading, SubHeading, Kbd } from './_shared';

export function KeyboardShortcuts() {
  return (
    <section id="keyboard-shortcuts" className="mb-16 scroll-mt-4">
      <SectionHeading id="keyboard-shortcuts-heading" icon={Keyboard} title="Keyboard Shortcuts" />

      <SubHeading id="player-shortcuts" title="Video Player" />
      <div className="surface rounded-lg overflow-hidden mb-6">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border">
              <th className="text-left px-4 py-2.5 text-xs font-semibold text-txt-tertiary uppercase tracking-wider">Action</th>
              <th className="text-left px-4 py-2.5 text-xs font-semibold text-txt-tertiary uppercase tracking-wider">Shortcut</th>
              <th className="text-left px-4 py-2.5 text-xs font-semibold text-txt-tertiary uppercase tracking-wider">Notes</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {[
              { action: 'Play / Pause', keys: ['Space', 'K'], notes: 'YouTube-style K shortcut also works' },
              { action: 'Seek Back 5s', keys: ['←'], notes: 'Hold for continuous seeking' },
              { action: 'Seek Forward 5s', keys: ['→'], notes: 'Hold for continuous seeking' },
              { action: 'Seek Back 10s', keys: ['J'], notes: 'Standard media player shortcut' },
              { action: 'Seek Forward 10s', keys: ['L'], notes: 'Standard media player shortcut' },
              { action: 'Mute / Unmute', keys: ['M'], notes: '' },
              { action: 'Volume Up', keys: ['↑'], notes: '+10% volume' },
              { action: 'Volume Down', keys: ['↓'], notes: '-10% volume' },
              { action: 'Fullscreen', keys: ['F'], notes: 'Toggle fullscreen mode' },
              { action: 'Toggle Captions', keys: ['C'], notes: 'Show/hide caption overlay' },
              { action: 'Speed 0.5x', keys: ['Shift+,'], notes: 'Slow down' },
              { action: 'Speed 1x', keys: ['Shift+.'], notes: 'Normal speed' },
              { action: 'Speed 2x', keys: ['Shift+/'], notes: 'Double speed' },
            ].map(row => (
              <tr key={row.action} className="hover:bg-bg-hover transition-colors">
                <td className="px-4 py-2.5 text-txt-primary text-sm">{row.action}</td>
                <td className="px-4 py-2.5">
                  <div className="flex gap-1 flex-wrap">
                    {row.keys.map(k => <Kbd key={k}>{k}</Kbd>)}
                  </div>
                </td>
                <td className="px-4 py-2.5 text-xs text-txt-tertiary">{row.notes}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <SubHeading id="activity-monitor" title="Activity Monitor" />
      <p className="text-sm text-txt-secondary leading-relaxed mb-3">
        The Activity Monitor is the floating panel in the bottom-right corner. It shows all running and
        recently completed pipeline jobs. It is visible on every page in the app.
      </p>
      <ul className="space-y-2 text-sm text-txt-secondary ml-4">
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Drag to reposition</strong> — click and drag the header to move the Activity Monitor anywhere on screen.</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Cancel jobs</strong> — click the X button on any running job to cancel it. Cancellation is checked between pipeline steps.</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Collapse/expand</strong> — click the header to minimize the monitor without closing it.</li>
        <li className="flex gap-2"><ChevronRight size={13} className="text-accent shrink-0 mt-0.5" /><strong className="text-txt-primary">Progress detail</strong> — each job shows the current step and a progress percentage in real time via WebSocket.</li>
      </ul>
    </section>
  );
}

export default KeyboardShortcuts;
