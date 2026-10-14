import { clsx, type ClassValue } from 'clsx';
import { extendTailwindMerge } from 'tailwind-merge';
// Semantic utilities join the same conflict groups as standard Tailwind utilities.
const merge = extendTailwindMerge({
  extend: {
    classGroups: {
      'font-size': [{ text: ['g-body', 'g-small', 'g-title', 'g-caption'] }],
      rounded: [{ rounded: ['g-control', 'g-panel'] }],
      px: [{ px: ['g-control'] }],
      py: [{ py: ['g-control'] }],
    },
  },
});
export const cn = (...values: ClassValue[]) => {
  return merge(clsx(values));
};
