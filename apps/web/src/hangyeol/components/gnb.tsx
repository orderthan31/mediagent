import { forwardRef, useRef, type HTMLAttributes, type ReactNode } from 'react';
import { cn } from '../lib/cn';
export type NavItem = { id: string; label: string; href: string; disabled?: boolean };
export type GNBProps = HTMLAttributes<HTMLElement> & {
  logo: ReactNode;
  items: NavItem[];
  actions?: ReactNode;
  currentHref?: string;
  label?: string;
};
export const GNB = forwardRef<HTMLElement, GNBProps>(
  ({ logo, items, actions, currentHref, label = '주 메뉴', className, ...props }, ref) => {
    const menu = useRef<HTMLDetailsElement>(null);
    const links = items.map((item) => (
      <li key={item.id}>
        {item.disabled ? (
          <span
            aria-disabled="true"
            className="inline-flex min-h-11 items-center px-3 py-2 text-g-soft opacity-50"
          >
            {item.label}
          </span>
        ) : (
          <a
            href={item.href}
            aria-current={item.href === currentHref ? 'page' : undefined}
            className={cn(
              'inline-flex min-h-11 items-center break-words rounded-g-control px-3 py-2 text-g-small focus-visible:outline-3 focus-visible:outline-g-focus',
              item.href === currentHref ? 'bg-g-muted text-g-ink' : 'text-g-soft hover:bg-g-muted',
            )}
          >
            {item.label}
          </a>
        )}
      </li>
    ));
    return (
      <header
        {...props}
        ref={ref}
        className={cn(
          'flex min-w-0 flex-wrap items-center justify-between gap-3 border-b border-solid border-g-line bg-g-surface px-4 py-3',
          className,
        )}
      >
        <div className="min-w-0 shrink-0">{logo}</div>
        <nav aria-label={label} className="hidden min-w-0 flex-1 sm:block">
          <ul className="flex min-w-0 flex-wrap items-center gap-1">{links}</ul>
        </nav>
        {actions}
        <details
          ref={menu}
          className="w-full sm:hidden"
          onKeyDown={(event) => {
            if (event.key === 'Escape' && menu.current?.open) {
              event.preventDefault();
              menu.current.open = false;
              menu.current.querySelector('summary')?.focus();
            }
          }}
        >
          <summary className="min-h-11 cursor-pointer rounded-g-control px-3 py-2 text-g-small focus-visible:outline-3 focus-visible:outline-g-focus">
            메뉴
          </summary>
          <nav
            aria-label={label}
            onClick={(event) => {
              if ((event.target as HTMLElement).closest('a') && menu.current) {
                menu.current.open = false;
              }
            }}
          >
            <ul className="grid gap-1 py-2">{links}</ul>
          </nav>
        </details>
      </header>
    );
  },
);
