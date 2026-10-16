import { useEffect, useState } from 'react';
import { ArrowUpRight, GitBranch, ChevronRight } from 'lucide-react';
import { request } from './api';
type Summary = { id: string; name: string; revision: number };
type Definition = Summary & { nodes: { id: string; type: string }[]; edges: unknown[] };
export const WorkflowCatalog = ({ query, identity }: { query: string; identity?: string }) => {
  const [rows, setRows] = useState<Summary[]>([]), [detail, setDetail] = useState<Definition | null>(null);
  const [loading, setLoading] = useState(true), [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(''); setDetail(null);
    const load = async () => {
      try {
        if (identity) setDetail(await request<Definition>('/settings/workflow-definitions/' + identity, { signal: controller.signal }));
        else setRows((await request<{ definitions: Summary[] }>('/settings/workflow-definitions', { signal: controller.signal })).definitions);
      } catch (value) { if (!controller.signal.aborted) setError(value instanceof Error ? value.message : '조회 실패'); }
      finally { if (!controller.signal.aborted) setLoading(false); }
    };
    void load(); return () => controller.abort();
  }, [identity]);
  return <main className="ui02-catalog">
    <div className="ui02-page-heading"><h1>{identity ? detail?.name || '워크플로우 상세' : '워크플로우'}</h1>{!identity && !loading && !error && <span>{rows.length}</span>}{detail && <span className="ui02-revision">r{detail.revision}</span>}</div>
    {error && <p role="alert" className="alert">{error}</p>}
    {loading ? <p role="status">불러오는 중</p> : detail ? <>
      <section className="ui02-definition-summary"><dl><div><dt>에이전트</dt><dd>{detail.nodes.length}</dd></div><div><dt>연결</dt><dd>{detail.edges.length}</dd></div></dl><ol>{detail.nodes.map(node => <li key={node.id}><GitBranch size={17} /><strong>{node.id}</strong><span>{node.type}</span></li>)}</ol></section>
      <a className="ui02-text-action" href="#/start">작업 추가<ArrowUpRight size={17} /></a>
    </> : <div className="ui02-list">{rows.filter(row => row.name.toLocaleLowerCase().includes(query.toLocaleLowerCase())).map(row => <a href={'#/workflows/' + row.id} className="ui02-list-item ui02-catalog-row" key={row.id}><span className="ui02-workflow-icon"><GitBranch size={22} /></span><strong className="ui02-list-title">{row.name}</strong><span className="ui02-revision">r{row.revision}</span><ChevronRight size={19} aria-hidden="true" /></a>)}{!rows.length && !error && <div className="ui02-empty">저장 워크플로우 없음</div>}</div>}
  </main>;
};
