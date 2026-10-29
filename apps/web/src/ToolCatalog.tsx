import { useEffect, useState } from 'react';
import { ApiError, request } from './api';
import { PageTitle } from './PageTitle';
import { LoadingSkeleton } from './LoadingSkeleton';
import { canonicalAgentIdentity, agentStateLabel } from './agent-hub.mjs';

type Tool = {
  id: string;
  name: string;
  inputs: Record<string, string>;
  outputs: Record<string, string>;
  settings: string[];
  requires_model: boolean;
  availability: string;
};
type AgentExecution = {
  task_id: string;
  job_id: string;
  ticket_number: number;
  status: string;
  completed_calls: number;
  created_at: string;
  completed_at: string | null;
};
type Agent = {
  id: string;
  name: string;
  goal: string;
  tools: Tool[];
  status: string;
  instances: number | null;
  availability: string;
  executions: AgentExecution[];
};
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
  const requestedIdentity = canonicalAgentIdentity(identity);
  const selected = agents.find((a) => a.id === requestedIdentity);
  useEffect(() => {
    const c = new AbortController();
    let sequence = 0;
    setLoading(true);
    setError('');
    const load = async () => {
      const current = ++sequence;
      const valid = () => !c.signal.aborted && current === sequence;
      try {
        const r = await request<{ agents: Agent[] }>('/agent-hub/agents', { signal: c.signal });
        if (valid()) {
          setError('');
        }
        if (requestedIdentity && r.agents.some((a) => a.id === requestedIdentity)) {
          const detail = await request<Agent>(
            '/agent-hub/agents/' + encodeURIComponent(requestedIdentity),
            {
              signal: c.signal,
            },
          );
          if (valid()) {
            setAgents(r.agents.map((a) => (a.id === requestedIdentity ? detail : a)));
          }
        } else if (valid()) {
          setAgents(r.agents);
        }
        if (
          requestedIdentity &&
          !r.agents.some((a) => a.id === requestedIdentity) &&
          !['transcribe', 'translate'].includes(requestedIdentity)
        ) {
          try {
            const legacy = await request<{ tools: Tool[] }>(
              '/tool-hub/executors/' + encodeURIComponent(requestedIdentity),
              { signal: c.signal },
            );
            if (valid() && legacy.tools[0]) {
              location.hash = '/tools/' + legacy.tools[0].id;
            }
          } catch (reason) {
            if (valid() && !(reason instanceof ApiError && reason.status === 404)) {
              setError('실행 정보를 불러오지 못했습니다. 새로고침해 주세요.');
            }
          }
        }
      } catch {
        if (valid()) {
          setError('최근 상태를 불러오지 못했습니다. 새로고침해 주세요.');
        }
      } finally {
        if (valid()) {
          setLoading(false);
        }
      }
    };
    void load();
    const timer = window.setInterval(() => void load(), 3000);
    return () => {
      c.abort();
      window.clearInterval(timer);
    };
  }, [requestedIdentity]);
  return (
    <main className="ui02-catalog">
      <PageTitle>{selected?.name || '에이전트'}</PageTitle>
      {error && (
        <p role="alert">
          {error}
          {agents.length > 0 && ' 아래는 마지막으로 확인한 정보입니다.'}
        </p>
      )}
      {loading ? (
        <LoadingSkeleton layout="list" label="에이전트 불러오는 중" />
      ) : identity ? (
        selected ? (
          <>
            <p>{selected.goal}</p>
            <p role="status">
              {error ? '확인 필요' : agentStateLabel(selected.status)}
              {!error && selected.instances !== null && ` · 실행 중 ${selected.instances}개`}
            </p>
            <h2>사용 가능한 툴</h2>
            <div className="ui02-list">
              {selected.tools.map((t) => (
                <a className="ui02-list-item" key={t.id} href={'#/tools/' + t.id}>
                  <span className="ui02-list-title">{t.name}</span>
                </a>
              ))}
            </div>
            <h2>작업 기록</h2>
            <div className="ui02-list">
              {selected.executions.map((execution) => (
                <a
                  className="ui02-list-item"
                  key={execution.task_id}
                  href={'#/jobs/' + execution.job_id}
                >
                  <div className="ui02-list-copy">
                    <h3 className="ui02-list-title">작업 #{execution.ticket_number}</h3>
                    <p className="ui02-list-meta">
                      {agentStateLabel(execution.status)} · 모델 응답 {execution.completed_calls}회
                    </p>
                  </div>
                  <span>작업 보기</span>
                </a>
              ))}
              {selected.executions.length === 0 && <p>아직 수행한 작업이 없습니다.</p>}
            </div>
            <a href="#/agents">에이전트 목록</a>
          </>
        ) : (
          !error && <p>에이전트를 찾을 수 없습니다.</p>
        )
      ) : (
        <div className="ui02-list">
          {agents.map((a) => (
            <a className="ui02-list-item" key={a.id} href={'#/agents/' + a.id}>
              <div className="ui02-list-copy">
                <h2 className="ui02-list-title">{a.name}</h2>
                <p className="ui02-list-meta">{a.goal}</p>
              </div>
              <span>{error ? '확인 필요' : agentStateLabel(a.status)}</span>
            </a>
          ))}
          {!error && agents.length === 0 && <p className="ui02-empty">등록된 에이전트 없음</p>}
        </div>
      )}
    </main>
  );
};
