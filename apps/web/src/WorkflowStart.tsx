import { useEffect, useRef, useState } from 'react';
import { PageTitle } from './PageTitle';
import { LoadingSkeleton } from './LoadingSkeleton';
import { mediaUrl, request } from './api';
import { frontendOnly, renewalBackend } from './preview';
import { jsonPost, type VideoAsset } from './video-api';
import { Button } from './hangyeol/primitives/button';
import { WorkflowTickets } from './WorkflowTickets';
import { WorkflowCanvas, type CanvasDefinition, type CanvasSpec } from './WorkflowCanvas';
import type { RegisteredVersion } from './registered-models';
import { useWorkspaceAuth } from './AuthGate';
import './serving.css';
import './workflow-tickets.css';

type Inspection = {
  supported: boolean;
  definition_revision: number;
  model_ready: boolean;
  summary: {
    id: string;
    type: string;
    options: Record<string, string>;
    model?: RegisteredVersion;
    model_error?: string;
  }[];
  reasons: { message: string; node_id: string | null }[];
};
type StartPlan = {
  token: string;
  paid_roles: string[];
  notice: string;
};
export const WorkflowStart = () => {
  const auth = useWorkspaceAuth();
  const administrator = frontendOnly || auth?.session.user?.role === 'admin';
  const entryPath = renewalBackend ? '/work-entry' : '/settings/work-entry';
  const [assets, setAssets] = useState<VideoAsset[]>([]);
  const [definitions, setDefinitions] = useState<{ id: string; name: string; revision: number }[]>(
    [],
  );
  const [catalog, setCatalog] = useState<CanvasSpec[]>([]);
  const [assetId, setAssetId] = useState('');
  const [definitionId, setDefinitionId] = useState('');
  const [definition, setDefinition] = useState<CanvasDefinition | null>(null);
  const [selected, setSelected] = useState('');
  const [inspection, setInspection] = useState<Inspection | null>(null);
  const [choices, setChoices] = useState<Record<string, string>>({});
  const [plan, setPlan] = useState<StartPlan | null>(null);
  const [paid, setPaid] = useState(false);
  const [sourceLanguage, setSourceLanguage] = useState('auto');
  const [targetLanguage, setTargetLanguage] = useState('ko');
  const [transcript, setTranscript] = useState('');
  const [ticketId, setTicketId] = useState('');
  const [requestId, setRequestId] = useState(() => crypto.randomUUID());
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [listError, setListError] = useState('');
  const generation = useRef(0);
  const asset = assets.find((row) => row.asset_id === assetId);
  const selectedNode = inspection?.summary.find((row) => row.id === selected);
  const invalidate = () => {
    setPlan(null);
    setPaid(false);
    setRequestId(crypto.randomUUID());
  };
  const load = async () => {
    setLoading(true);
    try {
      const [videos, workflows, nodes] = await Promise.all([
        request<{ videos: VideoAsset[] }>('/videos'),
        request<{ definitions: { id: string; name: string; revision: number }[] }>(
          renewalBackend ? '/work-entry/workflows' : '/settings/workflow-definitions',
        ),
        request<{ nodes: CanvasSpec[] }>(
          renewalBackend ? '/work-entry/catalog' : '/settings/node-catalog',
        ),
      ]);
      setAssets(videos.videos);
      setDefinitions(workflows.definitions);
      setCatalog(nodes.nodes);
      setListError('');
    } catch (e) {
      setListError(e instanceof Error ? e.message : '목록을 불러오지 못했습니다.');
    } finally {
      setLoading(false);
    }
  };
  const inspect = async (identity: string) => {
    const current = ++generation.current;
    setDefinitionId(identity);
    setInspection(null);
    setDefinition(null);
    setSelected('');
    invalidate();
    setError('');
    if (!identity) {
      return;
    }
    const saved = definitions.find((row) => row.id === identity);
    if (!saved) {
      return;
    }
    setBusy(true);
    try {
      const [result, graph] = await Promise.all([
        jsonPost<Inspection>(entryPath + '/inspect', {
          definition_id: identity,
          definition_revision: saved.revision,
        }),
        request<CanvasDefinition>(
          renewalBackend
            ? `/work-entry/workflows/${identity}?revision=${saved.revision}`
            : '/settings/workflow-definitions/' + identity,
        ),
      ]);
      if (graph.revision !== result.definition_revision) {
        throw new Error('워크플로우가 변경됐습니다. 다시 선택해 주세요.');
      }
      if (generation.current === current) {
        setInspection(result);
        setDefinition(graph);
        setChoices(
          Object.fromEntries(
            result.summary
              .filter((node) => node.type === 'select')
              .map((node) => [node.id, node.options.selection || 'a']),
          ),
        );
      }
    } catch (e) {
      if (generation.current === current) {
        setError(e instanceof Error ? e.message : '워크플로우를 불러오지 못했습니다.');
      }
    } finally {
      if (generation.current === current) {
        setBusy(false);
      }
    }
  };
  const selection = () => ({
    asset_id: assetId,
    recovery_enabled: false,
    definition_id: definitionId,
    definition_revision: inspection?.definition_revision,
    options: {
      source_language: sourceLanguage,
      target_language: targetLanguage,
      ...(definition?.inputs.transcript === 'transcript'
        ? { transcript: JSON.parse(transcript) }
        : {}),
      video_description: '',
      branch_choices: choices,
    },
  });
  const preview = async () => {
    if (busy || !assetId || !inspection?.supported || !inspection.model_ready) {
      return;
    }
    setBusy(true);
    setError('');
    setPlan(null);
    setPaid(false);
    try {
      setPlan(await jsonPost<StartPlan>(entryPath + '/preview', selection()));
    } catch (e) {
      setError(e instanceof Error ? e.message : '입력과 모델 설정을 확인해 주세요.');
    } finally {
      setBusy(false);
    }
  };
  const create = async () => {
    if (busy || !plan || (plan.paid_roles.length > 0 && !paid)) {
      return;
    }
    setBusy(true);
    setError('');
    try {
      const ticket = await jsonPost<{ id: string }>(entryPath + '/create', {
        ...selection(),
        request_id: requestId,
        token: plan.token,
        paid_confirmed: paid,
      });
      if (frontendOnly || renewalBackend) {
        location.hash = `/jobs/${ticket.id}`;
      } else {
        setTicketId(ticket.id);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : '작업을 만들지 못했습니다.');
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => {
    void load();
    return () => {
      ++generation.current;
    };
  }, []);
  if (ticketId) {
    return <WorkflowTickets key={ticketId} work recovery={false} initialTicketId={ticketId} />;
  }
  return (
    <main className="serving-page workflow-start">
      <PageTitle>작업 추가</PageTitle>
      {listError && (
        <p role="alert" className="alert">
          {listError}
        </p>
      )}
      {error && (
        <p role="alert" className="alert">
          {error}
        </p>
      )}
      {loading ? (
        <LoadingSkeleton layout="form" label="작업 구성 불러오는 중" />
      ) : (
        <div className="work-entry-layout">
          <section className="entry-selection" aria-label="작업 구성">
            <label className="form-row">
              <span>원문 언어</span>
              <select
                aria-label="원문 언어"
                value={sourceLanguage}
                disabled={busy}
                onChange={(e) => {
                  setSourceLanguage(e.target.value);
                  invalidate();
                }}
              >
                {['auto', 'en', 'ko', 'ja', 'zh', 'de', 'fr', 'es'].map((lang) => (
                  <option key={lang} value={lang}>
                    {lang === 'auto' ? '자동 감지' : lang}
                  </option>
                ))}
              </select>
            </label>
            <label className="form-row">
              <span>대상 언어</span>
              <select
                aria-label="대상 언어"
                value={targetLanguage}
                disabled={busy}
                onChange={(e) => {
                  setTargetLanguage(e.target.value);
                  invalidate();
                }}
              >
                {['ko', 'en', 'ja', 'zh', 'de', 'fr', 'es'].map((lang) => (
                  <option key={lang} value={lang}>
                    {lang}
                  </option>
                ))}
              </select>
            </label>
            {definition?.inputs.transcript === 'transcript' && (
              <label className="form-row">
                <span>번역할 자막 JSON</span>
                <textarea
                  aria-label="번역할 자막 JSON"
                  value={transcript}
                  disabled={busy}
                  onChange={(e) => {
                    setTranscript(e.target.value);
                    invalidate();
                  }}
                  placeholder='[{"start":0,"end":1,"text":"자막"}]'
                />
                <small>
                  원본은 작업 출처로 보존하고, 입력한 자막과 시각을 티켓에 고정합니다. 최대
                  100개/16KB.
                </small>
              </label>
            )}
            <label className="form-row">
              <span>원본</span>
              <div>
                <select
                  aria-label="원본"
                  value={assetId}
                  disabled={busy || !!listError}
                  onChange={(event) => {
                    setAssetId(event.target.value);
                    invalidate();
                  }}
                >
                  <option value="">원본 선택</option>
                  {assets.map((row) => (
                    <option key={row.asset_id} value={row.asset_id}>
                      {row.original_filename}
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
                  disabled={busy || !!listError}
                  onChange={(event) => void inspect(event.target.value)}
                >
                  <option value="">워크플로우 선택</option>
                  {definitions.map((row) => (
                    <option key={row.id} value={row.id}>
                      {row.name}
                    </option>
                  ))}
                </select>
                {!definitions.length && !listError && (
                  <p className="form-note">
                    {administrator ? (
                      <>
                        저장된 워크플로우가 없습니다. <a href="#/workflows/new">워크플로우 추가</a>
                      </>
                    ) : (
                      '사용 가능한 워크플로우가 없습니다. 관리자에게 문의해 주세요.'
                    )}
                  </p>
                )}
              </div>
            </label>
          </section>
          {busy && <p role="status">확인 중</p>}
          {definition && inspection && (
            <section className="entry-workflow" aria-label="선택한 워크플로우">
              <div className="section-heading">
                <h2>
                  {definition.name} · r{definition.revision}
                </h2>
                {administrator && <a href={'#/workflows/' + definitionId}>워크플로우 열기</a>}
              </div>
              {!inspection.supported && (
                <div role="alert">
                  {inspection.reasons.map((reason, index) => (
                    <p key={index}>{reason.message}</p>
                  ))}
                </div>
              )}
              <WorkflowCanvas
                key={definition.id}
                definition={definition}
                catalog={catalog}
                inputLabel={asset?.original_filename || '입력 미디어 선택 전'}
                inputThumbnail={asset ? mediaUrl(`/videos/${asset.asset_id}/thumbnail`) : undefined}
                onSelect={setSelected}
                detailsLabel="선택한 노드 정보"
                details={
                  selected === '$input' && asset ? (
                    <video
                      controls
                      playsInline
                      preload="none"
                      className="entry-media-preview"
                      poster={mediaUrl(`/videos/${asset.asset_id}/thumbnail`)}
                      src={mediaUrl(`/videos/${asset.asset_id}/stream`)}
                    />
                  ) : selectedNode ? (
                    <div className="entry-node-info">
                      {selectedNode.model && <p>모델: {selectedNode.model.name}</p>}
                      {selectedNode.model_error && <p role="alert">{selectedNode.model_error}</p>}
                      <dl>
                        {Object.entries(selectedNode.options).map(([key, value]) => (
                          <div key={key}>
                            <dt>{key}</dt>
                            <dd>{value}</dd>
                          </div>
                        ))}
                      </dl>
                      {selectedNode.type === 'select' && (
                        <label>
                          분기
                          <select
                            aria-label={`분기 ${selectedNode.id} 선택`}
                            disabled={busy}
                            value={choices[selectedNode.id] || 'a'}
                            onChange={(event) => {
                              setChoices({ ...choices, [selectedNode.id]: event.target.value });
                              invalidate();
                            }}
                          >
                            <option value="a">a</option>
                            <option value="b">b</option>
                            <option value="both">둘 다</option>
                          </select>
                        </label>
                      )}
                    </div>
                  ) : undefined
                }
              />
            </section>
          )}
          <div className="work-entry-actions page-actions">
            {plan && <p>{plan.notice}</p>}
            {plan && plan.paid_roles.length > 0 && (
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
            {plan ? (
              <Button
                disabled={busy || (plan.paid_roles.length > 0 && !paid)}
                onClick={() => void create()}
              >
                작업 생성
              </Button>
            ) : (
              <Button
                disabled={
                  busy ||
                  !!listError ||
                  !assetId ||
                  !inspection?.supported ||
                  !inspection.model_ready
                }
                onClick={() => void preview()}
              >
                실행 전 확인
              </Button>
            )}
          </div>
        </div>
      )}
    </main>
  );
};
