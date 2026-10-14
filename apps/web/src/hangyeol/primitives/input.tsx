import { forwardRef, type InputHTMLAttributes } from 'react';
import { cn } from '../lib/cn';
export type InputProps = InputHTMLAttributes<HTMLInputElement> & {
  invalid?: boolean;
  loading?: boolean;
};
export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ className, invalid, loading, ...props }, ref) => {
    return (
      <input
        {...props}
        ref={ref}
        aria-invalid={invalid || props['aria-invalid']}
        aria-busy={loading || undefined}
        className={cn(
          'block w-full min-w-0 min-h-11 border border-solid border-g-line rounded-g-control bg-g-surface enabled:hover:border-g-line-hover aria-[invalid=true]:border-g-danger aria-[invalid=true]:enabled:hover:border-g-danger transition-colors motion-reduce:transition-none px-3 py-2 text-g-body text-g-ink placeholder:text-g-soft focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-g-focus disabled:opacity-50',
          invalid && 'border-g-danger',
          className,
        )}
      />
    );
  },
);
