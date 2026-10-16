import { useEffect, useRef, useState } from 'react';
import { request } from './api';
import { jsonPost, type VideoAsset } from './video-api';
import { Button } from './hangyeol/primitives/button';
import { WorkflowTickets } from './WorkflowTickets';
import type { RegisteredVersion } from './registered-models';
import './serving.css';
import './workflow-tickets.css';

type Inspection = {
  supported: boolean;
  contract: string | null;
  definition_id: string;
  definition_revision: number;
  model_ready: boolean;
  runtime_connected: boolean;
  summary: {
    id: string;
    type: string;
    options: Record<string, string>;
    inputs: unknown;
    model?: RegisteredVersion;
    model_error?: string;
  }[];
  reasons: { message: string; node_id: string | null }[];
};
type StartPlan = {
  token: string;
  paid_roles: string[];
  notice: string;
  settings: Record<string, unknown>;
  eligible_steps: string[];
  model_bindings: Record<string, RegisteredVersion>;
  steps: { id: string; type: string; selected: boolean }[];
};
export const WorkflowStart = () => {
  const [assets, setAssets] = useState<VideoAsset[]>([]);
  const [definitions, setDefinitions] = useState<{ id: string; name: string; revision: number }[]>(
    [],
  );
  const [assetId, setAssetId] = useState('');
  const [definitionId, setDefinitionId] = useState('');
  const [inspection, setInspection] = useState<Inspection | null>(null);
  const [choices, setChoices] = useState<Record<string, string>>({});
  const [plan, setPlan] = useState<StartPlan | null>(null);
  const [paid, setPaid] = useState(false);
  const [ticketId, setTicketId] = useState('');
  const [requestId, setRequestId] = useState(() => crypto.randomUUID());
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [listError, setListError] = useState('');
  const [listsConfirmed, setListsConfirmed] = useState(false);
  const generation = useRef(0);
  const invalidate = () => {
    setPlan(null);
    setPaid(false);
    setRequestId(crypto.randomUUID());
  };
  const load = async () => {
    ++generation.current;
    invalidate();
    setInspection(null);
    setDefinitionId('');
    setLoading(true);
    setListError('');
    try {
      const [videos, workflows] = await Promise.all([
        request<{ videos: VideoAsset[] }>('/videos'),
        request<{ definitions: { id: string; name: string; revision: number }[] }>(
          '/settings/workflow-definitions',
        ),
      ]);
      setAssets(videos.videos);
      setDefinitions(workflows.definitions);
      setListsConfirmed(true);
    } catch (e) {
      setListError(
        e instanceof Error ? e.message : '목록 조회 실패. 정상/빈 목록으로 간주하지 않습니다.',
      );
    } finally {
      setLoading(false);
    }
  };
  const inspect = async (identity: string) => {
    const current = ++generation.current;
    setDefinitionId(identity);
    setInspection(null);
    invalidate();
    setError('');
    if (!identity) {
      return;
    }
    const selected = definitions.find((d) => d.id === identity);
    if (!selected) {
      return;
    }
    setBusy(true);
    try {
      const result = await jsonPost<Inspection>('/settings/work-entry/inspect', {
        definition_id: identity,
        definition_revision: selected.revision,
      });
      if (generation.current === current) {
        setInspection(result);
        setChoices(
          Object.fromEntries(
            result.summary
              .filter((n) => n.type === 'select')
              .map((n) => [n.id, n.options.selection || 'a']),
          ),
        );
      }
    } catch (e) {
      if (generation.current === current) {
        setError(e instanceof Error ? e.message : '저장 워크플로우를 새로 읽으세요.');
      }
    } finally {
      if (generation.current === current) {
        setBusy(false);
      }
    }
  };
  const selection = () => ({
    asset_id: assetId,
    definition_id: definitionId,
    definition_revision: inspection?.definition_revision,
    options: {
      source_language: 'auto',
      target_language: 'ko',
      video_description: '',
      branch_choices: choices,
    },
  });
  const preview = async () => {
    if (!assetId || !inspection?.supported || !inspection.model_ready) {
      return;
    }
    setBusy(true);
    setError('');
    setPlan(null);
    setPaid(false);
    try {
      setPlan(await jsonPost<StartPlan>('/settings/work-entry/preview', selection()));
    } catch (e) {
      setError(e instanceof Error ? e.message : '입력/모델/서빙을 새로 확인하세요.');
    } finally {
      setBusy(false);
    }
  };
  const create = async () => {
    if (!plan) {
      return;
    }
    setBusy(true);
    setError('');
    try {
      const ticket = await jsonPost<{ id: string }>('/settings/work-entry/create', {
        ...selection(),
        request_id: requestId,
        token: plan.token,
        paid_confirmed: paid,
      });
      setTicketId(ticket.id);
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : '확인한 계획이 달라 티켓을 만들지 않았습니다. 다시 확인하세요.',
      );
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => {
    void load();
  }, []);
  if (ticketId) {
    return <WorkflowTickets key={ticketId} work initialTicketId={ticketId} />;
  }
  return (
    <main className="serving-page workflow-tickets workflow-start">
      <div className="serving-heading">
        <div>
          <p className="workspace-eyebrow">작업</p>
          <h1>작업 시작</h1>
        </div>
        <Button variant="secondary" disabled={loading || busy} onClick={() => void load()}>
          목록 새로 읽기
        </Button>
      </div>
      <p>
        영상과 저장 워크플로우를 고르고 흐름·노드 설정을 확인하세요. 계획/비용 확인 후 티켓을 만들며
        실행은 별도입니다.
      </p>
      {listError && (
        <p role="alert" className="alert list-query-error">
          목록 조회 실패 · {listError}
        </p>
      )}
      {listError && listsConfirmed && (
        <p className="list-query-stale">
          이전 조회값 · 최신 미확인. 영상·워크플로우 목록을 다시 읽어 확인하세요.
        </p>
      )}
      {error && (
        <p role="alert" className="alert">
          {error}
        </p>
      )}
      {loading ? (
        <p role="status">영상·워크플로우 읽는 중</p>
      ) : (
        <section className="ticket-panel">
          <h2>작업 대상</h2>
          <div className="serving-grid">
            <label>
              입력 영상
              <select
                aria-label="입력 영상"
                value={assetId}
                disabled={busy}
                onChange={(e) => {
                  setAssetId(e.target.value);
                  invalidate();
                }}
              >
                <option value="">영상 선택</option>
                {assets.map((a) => (
                  <option key={a.asset_id} value={a.asset_id}>
                    {a.original_filename}
                  </option>
                ))}
              </select>
            </label>
            <label>
              저장 워크플로우
              <select
                aria-label="저장 워크플로우"
                value={definitionId}
                disabled={busy}
                onChange={(e) => void inspect(e.target.value)}
              >
                <option value="">워크플로우 선택</option>
                {definitions.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name} · r{d.revision}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {listsConfirmed && !listError && definitions.length === 0 && (
            <p>
              저장 워크플로우 없음 · <a href="#/workflow-editor">워크플로우 구성</a>에서 먼저
              저장하세요.
            </p>
          )}
          {listsConfirmed && !listError && assets.length === 0 && (
            <p>
              입력 영상 없음 · <a href="#/">영상 보관함</a>에서 등록하세요.
            </p>
          )}
        </section>
      )}
      {busy && <p role="status">흐름·설정 확인 중</p>}
      {inspection && (
        <section className="ticket-panel">
          <h2>흐름과 노드 설정</h2>
          <p>
            정의 r{inspection.definition_revision} · {inspection.summary.length}개 노드 ·{' '}
            <a href="#/workflow-editor">구성에서 상세 수정</a>
          </p>
          {!inspection.supported && (
            <div role="alert">
              {inspection.reasons.map((r, i) => (
                <p key={i}>
                  {r.node_id ? `${r.node_id}: ` : ''}
                  {r.message}
                </p>
              ))}
            </div>
          )}
          <ol>
            {inspection.summary.map((node) => (
              <li key={node.id}>
                <strong>{node.id}</strong> · {node.type}
                {node.model && (
                  <p>
                    {node.model.name} · r{node.model.revision} · {node.model.provider}/
                    {node.model.model} · 실연결 미확인
                  </p>
                )}
                {node.model_error && <p role="alert">{node.model_error}</p>}
                {node.type === 'select' && (
                  <label>
                    수동 분기 {node.id}
                    <select
                      aria-label={`분기 ${node.id} 선택`}
                      disabled={busy}
                      value={choices[node.id] || 'a'}
                      onChange={(e) => {
                        setChoices({ ...choices, [node.id]: e.target.value });
                        invalidate();
                      }}
                    >
                      <option value="a">a</option>
                      <option value="b">b</option>
                      <option value="both">둘 다</option>
                    </select>
                  </label>
                )}
                <details>
                  <summary>처리 옵션·연결</summary>
                  <pre>
                    {JSON.stringify({ options: node.options, inputs: node.inputs }, null, 2)}
                  </pre>
                </details>
              </li>
            ))}
          </ol>
          <Button
            disabled={busy || !inspection.supported || !inspection.model_ready || !assetId}
            onClick={() => void preview()}
          >
            계획·비용 확인으로
          </Button>
        </section>
      )}
      {plan && (
        <section className="ticket-panel start-plan">
          <h2>계획·비용 명시 확인</h2>
          <p>{plan.notice}</p>
          <p>이번 미실행 대상: {plan.eligible_steps.join(' → ')}</p>
          <p>
            이번 모델 호출 역할: {plan.paid_roles.join(', ') || '해당 없음'} · 이후 판단/검수 뒤에는
            새 확인이 필요합니다.
          </p>
          {Object.values(plan.model_bindings).map((binding) => (
            <p key={`${binding.model_id}@${binding.revision}`}>
              고정 모델 {binding.name} · r{binding.revision} · {binding.provider}/{binding.model}
            </p>
          ))}
          <label className="serving-check">
            <input
              type="checkbox"
              aria-label="계획의 모델 호출 확인"
              checked={paid}
              disabled={busy || plan.paid_roles.length === 0}
              onChange={(e) => setPaid(e.target.checked)}
            />
            이 계획의 모델 호출/비용 역할을 명시 확인
          </label>
          <Button
            disabled={busy || (plan.paid_roles.length > 0 && !paid)}
            onClick={() => void create()}
          >
            확인하고 티켓 만들기
          </Button>
        </section>
      )}
    </main>
  );
};
