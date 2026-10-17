import { useEffect, useState } from 'react';
import { Boxes } from 'lucide-react';
import { request } from './api';
import { AgentInformation } from './AgentInformation';

export type Agent = {
  optional_inputs: string[];
  port_types_from_options?: Partial<Record<'inputs' | 'outputs', Record<string, string>>>;
  id: string;
  label: string;
  inputs: Record<string, string>;
  outputs: Record<string, string>;
  options: Record<string, string[]>;
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
  const [loading, setLoading] = useState(true),
    [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    request<{ nodes: Agent[] }>('/settings/node-catalog', { signal: controller.signal })
      .then((data) => {
        if (!controller.signal.aborted) setAgents(data.nodes);
      })
      .catch((reason) => {
        if (!controller.signal.aborted)
          setError(reason instanceof Error ? reason.message : '에이전트를 불러오지 못했습니다.');
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, []);
  const selected = agents.find((agent) => agent.id === identity);
  useEffect(() => {
    onLabel?.(selected?.label || '');
  }, [selected?.label, onLabel]);
  const shown = agents.filter((agent) =>
    `${agent.label} ${agent.id}`.toLocaleLowerCase().includes(query.toLocaleLowerCase()),
  );
  const ports = (value: Record<string, string>) =>
    [...new Set(Object.values(value))].map((type) => types[type] || type).join(' · ');
  return (
    <main className="ui02-catalog">
      <div className="ui02-page-heading">
        <h1>{identity ? selected?.label || '에이전트 상세' : '에이전트'}</h1>
        {!identity && !loading && !error && <span>{agents.length}</span>}
      </div>
      {error && (
        <p role="alert" className="alert">
          {error}
        </p>
      )}
      {loading ? (
        <p role="status">불러오는 중</p>
      ) : identity ? (
        selected ? (
          <AgentInformation agent={selected} />
        ) : (
          !error && <p className="ui02-empty">에이전트를 찾을 수 없습니다.</p>
        )
      ) : (
        <div className="ui02-list">
          {shown.map((agent) => (
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
              </div>
              <code className="ui02-revision">{agent.id}</code>
            </a>
          ))}
          {!error && !shown.length && (
            <p className="ui02-empty">{query ? '검색 결과 없음' : '등록된 에이전트 없음'}</p>
          )}
        </div>
      )}
    </main>
  );
};
