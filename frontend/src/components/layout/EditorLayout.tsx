import { Outlet } from 'react-router-dom';

// Minimal layout used by the fullscreen video editor. Skips the
// main sidebar, header, activity monitor, and page padding so the
// editor gets the entire viewport. The editor route is mounted
// against this layout so "/episodes/:id/edit" is a chromeless app,
// while every other route continues to use the standard ``Layout``
// with its navigation rail.

function EditorLayout() {
  return (
    <div className="fixed inset-0 bg-bg-base text-txt-primary flex flex-col">
      <Outlet />
    </div>
  );
}

export { EditorLayout };
