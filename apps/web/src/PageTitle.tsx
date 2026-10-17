import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ComponentProps,
  type ReactNode,
} from 'react';
import { createPortal } from 'react-dom';

// Titles remain owned by their route (including asynchronous names and focus refs),
// but occupy the GNB instead of a separate body row.
const TitleContext = createContext<{
  host: HTMLDivElement | null;
  setHost: (host: HTMLDivElement | null) => void;
} | null>(null);
export const PageTitleProvider = ({ children }: { children: ReactNode }) => {
  const [host, setHost] = useState<HTMLDivElement | null>(null);
  return <TitleContext.Provider value={{ host, setHost }}>{children}</TitleContext.Provider>;
};
export const PageTitleSlot = () => {
  const context = useContext(TitleContext);
  return <div className="ui02-title-slot" ref={context?.setHost} />;
};
export const PageTitle = ({ children, ...props }: ComponentProps<'h1'>) => {
  const context = useContext(TitleContext);
  useEffect(() => {
    if (typeof children === 'string') document.title = `${children} · mideagent`;
  }, [children]);
  if (!context) return <h1 {...props}>{children}</h1>;
  return context.host ? createPortal(<h1 {...props}>{children}</h1>, context.host) : null;
};
