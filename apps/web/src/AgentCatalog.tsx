import { useEffect, useState } from 'react';
import { Boxes } from 'lucide-react';
import { PageTitle } from './PageTitle';
import { Pagination, usePagination } from './Pagination';
import { request } from './api';
import { AgentInformation } from './AgentInformation';
import { AgentOperations } from './AgentOperations';
import type { AgentRuntime } from './AgentOperations';
import { brokerStatusView } from './broker-agent-status';
import { frontendOnly, renewalBackend } from './preview';

export type Agent = {
  optional_inputs: string[];
  port_types_from_options?: Partial<Record<'inputs' | 'outputs', Record<string, string>>>;
  id: string;
  label: string;
  inputs: Record<string, string>;
  outputs: Record<string, string>;
  options: Record<string, string[]>;
  engine_runtime?: {
    revision: number;
    sha256: string;
    descriptor: {
      role: string;
      family: string;
      engine: string;
      model_sha256: string;
      source_language: string | null;
      target_language: string | null;
    };
  };
  workflow_binding?: boolean;
};
const types: Record<string, string> = {
  video: '영상',
  audio: '오디오',
  transcript: '전사문',
  subtitle: '자막',
  media_metadata: '영상 정보',
  timeline_map: '타임라인',
  validation_report: '검증 결과',
  decision_result: '판단 결과',
  artifact_manifest: '결과 목록',
  faceswap_session: '합성 세션',
  faceswap_preview: '합성 미리보기',
};
export const AgentCatalog = ({
  query,
  identity,
  onLabel,
}: {
  query: string;
  identity?: string;
  onLabel?: (label: string) => void;
}) => {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [runtimes, setRuntimes] = useState<Record<string, AgentRuntime> | null>(null);
  const [runtimeError, setRuntimeError] = useState('');
  const [loading, setLoading] = useState(true),
    [error, setError] = useState('');
  const selected = agents.find((agent) => agent.id === identity);
  const shown = agents.filter((agent) =>
    `${agent.label} ${agent.id}`.toLocaleLowerCase().includes(query.toLocaleLowerCase()),
  );
  const page = usePagination(shown, query);
  const ports = (value: Record<string, string>) =>
    [...new Set(Object.values(value))].map((type) => types[type] || type).join(' · ');
  useEffect(() => {
    const controller = new AbortController();
    request<{ nodes: Agent[] }>('/settings/node-catalog', { signal: controller.signal })
      .then((data) => {
        if (!controller.signal.aborted) {
          setAgents(data.nodes);
        }
      })
      .catch((reason) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : '에이전트를 불러오지 못했습니다.');
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, []);
  useEffect(() => {
    onLabel?.(selected?.label || '');
  }, [selected?.label, onLabel]);
  useEffect(() => {
    if (!renewalBackend || identity) {
      return;
    }
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const value = await request<{ agents: AgentRuntime[] }>('/admin/agents', {
          signal: controller.signal,
        });
        if (!controller.signal.aborted) {
          setRuntimes(
            Object.fromEntries(value.agents.map((runtime) => [runtime.agent_id, runtime])),
          );
          setRuntimeError('');
        }
      } catch (reason) {
        if (!controller.signal.aborted) {
          setRuntimes(null);
          setRuntimeError(reason instanceof Error ? reason.message : '실행 상태 조회 실패');
        }
      } finally {
        if (!controller.signal.aborted) {
          timer = setTimeout(poll, 3000);
        }
      }
    };
    void poll();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [identity]);
  return (
    <main className="ui02-catalog">
      <PageTitle>{identity ? selected?.label || '에이전트 상세' : '에이전트'}</PageTitle>
      {error && (
        <p role="alert" className="alert">
          {error}
        </p>
      )}
      {loading ? (
        <p role="status">불러오는 중</p>
      ) : identity ? (
        selected ? (
          <>
            <AgentInformation agent={selected} />
            {(frontendOnly || renewalBackend) && <AgentOperations identity={selected.id} />}
          </>
        ) : (
          !error && <p className="ui02-empty">에이전트를 찾을 수 없습니다.</p>
        )
      ) : (
        <div className="ui02-list">
          {page.items.map((agent) => (
            <a
              href={'#/agents/' + agent.id}
              key={agent.id}
              className="ui02-list-item ui02-agent-row"
            >
              <span className="ui02-workflow-icon">
                <Boxes size={21} aria-hidden="true" />
              </span>
              <div className="ui02-list-copy">
                <h2 className="ui02-list-title">{agent.label}</h2>
                <p className="ui02-list-meta">
                  {ports(agent.inputs)} → {ports(agent.outputs)}
                </p>
                {renewalBackend && (
                  <span aria-label={`${agent.label} 상태`}>
                    {runtimeError
                      ? '관측 실패 · 최신 상태 확인 불가'
                      : runtimes?.[agent.id]?.observation_source === 'amqp'
                        ? brokerStatusView(runtimes[agent.id]).title
                        : runtimes?.[agent.id]
                          ? runtimes[agent.id].state
                          : '실행 상태 확인 중'}
                  </span>
                )}
              </div>
              <code className="ui02-revision">{agent.id}</code>
            </a>
          ))}
          {!error && !shown.length && (
            <p className="ui02-empty">{query ? '검색 결과 없음' : '등록된 에이전트 없음'}</p>
          )}
        </div>
      )}
      {!identity && !loading && !error && <Pagination {...page} />}
    </main>
  );
};
