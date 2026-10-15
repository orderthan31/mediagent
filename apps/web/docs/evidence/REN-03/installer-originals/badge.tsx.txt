import { forwardRef, type HTMLAttributes } from 'react';
import { cn } from '../lib/cn';
const tones = {
 neutral: 'bg-g-muted text-g-ink border-g-line',
 info: 'bg-g-surface text-g-action border-g-action',
 danger: 'bg-g-surface text-g-danger border-g-danger',
} as const;
export type BadgeProps = HTMLAttributes<HTMLSpanElement> & { tone?: keyof typeof tones };
export const Badge = forwardRef<HTMLSpanElement, BadgeProps>(function Badge({tone='neutral',className,children,...props},ref){
 return <span {...props} ref={ref} className={cn('inline align-baseline box-decoration-clone max-w-full whitespace-normal break-keep wrap-anywhere rounded-g-control border border-solid px-2 py-0.5 text-g-small leading-6',tones[tone],className)}>{children}</span>;
});
