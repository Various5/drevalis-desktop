import { forwardRef, type SelectHTMLAttributes, type ReactNode } from 'react';

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label?: string;
  error?: string;
  hint?: string;
  options: Array<{ value: string; label: string }>;
  placeholder?: string;
  icon?: ReactNode;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const Select = forwardRef<HTMLSelectElement, SelectProps>(
  (
    {
      label,
      error,
      hint,
      options,
      placeholder,
      icon,
      className = '',
      id,
      ...props
    },
    ref,
  ) => {
    const selectId = id ?? label?.toLowerCase().replace(/\s+/g, '-');

    return (
      <div className="flex flex-col gap-1">
        {label && (
          <label
            htmlFor={selectId}
            className="text-xs font-display font-medium text-txt-secondary tracking-wide"
          >
            {label}
          </label>
        )}
        <div className="relative">
          {icon && (
            <div className="absolute inset-y-0 left-0 pl-2.5 flex items-center pointer-events-none text-txt-tertiary">
              {icon}
            </div>
          )}
          <select
            ref={ref}
            id={selectId}
            className={[
              'w-full h-9 px-3 pr-8 text-sm text-txt-primary appearance-none',
              'bg-bg-base/60 backdrop-blur-sm border rounded-md cursor-pointer',
              error
                ? 'border-error/50 focus:border-error'
                : 'border-white/[0.06] focus:border-accent/50 focus:shadow-accent-glow focus:bg-bg-base/80',
              'transition-all duration-normal',
              icon ? 'pl-8' : '',
              className,
            ].join(' ')}
            {...props}
          >
            {placeholder && (
              <option value="" disabled>
                {placeholder}
              </option>
            )}
            {options.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
          {/* Dropdown chevron */}
          <div className="absolute inset-y-0 right-0 pr-2 flex items-center pointer-events-none text-txt-tertiary">
            <svg
              width="12"
              height="12"
              viewBox="0 0 12 12"
              fill="none"
              className="shrink-0"
            >
              <path
                d="M3 4.5L6 7.5L9 4.5"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </div>
        </div>
        {error && <p className="text-xs text-error">{error}</p>}
        {hint && !error && (
          <p className="text-xs text-txt-tertiary">{hint}</p>
        )}
      </div>
    );
  },
);

Select.displayName = 'Select';

export { Select };
export type { SelectProps };
