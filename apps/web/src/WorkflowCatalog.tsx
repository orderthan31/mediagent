import { useEffect, useState } from 'react';
import { GitBranch, ChevronRight } from 'lucide-react';
import { PageTitle } from './PageTitle';
import { Pagination, usePagination } from './Pagination';
import { request } from './api';
type Summary = { id: string; name: string; revision: number };
export const WorkflowCatalog = ({ query }: { query: string }) => {
  const [rows, setRows] = useState<Summary[]>([]);
  const [loading, setLoading] = useState(true),
    [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    request<{ definitions: Summary[] }>('/settings/workflow-definitions', {
      signal: controller.signal,
    })
      .then((result) => {
        if (!controller.signal.aborted) {
          setRows(result.definitions);
        }
      })
      .catch((value) => {
        if (!controller.signal.aborted) {
          setError(value instanceof Error ? value.message : '조회 실패');
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, []);
  const shown = rows.filter((row) =>
    row.name.toLocaleLowerCase().includes(query.toLocaleLowerCase()),
  );
  const page = usePagination(shown, query);
  return (
    <main className="ui02-catalog">
      <PageTitle>워크플로우</PageTitle>
      {error && (
        <p role="alert" className="alert">
          {error}
        </p>
      )}
      {loading ? (
        <p role="status">불러오는 중</p>
      ) : (
        <div className="ui02-list">
          {page.items.map((row) => (
            <a
              href={'#/workflows/' + row.id}
              className="ui02-list-item ui02-catalog-row"
              key={row.id}
            >
              <span className="ui02-workflow-icon">
                <GitBranch size={22} />
              </span>
              <strong className="ui02-list-title">{row.name}</strong>
              <span className="ui02-revision">r{row.revision}</span>
              <ChevronRight size={19} aria-hidden="true" />
            </a>
          ))}
          {!shown.length && !error && (
            <div className="ui02-empty">{query ? '검색 결과 없음' : '저장 워크플로우 없음'}</div>
          )}
        </div>
      )}
      {!loading && !error && <Pagination {...page} />}
    </main>
  );
};
