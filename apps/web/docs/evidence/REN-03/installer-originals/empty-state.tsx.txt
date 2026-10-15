import { forwardRef, useId, type HTMLAttributes, type ReactNode } from 'react';
import { cn } from '../lib/cn';
export type EmptyStateProps = HTMLAttributes<HTMLElement> & { heading: string; description?: string; illustration?: ReactNode; actions?: ReactNode };
export const EmptyState = forwardRef<HTMLElement, EmptyStateProps>(function EmptyState({ heading, description, illustration, actions, className, ...props }, ref) {
  const id = useId();
  return <section {...props} ref={ref} aria-labelledby={props['aria-labelledby'] ?? `${id}-title`} className={cn('grid min-w-0 justify-items-center gap-3 py-8 text-center', className)}>{illustration}<h3 id={`${id}-title`} className="break-words font-semibold">{heading}</h3>{description && <p className="max-w-prose break-words text-g-small text-g-soft">{description}</p>}{actions && <div className="flex flex-wrap justify-center gap-3">{actions}</div>}</section>;
});
