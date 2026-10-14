import { forwardRef, useId, type HTMLAttributes, type ReactNode } from 'react';
import { Input, type InputProps } from '../primitives/input';
import { cn } from '../lib/cn';
export type FormFieldProps = Omit<HTMLAttributes<HTMLDivElement>, 'children'> & {
  label: string;
  hint?: string;
  error?: string;
  inputProps?: InputProps;
  children?: ReactNode | ((props: InputProps) => ReactNode);
};
export const FormField = forwardRef<HTMLDivElement, FormFieldProps>(
  ({ label, hint, error, inputProps = {}, children, className, ...props }, ref) => {
    const generated = useId(),
      id = inputProps.id ?? generated;
    const describedBy =
      [inputProps['aria-describedby'], hint && `${id}-hint`, error && `${id}-error`]
        .filter(Boolean)
        .join(' ') || undefined;
    const fieldProps: InputProps = {
      ...inputProps,
      id,
      'aria-describedby': describedBy,
      invalid: !!error || inputProps.invalid,
      'aria-invalid': !!error || inputProps['aria-invalid'],
    };
    return (
      <div {...props} ref={ref} className={cn('grid min-w-0 gap-2', className)}>
        <label htmlFor={id} className="text-g-small font-medium">
          {label}
          {inputProps.required && <span className="text-g-small text-g-soft"> (필수)</span>}
        </label>
        {typeof children === 'function'
          ? children(fieldProps)
          : (children ?? <Input {...fieldProps} />)}{' '}
        {hint && (
          <p id={`${id}-hint`} className="text-g-small text-g-soft">
            {hint}
          </p>
        )}
        {error && (
          <p id={`${id}-error`} role="alert" className="text-g-small text-g-danger">
            {error}
          </p>
        )}
      </div>
    );
  },
);
