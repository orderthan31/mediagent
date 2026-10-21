import type { MouseEvent, KeyboardEvent } from 'react';
const interactive =
  'a,button,input,select,textarea,label,summary,[role="button"],[contenteditable]:not([contenteditable="false"])';
export const rowClick = (event: MouseEvent<HTMLTableRowElement>, href: string) => {
  if (
    event.defaultPrevented ||
    event.button !== 0 ||
    event.ctrlKey ||
    event.metaKey ||
    event.shiftKey ||
    event.altKey
  ) {
    return;
  }
  if (
    !(event.target instanceof Element) ||
    event.target.closest(interactive) ||
    window.getSelection()?.toString()
  ) {
    return;
  }
  location.hash = href;
};
export const rowKeyDown = (event: KeyboardEvent<HTMLTableRowElement>, href: string) => {
  if (
    event.target !== event.currentTarget ||
    event.defaultPrevented ||
    event.ctrlKey ||
    event.metaKey ||
    event.altKey ||
    event.shiftKey
  ) {
    return;
  }
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault();
    location.hash = href;
  }
};
