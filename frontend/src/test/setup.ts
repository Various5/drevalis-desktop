// Vitest global setup. Loaded once before any test runs.
//
// Adds @testing-library/jest-dom matchers (toBeInTheDocument, toHaveClass,
// etc.) so component tests can assert on rendered DOM ergonomically.
import '@testing-library/jest-dom/vitest';
