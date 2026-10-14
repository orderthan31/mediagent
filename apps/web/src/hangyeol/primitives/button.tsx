import { forwardRef, type ButtonHTMLAttributes } from 'react';
import { cn } from '../lib/cn';
const variants = {
  primary: 'bg-g-action text-g-on-action border-transparent hover:bg-g-action-hover',
  secondary:
    'bg-g-surface text-g-ink border-g-line enabled:hover:border-g-line-hover hover:bg-g-muted',
  quiet: 'bg-transparent text-g-soft border-transparent hover:bg-g-muted hover:text-g-ink',
} satisfies Record<string, string>;
const sizes = {
  small: 'min-h-11 px-3 py-2 text-g-small',
  medium: 'min-h-11 px-g-control py-2 text-g-body',
} satisfies Record<string, string>;
export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: keyof typeof variants;
  size?: keyof typeof sizes;
  loading?: boolean;
};
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      variant = 'primary',
      size = 'medium',
      loading = false,
      disabled,
      className,
      type = 'button',
      children,
      ...props
    },
    ref,
  ) => {
    return (
      <button
        {...props}
        ref={ref}
        type={type}
        disabled={disabled || loading}
        aria-busy={loading || undefined}
        className={cn(
          'inline-flex items-center justify-center gap-2 border border-solid rounded-g-control font-medium leading-6 transition-colors focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-g-focus disabled:opacity-50',
          variants[variant],
          sizes[size],
          className,
        )}
      >
        {children}
        {loading && <span aria-hidden="true">…</span>}
      </button>
    );
  },
);
