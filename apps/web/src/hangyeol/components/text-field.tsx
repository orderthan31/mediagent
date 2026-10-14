import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
  type HTMLAttributes,
  type ReactNode,
} from 'react';
import { Input, type InputProps } from '../primitives/input';
import { Button } from '../primitives/button';
import { FormField } from './form-field';
export type TextFieldProps = Omit<InputProps, 'onChange' | 'prefix'> & {
  label: string;
  hint?: string;
  error?: string;
  prefix?: ReactNode;
  suffix?: ReactNode;
  trailing?: ReactNode;
  clearable?: boolean;
  onValueChange?: (value: string) => void;
  onChange?: InputProps['onChange'];
  wrapperProps?: HTMLAttributes<HTMLDivElement>;
};
export const TextField = forwardRef<HTMLInputElement, TextFieldProps>(
  (
    {
      label,
      hint,
      error,
      prefix,
      suffix,
      trailing,
      clearable,
      onValueChange,
      onChange,
      value,
      defaultValue,
      id,
      wrapperProps,
      ...props
    },
    ref,
  ) => {
    const inner = useRef<HTMLInputElement>(null);
    const [local, setLocal] = useState(defaultValue ?? '');
    const [form, setForm] = useState<HTMLFormElement | null>(null);
    const [composing, setComposing] = useState(false);
    const controlled = value !== undefined,
      current = controlled ? value : local;
    useImperativeHandle(ref, () => inner.current!, []);
    const inputRef = useCallback((node: HTMLInputElement | null) => {
      inner.current = node;
      if (node) {
        setForm(node.form);
      }
    }, []);
    useEffect(() => {
      if (!form) {
        return;
      }
      const reset = (event: Event) =>
        queueMicrotask(() => {
          if (!event.defaultPrevented && !controlled) {
            setLocal(defaultValue ?? '');
          }
        });
      form.addEventListener('reset', reset);
      return () => form.removeEventListener('reset', reset);
    }, [form, controlled, defaultValue]);
    return (
      <FormField
        {...wrapperProps}
        label={label}
        hint={hint}
        error={error}
        inputProps={{
          ...props,
          id,
          value: current,
          onChange: (event) => {
            if (!controlled) {
              setLocal(event.target.value);
            }
            onValueChange?.(event.target.value);
            onChange?.(event);
          },
          onCompositionStart: (event) => {
            setComposing(true);
            props.onCompositionStart?.(event);
          },
          onCompositionEnd: (event) => {
            setComposing(false);
            props.onCompositionEnd?.(event);
          },
        }}
      >
        {(fieldProps) => (
          <div className="flex min-w-0 items-center gap-2">
            {prefix && <span className="shrink-0 text-g-small text-g-soft">{prefix}</span>}
            <Input {...fieldProps} ref={inputRef} />
            {suffix && <span className="shrink-0 text-g-small text-g-soft">{suffix}</span>}
            {trailing}
            {clearable && (
              <Button
                variant="quiet"
                size="small"
                className="shrink-0 whitespace-nowrap"
                disabled={props.disabled || props.readOnly || composing || !String(current)}
                aria-label={`${label} 지우기`}
                onClick={() => {
                  if (!controlled) {
                    setLocal('');
                  }
                  onValueChange?.('');
                  inner.current?.focus();
                }}
              >
                지우기
              </Button>
            )}
          </div>
        )}
      </FormField>
    );
  },
);
