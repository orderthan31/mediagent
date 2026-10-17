import { useState, type ReactNode } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { Button } from './hangyeol/primitives/button';
import { pageWindow } from './pagination-state';
export { pageWindow } from './pagination-state';
import './pagination.css';
// Existing endpoints return complete arrays. This bounds rendering consistently;
// it does not claim to implement server-side pagination for those endpoints.
export const usePagination = <T,>(rows: T[], key: string, size = 20) => {
  const [selection, setSelection] = useState({ key, page: 1 });
  const state = pageWindow(rows.length, selection.key === key ? selection.page : 1, size);
  return {
    ...state,
    items: rows.slice(state.offset, state.offset + state.pageSize),
    onPage: (page: number) => setSelection({ key, page: pageWindow(rows.length, page, size).page }),
  };
};
export const Pagination = ({
  total,
  page,
  pages,
  first,
  last,
  onPage,
  disabled = false,
  children,
}: {
  total: number;
  page: number;
  pages: number;
  first: number;
  last: number;
  onPage: (page: number) => void;
  disabled?: boolean;
  children?: ReactNode;
}) => (
  <nav className="list-pagination" aria-label="목록 페이지">
    <span role="status">{total ? `${first}–${last} / ${total}개` : '0개'}</span>
    <div className="pagination-controls">
      <Button
        variant="quiet"
        aria-label="이전 페이지"
        disabled={disabled || page <= 1}
        onClick={() => onPage(page - 1)}
      >
        <ChevronLeft size={16} />
      </Button>
      <label>
        <span className="pagination-label">페이지</span>
        <select
          aria-label="페이지 선택"
          value={page}
          disabled={disabled || pages <= 1}
          onChange={(event) => onPage(Number(event.target.value))}
        >
          {Array.from({ length: pages }, (_, index) => (
            <option key={index + 1} value={index + 1}>
              {index + 1}
            </option>
          ))}
        </select>
        <span>/ {pages}</span>
      </label>
      <Button
        variant="quiet"
        aria-label="다음 페이지"
        disabled={disabled || page >= pages}
        onClick={() => onPage(page + 1)}
      >
        <ChevronRight size={16} />
      </Button>
    </div>
    {children}
  </nav>
);
