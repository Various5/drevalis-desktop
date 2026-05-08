// Tests for formatError + ApiError.toString() — the layer that decides
// what error string the user actually sees in toast popups.
//
// Pre-fix, ``String(err)`` on a custom Error with a non-string detail
// payload would render as ``[object Object]`` — opaque and useless.
// formatError must always produce a human-readable string regardless
// of input shape.

import { describe, it, expect } from 'vitest';
import { ApiError, formatError } from './_monolith';

describe('ApiError', () => {
  it('uses detail as the message when provided', () => {
    const err = new ApiError(404, 'Not Found', 'episode missing');
    expect(err.message).toBe('episode missing');
  });

  it('falls back to "<status> <statusText>" when detail is absent', () => {
    const err = new ApiError(500, 'Server Error');
    expect(err.message).toBe('500 Server Error');
  });

  it('toString shape: "ApiError (<status>): <message>"', () => {
    const err = new ApiError(401, 'Unauthorized', 'token expired');
    expect(err.toString()).toBe('ApiError (401): token expired');
  });

  it('exposes statusText + detailRaw fields', () => {
    const raw = { code: 'X', hint: 'try again' };
    const err = new ApiError(422, 'Unprocessable', JSON.stringify(raw), raw);
    expect(err.status).toBe(422);
    expect(err.statusText).toBe('Unprocessable');
    expect(err.detailRaw).toEqual(raw);
  });
});

describe('formatError', () => {
  it('formats ApiError via its toString', () => {
    const err = new ApiError(403, 'Forbidden', 'license required');
    expect(formatError(err)).toBe('ApiError (403): license required');
  });

  it('returns Error.message for plain Errors', () => {
    expect(formatError(new Error('boom'))).toBe('boom');
  });

  it('falls back to toString when Error.message is empty', () => {
    const err = new Error('');
    expect(formatError(err)).toBe(err.toString());
  });

  it('returns string inputs unchanged', () => {
    expect(formatError('plain string')).toBe('plain string');
  });

  it('JSON-stringifies non-Error objects', () => {
    expect(formatError({ kind: 'oops', code: 7 })).toBe('{"kind":"oops","code":7}');
  });

  it('handles arrays via JSON.stringify', () => {
    expect(formatError(['a', 'b'])).toBe('["a","b"]');
  });

  it('returns String(err) for circular structures (JSON.stringify throws)', () => {
    const circular: Record<string, unknown> = { name: 'self' };
    circular.self = circular;
    const out = formatError(circular);
    // The stringify path throws TypeError; the catch falls back to
    // String(err) which yields "[object Object]" — better than crashing
    // the toast renderer.
    expect(typeof out).toBe('string');
    expect(out.length).toBeGreaterThan(0);
  });

  it('handles null via JSON.stringify', () => {
    expect(formatError(null)).toBe('null');
  });

  it('handles numbers via JSON.stringify', () => {
    expect(formatError(42)).toBe('42');
  });

  it('handles booleans via JSON.stringify', () => {
    expect(formatError(false)).toBe('false');
  });
});
