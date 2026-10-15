import { forwardRef, type TextareaHTMLAttributes } from 'react';
import { cn } from '../lib/cn';
export type TextareaProps = TextareaHTMLAttributes<HTMLTextAreaElement> & { invalid?: boolean; resize?: 'vertical' | 'none' | 'both' };
const resizing = { vertical: 'resize-y', none: 'resize-none', both: 'resize' };
export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea({ className, invalid, resize = 'vertical', rows = 4, ...props }, ref) {
  return <textarea {...props} ref={ref} rows={rows} aria-invalid={invalid || props['aria-invalid']} className={cn('block w-full min-w-0 rounded-g-control border border-solid border-g-line bg-g-surface enabled:hover:border-g-line-hover aria-[invalid=true]:border-g-danger aria-[invalid=true]:enabled:hover:border-g-danger transition-colors motion-reduce:transition-none px-3 py-2 text-g-body leading-6 text-g-ink placeholder:text-g-soft focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-g-focus disabled:opacity-50', resizing[resize], invalid && 'border-g-danger', className)}/>;
});
