import {
  createContext,
  useContext,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type HTMLAttributes,
} from 'react';
import { cn } from '../lib/cn';
export type ThemeMode = 'light' | 'dark';
export type ThemeValues = Readonly<Record<`--${string}`, string | number>>;
interface ThemeScope {
  mode: ThemeMode;
  palette: string;
  explicit: ThemeValues;
  variables: CSSProperties;
}
const ThemeContext = createContext<ThemeScope>({
  mode: 'light',
  palette: 'Indigo',
  explicit: {},
  variables: {},
});
// Retain the existing mode-only public hook.
export const useTheme = () => {
  return useContext(ThemeContext).mode;
};
export const useThemeScope = () => {
  return useContext(ThemeContext);
};
export const Theme = ({
  mode,
  palette,
  values,
  className,
  style,
  ...props
}: HTMLAttributes<HTMLDivElement> & {
  mode?: ThemeMode;
  palette?: string;
  values?: ThemeValues;
}) => {
  const parent = useThemeScope(),
    root = useRef<HTMLDivElement>(null),
    applied = useRef(new Set<string>()),
    [variables, setVariables] = useState<CSSProperties>({});
  const currentMode = mode ?? parent.mode,
    currentPalette = palette ?? parent.palette;
  const ownVariables = Object.fromEntries(
    Object.entries(style ?? {}).filter(
      ([name, value]) => name.startsWith('--') && value !== undefined,
    ),
  );
  const explicit = { ...parent.explicit, ...values, ...ownVariables };
  const nativeProps = { ...props, style };
  // Carry the actual scope's computed semantic values to body/in-modal portals.
  // Read after every render: a scheme/values change does not replace native nodes.
  useLayoutEffect(() => {
    const node = root.current;
    if (!node) {
      return;
    }
    for (const name of applied.current) {
      if (!Object.hasOwn(explicit, name)) {
        node.style.removeProperty(name);
      }
    }
    for (const [name, value] of Object.entries(explicit)) {
      node.style.setProperty(name, String(value));
    }
    applied.current = new Set(Object.keys(explicit));
    const read = () => {
      const computed = getComputedStyle(node),
        next: Record<string, string> = {};
      for (let i = 0; i < computed.length; i++) {
        const name = computed.item(i);
        if (name.startsWith('--g-') || Object.hasOwn(explicit, name)) {
          next[name] = computed.getPropertyValue(name).trim();
        }
      }
      for (const [name, value] of Object.entries(explicit)) {
        if (!next[name]) {
          next[name] = String(value);
        }
      }
      setVariables((previous) =>
        JSON.stringify(previous) === JSON.stringify(next) ? previous : next,
      );
    };
    read();
    const observer = new MutationObserver(read);
    observer.observe(node, {
      attributes: true,
      attributeFilter: ['style', 'class', 'data-theme', 'data-palette'],
    });
    return () => observer.disconnect();
  });
  return (
    <ThemeContext.Provider
      value={{
        mode: currentMode,
        palette: currentPalette,
        explicit,
        variables: { ...variables, ...explicit },
      }}
    >
      <div
        {...nativeProps}
        ref={root}
        data-hangyeol=""
        data-theme={currentMode}
        data-palette={currentPalette}
        className={cn('font-g-sans text-g-body text-g-ink bg-g-canvas', className)}
      />
    </ThemeContext.Provider>
  );
};
