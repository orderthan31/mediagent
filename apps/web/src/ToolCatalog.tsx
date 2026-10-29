import { useEffect, useState } from 'react';
import { ApiError, request } from './api';
import { PageTitle } from './PageTitle';
import { LoadingSkeleton } from './LoadingSkeleton';

type Tool = {
  id: string;
  name: string;
  inputs: Record<string, string>;
  outputs: Record<string, string>;
  settings: string[];
  requires_model: boolean;
  availability: string;
};
type Agent = { id: string; name: string; goal: string; tools: Tool[] };
const status = (tool: Tool) =>
  tool.availability === 'on_demand'
    ? tool.requires_model
      ? '모델 선택 후 사용'
      : '필요할 때 준비'
    : '상태 확인 필요';
export const ToolCatalog = ({ query, identity }: { query: string; identity?: string }) => {
  const [tools, setTools] = useState<Tool[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const selected = tools.find((t) => t.id === identity);
  const shown = tools.filter((t) => t.name.includes(query));
  useEffect(() => {
    const c = new AbortController();
    request<{ tools: Tool[] }>('/tool-hub/tools', { signal: c.signal })
      .then((r) => {
        if (!c.signal.aborted) {
          setTools(r.tools);
        }
      })
      .catch(() => {
        if (!c.signal.aborted) {
          setError('툴을 불러오지 못했습니다.');
        }
      })
      .finally(() => {
        if (!c.signal.aborted) {
          setLoading(false);
        }
      });
    return () => c.abort();
  }, []);
  return (
    <main className="ui02-catalog">
      <PageTitle>{identity ? selected?.name || '툴 상세' : '툴'}</PageTitle>
      {error && <p role="alert">{error}</p>}
      {loading ? (
        <LoadingSkeleton layout="list" label="툴 불러오는 중" />
      ) : identity ? (
        selected ? (
          <section className="tool-detail">
            <p role="status">{status(selected)}</p>
            <h2>입력</h2>
            <ul>
              {Object.values(selected.inputs).map((x) => (
                <li key={x}>{x}</li>
              ))}
            </ul>
            <h2>출력</h2>
            <ul>
              {Object.values(selected.outputs).map((x) => (
                <li key={x}>{x}</li>
              ))}
            </ul>
            {selected.settings.length > 0 && (
              <>
                <h2>설정</h2>
                <ul>
                  {selected.settings.map((x) => (
                    <li key={x}>{x}</li>
                  ))}
                </ul>
              </>
            )}
            <a href="#/tools">툴 목록</a>
          </section>
        ) : (
          !error && <p>툴을 찾을 수 없습니다.</p>
        )
      ) : (
        <div className="ui02-list">
          {shown.map((t) => (
            <a className="ui02-list-item" href={'#/tools/' + t.id} key={t.id}>
              <div className="ui02-list-copy">
                <h2 className="ui02-list-title">{t.name}</h2>
                <p className="ui02-list-meta">
                  {Object.values(t.inputs).join(' · ')} → {Object.values(t.outputs).join(' · ')}
                </p>
              </div>
              <span>{status(t)}</span>
            </a>
          ))}
          {!error && !shown.length && <p>{query ? '검색 결과 없음' : '등록된 툴 없음'}</p>}
        </div>
      )}
    </main>
  );
};
export const AgentHubCatalog = ({ identity }: { identity?: string }) => {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const selected = agents.find((a) => a.id === identity);
  useEffect(() => {
    const c = new AbortController();
    const load = async () => {
      try {
        const r = await request<{ agents: Agent[] }>('/agent-hub/agents', { signal: c.signal });
        if (identity && r.agents.some((a) => a.id === identity)) {
          const detail = await request<Agent>('/agent-hub/agents/' + encodeURIComponent(identity), {
            signal: c.signal,
          });
          if (!c.signal.aborted) {
            setAgents(r.agents.map((a) => (a.id === identity ? detail : a)));
          }
        } else if (!c.signal.aborted) {
          setAgents(r.agents);
        }
        if (identity && !r.agents.some((a) => a.id === identity)) {
          try {
            const legacy = await request<{ tools: Tool[] }>(
              '/tool-hub/executors/' + encodeURIComponent(identity),
              { signal: c.signal },
            );
            if (!c.signal.aborted && legacy.tools[0]) {
              location.hash = '/tools/' + legacy.tools[0].id;
            }
          } catch (reason) {
            if (!c.signal.aborted && !(reason instanceof ApiError && reason.status === 404)) {
              setError('실행 정보를 불러오지 못했습니다. 새로고침해 주세요.');
            }
          }
        }
      } catch {
        if (!c.signal.aborted) {
          setError('에이전트를 불러오지 못했습니다.');
        }
      } finally {
        if (!c.signal.aborted) {
          setLoading(false);
        }
      }
    };
    void load();
    return () => c.abort();
  }, [identity]);
  return (
    <main className="ui02-catalog">
      <PageTitle>{selected?.name || '에이전트'}</PageTitle>
      {error && <p role="alert">{error}</p>}
      {loading ? (
        <LoadingSkeleton layout="list" label="에이전트 불러오는 중" />
      ) : identity ? (
        selected ? (
          <>
            <p>{selected.goal}</p>
            <h2>사용 가능한 툴</h2>
            {selected.tools.map((t) => (
              <a key={t.id} href={'#/tools/' + t.id}>
                {t.name}
              </a>
            ))}
          </>
        ) : (
          !error && <p>에이전트를 찾을 수 없습니다.</p>
        )
      ) : (
        !error &&
        (agents.length ? (
          agents.map((a) => (
            <a key={a.id} href={'#/agents/' + a.id}>
              {a.name}
            </a>
          ))
        ) : (
          <p className="ui02-empty">등록된 에이전트 없음</p>
        ))
      )}
    </main>
  );
};
