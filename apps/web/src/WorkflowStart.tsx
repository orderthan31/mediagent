import { startSavedJob } from './job-start.mjs';
import { frozenGoalLanguages } from './goal-languages';
import { languageLabel } from './language-label';
import { WorkflowInputs } from './WorkflowInputs';
import { FaceWorkflowInputs } from './FaceWorkflowInputs';
import { normalInputReady, type InputChoice, type NormalInputValue } from './normal-inputs';
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
    model_required?: boolean;
    model_ref?: { model_id: string; revision: number };
  }[];
  reasons: { message: string; node_id: string | null }[];
};
type StartPlan = {
  token: string;
  paid_roles: string[];
  model_call_budgets?: {
    node_id: string;
    role: string;
    max_calls: number;
    minimum_audio_calls: number | null;
  }[];
  vocal_source_policy?: {
    id: string;
    max_source_seconds: number;
    request_max_seconds?: number;
    request_max_audio_bytes?: number;
  };
  notice: string;
  selected_inputs?: {
    input: string;
    kind: string;
    language?: string;
    segments?: number;
    job_id?: string;
  }[];
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
  const [assetId, setAssetId] = useState(
    () => new URLSearchParams(location.hash.split('?')[1] || '').get('target') || '',
  );
  const [definitionId, setDefinitionId] = useState('');
  const [definition, setDefinition] = useState<CanvasDefinition | null>(null);
  const [selected, setSelected] = useState('');
  const [inspection, setInspection] = useState<Inspection | null>(null);
  const [choices, setChoices] = useState<Record<string, string>>({});
  const [plan, setPlan] = useState<StartPlan | null>(null);

  const [sourceLanguage, setSourceLanguage] = useState('auto');
  const [targetLanguage, setTargetLanguage] = useState('ko');
  const [transcript, setTranscript] = useState('');
  const [normalInput, setNormalInput] = useState<NormalInputValue>(() => {
    const photo = new URLSearchParams(location.hash.split('?')[1] || '').get('photo');
    return photo
      ? {
          face_input: {
            photo_asset_id: photo,
            engine_revision: null,
            engine_sha256: null,
            settings_revision: 1,
            reference_frame: 1,
          },
        }
      : {};
  });
  const [inputChoices, setInputChoices] = useState<InputChoice[]>([]);
  const [inputChoicesFor, setInputChoicesFor] = useState('');
  const [inputLoading, setInputLoading] = useState(false);
  const [inputError, setInputError] = useState('');
  const [inputAttempt, setInputAttempt] = useState(0);
  const [ticketId, setTicketId] = useState('');
  const [requestId, setRequestId] = useState(() => crypto.randomUUID());
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [listError, setListError] = useState('');
  const generation = useRef(0);
  const asset = assets.find((row) => row.asset_id === assetId);
  const selectedNode = inspection?.summary.find((row) => row.id === selected);
  const inputReady = normalInputReady(definition, normalInput);
  const invalidate = () => {
    setPlan(null);
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
      const initialWorkflow = new URLSearchParams(location.hash.split('?')[1] || '').get(
        'workflow',
      );
      if (initialWorkflow && workflows.definitions.some((row) => row.id === initialWorkflow)) {
        await inspect(
          initialWorkflow,
          workflows.definitions.find((row) => row.id === initialWorkflow),
        );
      }
      setListError('');
    } catch (e) {
      setListError(e instanceof Error ? e.message : '목록을 불러오지 못했습니다.');
    } finally {
      setLoading(false);
    }
  };
  const inspect = async (
    identity: string,
    known?: { id: string; name: string; revision: number },
  ) => {
    const current = ++generation.current;
    setDefinitionId(identity);
    setInspection(null);
    setDefinition(null);
    setNormalInput({});
    setSelected('');
    invalidate();
    setError('');
    if (!identity) {
      return;
    }
    const saved = known || definitions.find((row) => row.id === identity);
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
        if (graph.input_profile === 'face_workflow_v1') {
          setNormalInput({
            face_input: {
              photo_asset_id:
                new URLSearchParams(location.hash.split('?')[1] || '').get('photo') || '',
              engine_revision: null,
              engine_sha256: null,
              settings_revision: 1,
              reference_frame: 1,
            },
          });
        }
        const speech = graph.nodes.find((n) =>
          ['transcribe', 'transcription_agent'].includes(n.type),
        );
        const translated = graph.nodes.find((n) =>
          ['translate', 'translation_agent'].includes(n.type),
        );
        if (speech?.options.source_language) {
          setSourceLanguage(speech.options.source_language);
        }
        if (translated?.options.target_language) {
          setTargetLanguage(translated.options.target_language);
        }
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
      ...(definition?.catalog_version !== 2
        ? {
            source_language: sourceLanguage,
            target_language: targetLanguage,
          }
        : normalInput),
      ...(definition?.catalog_version !== 2 && definition?.inputs.transcript === 'transcript'
        ? { transcript: JSON.parse(transcript) }
        : {}),
      video_description: '',
      branch_choices: choices,
    },
  });
  const selectionKey = JSON.stringify({
    assetId,
    definitionId,
    revision: inspection?.definition_revision,
    sourceLanguage,
    targetLanguage,
    transcript,
    choices,
    normalInput,
  });
  const create = async () => {
    if (busy || !plan) {
      return;
    }
    setBusy(true);
    setError('');
    try {
      const ticket = await jsonPost<{ id: string }>(entryPath + '/create', {
        ...selection(),
        request_id: requestId,
        token: plan.token,
        paid_confirmed: plan.paid_roles.length > 0,
      });
      if (renewalBackend) {
        try {
          await startSavedJob(request, jsonPost, ticket.id, requestId);
        } finally {
          location.hash = `/jobs/${ticket.id}`;
        }
      } else if (frontendOnly) {
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
    if (
      !assetId ||
      !inspection?.supported ||
      !inspection.model_ready ||
      !inputReady ||
      inputLoading
    ) {
      return;
    }
    let cancelled = false;
    const timer = setTimeout(() => {
      void jsonPost<StartPlan>(entryPath + '/preview', selection())
        .then((value) => {
          if (!cancelled) {
            setPlan(value);
          }
        })
        .catch((reason) => {
          if (!cancelled) {
            setError(reason instanceof Error ? reason.message : '입력을 확인해 주세요.');
          }
        });
    }, 150);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [selectionKey, inspection?.supported, inspection?.model_ready, inputReady, inputLoading]);
  useEffect(() => {
    if (
      !assetId ||
      definition?.catalog_version !== 2 ||
      definition.input_profile === 'audio_file_v1' ||
      (!definition.inputs.transcript && !definition.inputs.audio)
    ) {
      setInputChoices([]);
      setInputLoading(false);
      setInputError('');
      return;
    }
    const controller = new AbortController();
    setInputLoading(true);
    setInputChoices([]);
    setInputError('');
    void request<{ inputs: InputChoice[] }>(
      `/work-entry/inputs?asset_id=${encodeURIComponent(assetId)}`,
      { signal: controller.signal },
    )
      .then((value) => {
        if (!controller.signal.aborted) {
          setInputChoices(value.inputs);
          setInputChoicesFor(assetId);
        }
      })
      .catch((reason) => {
        if (!controller.signal.aborted) {
          setInputChoices([]);
          setInputError(
            reason instanceof Error ? reason.message : '완료 입력 목록을 불러오지 못했습니다.',
          );
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setInputLoading(false);
        }
      });
    return () => controller.abort();
  }, [assetId, definition, inputAttempt]);
  useEffect(() => {
    if (definition?.input_profile === 'face_workflow_v1') {
      const query = new URLSearchParams();
      if (assetId) {
        query.set('target', assetId);
      }
      if (normalInput.face_input?.photo_asset_id) {
        query.set('photo', normalInput.face_input.photo_asset_id);
      }
      if (definitionId) {
        query.set('workflow', definitionId);
      }
      history.replaceState(null, '', '#/start?' + query.toString());
    }
  }, [assetId, definitionId, definition?.input_profile, normalInput.face_input?.photo_asset_id]);
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
      {renewalBackend && <a href="#/start/faceswap">얼굴 합성 입력 준비</a>}
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
            {definition?.catalog_version === 2 && frozenGoalLanguages(definition).length > 0 && (
              <div className="form-row">
                <span>저장된 워크플로우 언어</span>
                <div>
                  {frozenGoalLanguages(definition).map((language) => (
                    <p key={language.id}>
                      {language.label}: {languageLabel(language.value)}
                    </p>
                  ))}
                  <small>언어는 저장된 워크플로우 버전에 고정됩니다.</small>
                </div>
              </div>
            )}
            {definition?.catalog_version !== 2 && (
              <>
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
                        {languageLabel(lang)}
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
                        {languageLabel(lang)}
                      </option>
                    ))}
                  </select>
                </label>
              </>
            )}
            {definition?.input_profile === 'face_workflow_v1' && (
              <FaceWorkflowInputs
                assets={assets}
                value={normalInput}
                disabled={busy}
                onChange={(value) => {
                  setNormalInput(value);
                  setError('');
                  invalidate();
                }}
              />
            )}
            {definition?.catalog_version === 2 &&
              definition.input_profile !== 'audio_file_v1' &&
              (definition.inputs.transcript || definition.inputs.audio) && (
                <WorkflowInputs
                  key={`${assetId}:${definition.id}:${definition.revision}`}
                  inputs={definition.inputs}
                  value={normalInput}
                  choices={inputChoicesFor === assetId ? inputChoices : []}
                  loading={inputLoading}
                  error={inputError}
                  disabled={busy}
                  onReload={() => setInputAttempt((previous) => previous + 1)}
                  onChange={(value) => {
                    setNormalInput(value);
                    setError('');
                    invalidate();
                  }}
                />
              )}
            {definition?.catalog_version !== 2 &&
              definition?.inputs.transcript === 'transcript' && (
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
                  aria-invalid={!assetId}
                  aria-describedby={!assetId ? 'entry-source-required' : undefined}
                  value={assetId}
                  disabled={busy || !!listError}
                  onChange={(event) => {
                    setAssetId(event.target.value);
                    setNormalInput({});
                    invalidate();
                  }}
                >
                  <option value="">원본 선택</option>
                  {assets
                    .filter(
                      (row) =>
                        row.media_kind !== 'image' &&
                        (definition?.input_profile !== 'face_workflow_v1' ||
                          row.media_kind !== 'audio'),
                    )
                    .map((row) => (
                      <option
                        key={row.asset_id}
                        value={row.asset_id}
                        disabled={row.processing_supported === false}
                      >
                        {row.original_filename}
                        {row.processing_supported === false
                          ? ' · 현재 처리 한도 초과(보관 원본)'
                          : ''}
                      </option>
                    ))}
                </select>
                {!assetId && (
                  <small id="entry-source-required" className="field-validation">
                    원본을 선택하세요.
                  </small>
                )}
                {!assets.length && !listError && (
                  <p className="form-note">
                    등록된 원본이 없습니다. <a href="#/">원본 등록</a>
                  </p>
                )}
              </div>
            </label>
            {asset?.media_kind === 'audio' && (
              <a href={`#/start/audio/${assetId}`}>음성 전사 준비</a>
            )}
            <label className="form-row">
              <span>워크플로우</span>
              <div>
                <select
                  aria-label="워크플로우"
                  aria-invalid={!definitionId}
                  aria-describedby={!definitionId ? 'entry-workflow-required' : undefined}
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
                {!definitionId && (
                  <small id="entry-workflow-required" className="field-validation">
                    워크플로우를 선택하세요.
                  </small>
                )}
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
                inputThumbnail={
                  asset && asset.media_kind !== 'audio'
                    ? mediaUrl(`/videos/${asset.asset_id}/thumbnail`)
                    : undefined
                }
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
                      {selectedNode.model_required && <p>등록 API 모델 필수</p>}
                      {selectedNode.model ? (
                        <p>
                          모델: {selectedNode.model.name} · r{selectedNode.model.revision}
                        </p>
                      ) : selectedNode.model_required ? (
                        <p role="alert">
                          이 단계의 호환 등록 모델을 선택하고 워크플로우를 저장하세요.
                        </p>
                      ) : null}
                      {selectedNode.model_error && <p role="alert">{selectedNode.model_error}</p>}
                      <dl>
                        {Object.entries(selectedNode.options)
                          .filter(
                            ([k]) =>
                              ![
                                'batch_policy',
                                'clock_policy',
                                'media_budget',
                                'processing_profile',
                                'translation_profile',
                                'model_source',
                                'video_budget',
                                'max_model_calls',
                                'review_policy',
                                'cue_policy',
                              ].includes(k),
                          )
                          .map(([key, value]) => (
                            <div key={key}>
                              <dt>
                                {(
                                  {
                                    source_language: '원문 언어',
                                    target_language: '대상 언어',
                                    language: '자막 언어',
                                  } as Record<string, string>
                                )[key] || key}
                              </dt>
                              <dd>
                                {['source_language', 'target_language', 'language'].includes(key)
                                  ? languageLabel(value)
                                  : value}
                              </dd>
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
            {plan?.selected_inputs?.map((input) => (
              <p key={input.input}>
                {input.input === 'photo'
                  ? '선택 사진 원본'
                  : input.input === 'audio'
                    ? '같은 영상의 추출 WAV'
                    : '선택 시간 자막'}
                {input.segments !== undefined && ` · ${input.segments}구간`}
                {input.language &&
                  ` · 원문 언어: ${input.language === 'auto' ? '미지정' : languageLabel(input.language)}`}
              </p>
            ))}
            {plan?.model_call_budgets?.length ? (
              <section aria-label="이번 작업 모델 호출 상한">
                <h3>모델 호출 상한</h3>
                <ul>
                  {plan.model_call_budgets.map((item) => (
                    <li key={item.node_id}>
                      {item.role === 'vocalize'
                        ? '보컬'
                        : item.role === 'transcribe'
                          ? '전사'
                          : '번역'}{' '}
                      · {item.node_id}: 최대 {item.max_calls}회
                      {item.minimum_audio_calls !== null
                        ? ` · 원본 길이 기준 ${item.minimum_audio_calls}개 ${item.role === 'vocalize' ? '탐지 구간 예상 · 후보 재확인도 같은 상한 사용' : '오디오 구간 예상'}`
                        : ''}
                    </li>
                  ))}
                </ul>

                <p>
                  실제 구간 수는 전처리 결과에 따라 달라집니다. 이 화면의 확인만으로 API를 호출하지
                  않습니다.
                </p>
              </section>
            ) : null}
            {plan?.paid_roles.length ? (
              <p>
                선택한 모델의 API 비용이 발생할 수 있습니다. 금액은 미산정이며, 작업 시작을 누르면
                표시된 모델·호출 범위로 실행합니다.
              </p>
            ) : null}
            <Button
              aria-describedby={
                !assetId
                  ? 'entry-source-required'
                  : !definitionId
                    ? 'entry-workflow-required'
                    : !plan && inputReady
                      ? 'start-readiness'
                      : undefined
              }
              disabled={
                busy ||
                !plan ||
                !inputReady ||
                inputLoading ||
                !!listError ||
                !inspection?.supported ||
                !inspection.model_ready
              }
              onClick={() => void create()}
            >
              {busy ? '시작 준비 중…' : '작업 시작'}
            </Button>
            {!busy && !plan && assetId && definitionId && inputReady && (
              <p id="start-readiness" role="status">
                {error || listError
                  ? '위 오류를 확인하고 입력이나 설정을 변경하세요.'
                  : inputLoading
                    ? '완료 입력 목록을 불러오고 있습니다.'
                    : inspection && (!inspection.supported || !inspection.model_ready)
                      ? '위 안내에 따라 워크플로우 설정을 확인하세요.'
                      : '입력과 설정을 확인하고 있습니다.'}
              </p>
            )}
          </div>
        </div>
      )}
    </main>
  );
};
