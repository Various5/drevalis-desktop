// Minimal ambient typings for the few Node built-ins used by *test-only*
// files. The app is browser-targeted, so the tsconfig deliberately omits
// @types/node (it would pollute globals like setTimeout's return type). The
// design-token contrast audit (src/styles/tokens.a11y.test.ts) needs to read
// globals.css from disk, so we declare just the surface it touches.

declare module 'node:fs' {
  export function readFileSync(path: string, encoding: 'utf8'): string;
}

declare module 'node:path' {
  export function resolve(...segments: string[]): string;
}

declare const process: {
  cwd(): string;
};
