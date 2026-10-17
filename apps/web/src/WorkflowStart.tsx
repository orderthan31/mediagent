import { useEffect, useRef, useState } from 'react';
import { request } from './api';
import { frontendOnly } from './preview';
import { stageLabels } from './video-api';
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
  const [recovery, setRecovery] = useState(false);
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
    recovery_enabled: recovery,
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
      if (frontendOnly) {
        location.hash = `/jobs/${ticket.id}`;
      } else {
        setTicketId(ticket.id);
      }
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
    return <WorkflowTickets key={ticketId} work recovery={recovery} initialTicketId={ticketId} />;
  }
  return (
    <main className="serving-page workflow-start">
      <div className="serving-heading">
        <h1>작업 추가</h1>
        <Button variant="quiet" disabled={loading || busy} onClick={() => void load()}>
          새로고침
        </Button>
      </div>
      {listError && (
        <p role="alert" className="alert">
          {listError}
        </p>
      )}
      {listError && listsConfirmed && <p className="list-query-stale">이전 조회값 · 최신 미확인</p>}
      {error && (
        <p role="alert" className="alert">
          {error}
        </p>
      )}
      {loading ? (
        <p role="status">불러오는 중</p>
      ) : (
        <div className="work-entry-layout">
          <div className="work-entry-fields">
            <section className="entry-selection" aria-labelledby="entry-selection-title">
              <h2 id="entry-selection-title">작업 구성</h2>
              <label className="form-row">
                <span>원본</span>
                <div>
                  <select
                    aria-label="원본"
                    value={assetId}
                    disabled={busy}
                    onChange={(event) => {
                      setAssetId(event.target.value);
                      invalidate();
                    }}
                  >
                    <option value="">원본 선택</option>
                    {assets.map((asset) => (
                      <option key={asset.asset_id} value={asset.asset_id}>
                        {asset.original_filename}
                      </option>
                    ))}
                  </select>
                  {!assets.length && !listError && (
                    <p className="form-note">
                      등록된 원본이 없습니다. <a href="#/">원본 등록</a>
                    </p>
                  )}
                </div>
              </label>
              <label className="form-row">
                <span>워크플로우</span>
                <div>
                  <select
                    aria-label="워크플로우"
                    value={definitionId}
                    disabled={busy}
                    onChange={(event) => void inspect(event.target.value)}
                  >
                    <option value="">워크플로우 선택</option>
                    {definitions.map((definition) => (
                      <option key={definition.id} value={definition.id}>
                        {definition.name}
                      </option>
                    ))}
                  </select>
                  {!definitions.length && !listError && (
                    <p className="form-note">
                      저장된 워크플로우가 없습니다. <a href="#/workflows/new">워크플로우 추가</a>
                    </p>
                  )}
                </div>
              </label>
              <details className="entry-options">
                <summary>추가 옵션</summary>
                <label className="serving-check">
                  <input
                    type="checkbox"
                    checked={recovery}
                    disabled={busy}
                    onChange={(event) => {
                      setRecovery(event.target.checked);
                      invalidate();
                    }}
                  />
                  복구 지원
                </label>
              </details>
            </section>
            {busy && <p role="status">확인 중</p>}
            {inspection && (
              <section className="entry-workflow" aria-labelledby="entry-workflow-title">
                <div className="section-heading">
                  <h2 id="entry-workflow-title">처리 흐름</h2>
                  <a href={'#/workflows/' + definitionId}>워크플로우 열기</a>
                </div>
                {!inspection.supported && (
                  <div role="alert">
                    {inspection.reasons.map((reason, i) => (
                      <p key={i}>{reason.message}</p>
                    ))}
                  </div>
                )}
                <ol className="entry-steps">
                  {inspection.summary.map((node) => (
                    <li key={node.id}>
                      <span>{stageLabels[node.type] || node.type}</span>
                      {node.model && <small>{node.model.name}</small>}
                      {node.model_error && <p role="alert">{node.model_error}</p>}
                      {node.type === 'select' && (
                        <label>
                          분기
                          <select
                            aria-label={`분기 ${node.id} 선택`}
                            disabled={busy}
                            value={choices[node.id] || 'a'}
                            onChange={(event) => {
                              setChoices({ ...choices, [node.id]: event.target.value });
                              invalidate();
                            }}
                          >
                            <option value="a">a</option>
                            <option value="b">b</option>
                            <option value="both">둘 다</option>
                          </select>
                        </label>
                      )}
                    </li>
                  ))}
                </ol>
              </section>
            )}
          </div>
          <aside className="work-entry-summary" aria-labelledby="entry-summary-title">
            <h2 id="entry-summary-title">작업 요약</h2>
            <dl>
              <div>
                <dt>원본</dt>
                <dd>
                  {assets.find((asset) => asset.asset_id === assetId)?.original_filename ||
                    '선택 전'}
                </dd>
              </div>
              <div>
                <dt>워크플로우</dt>
                <dd>
                  {definitions.find((definition) => definition.id === definitionId)?.name ||
                    '선택 전'}
                </dd>
              </div>
              <div>
                <dt>비용</dt>
                <dd>{plan ? plan.notice : '확인 전'}</dd>
              </div>
            </dl>
            {plan && (
              <>
                {plan.paid_roles.length > 0 && (
                  <label className="serving-check">
                    <input
                      type="checkbox"
                      checked={paid}
                      disabled={busy}
                      onChange={(event) => setPaid(event.target.checked)}
                    />
                    {plan.paid_roles.join(', ')} 호출에 따른 비용 발생 가능성을 확인했습니다.
                  </label>
                )}
                <Button
                  disabled={busy || (plan.paid_roles.length > 0 && !paid)}
                  onClick={() => void create()}
                >
                  작업 생성
                </Button>
                <Button variant="quiet" disabled={busy} onClick={() => void preview()}>
                  다시 확인
                </Button>
              </>
            )}
            {!plan && (
              <Button
                disabled={busy || !assetId || !inspection?.supported || !inspection.model_ready}
                onClick={() => void preview()}
              >
                실행 전 확인
              </Button>
            )}
          </aside>
        </div>
      )}
    </main>
  );
};
