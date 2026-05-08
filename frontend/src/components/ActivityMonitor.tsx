/**
 * Back-compat shim — the ActivityMonitor was refactored into a package
 * at components/ActivityMonitor/. Any existing import of this file
 * (e.g. from Layout.tsx) continues to work unchanged.
 */
export { ActivityMonitor } from './ActivityMonitor/index';
