import { forwardRef, type InputHTMLAttributes, type TextareaHTMLAttributes, type ReactNode } from 'react';

// ---------------------------------------------------------------------------
// Text Input
// ---------------------------------------------------------------------------

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  hint?: string;
  leftIcon?: ReactNode;
}

const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ label, error, hint, leftIcon, className = '', id, ...props }, ref) => {
    const inputId = id ?? label?.toLowerCase().replace(/\s+/g, '-');

    return (
      <div className="flex flex-col gap-1">
        {label && (
          <label
            htmlFor={inputId}
            className="text-xs font-display font-medium text-txt-secondary tracking-wide"
          >
            {label}
          </label>
        )}
        <div className="relative">
          {leftIcon && (
            <div className="absolute inset-y-0 left-0 pl-2.5 flex items-center pointer-events-none text-txt-tertiary">
              {leftIcon}
            </div>
          )}
          <input
            ref={ref}
            id={inputId}
            className={[
              'w-full h-9 px-3 text-sm text-txt-primary',
              'bg-bg-base/60 backdrop-blur-sm border rounded-md',
              error
                ? 'border-error/50 focus:border-error focus:shadow-error-glow'
                : 'border-white/[0.06] focus:border-accent/50 focus:shadow-accent-glow focus:bg-bg-base/80',
              'placeholder:text-txt-tertiary/60',
              'transition-all duration-normal',
              leftIcon ? 'pl-8' : '',
              className,
            ].join(' ')}
            {...props}
          />
        </div>
        {error && <p className="text-xs text-error">{error}</p>}
        {hint && !error && (
          <p className="text-xs text-txt-tertiary">{hint}</p>
        )}
      </div>
    );
  },
);

Input.displayName = 'Input';

// ---------------------------------------------------------------------------
// Textarea
// ---------------------------------------------------------------------------

interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string;
  error?: string;
  hint?: string;
}

const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ label, error, hint, className = '', id, ...props }, ref) => {
    const inputId = id ?? label?.toLowerCase().replace(/\s+/g, '-');

    return (
      <div className="flex flex-col gap-1">
        {label && (
          <label
            htmlFor={inputId}
            className="text-xs font-display font-medium text-txt-secondary tracking-wide"
          >
            {label}
          </label>
        )}
        <textarea
          ref={ref}
          id={inputId}
          className={[
            'w-full min-h-[80px] px-3 py-2.5 text-sm text-txt-primary',
            'bg-bg-base/60 backdrop-blur-sm border rounded-md resize-y',
            error
              ? 'border-error/50 focus:border-error focus:shadow-error-glow'
              : 'border-white/[0.06] focus:border-accent/50 focus:shadow-accent-glow focus:bg-bg-base/80',
            'placeholder:text-txt-tertiary/60',
            'transition-all duration-normal',
            className,
          ].join(' ')}
          {...props}
        />
        {error && <p className="text-xs text-error">{error}</p>}
        {hint && !error && (
          <p className="text-xs text-txt-tertiary">{hint}</p>
        )}
      </div>
    );
  },
);

Textarea.displayName = 'Textarea';

export { Input, Textarea };
export type { InputProps, TextareaProps };
