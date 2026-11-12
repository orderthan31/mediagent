import { useEffect, useRef, useState } from 'react';
import { request } from './api';
import { jsonPost, type VideoAsset } from './video-api';
import { getSubtitleCopy } from './subtitle-copies';
import { startSavedJob } from './job-start.mjs';
import { PageTitle } from './PageTitle';
import { Button } from './hangyeol/primitives/button';
import { Input } from './hangyeol/primitives/input';
import { Textarea } from './hangyeol/primitives/textarea';
import type { ModelReference, RegisteredVersion } from './registered-models';
import { WorkflowCanvas, type CanvasDefinition, type CanvasSpec } from './WorkflowCanvas';
import { languageLabel } from './language-label';
import './direct-subtitle.css';
import './saved-subtitle-render.css';

type SavedCopy = Awaited<ReturnType<typeof getSubtitleCopy>>;
type Workflow = { id: string; revision: number; name: string };
type Inspection = {
  supported: boolean;
  model_ready: boolean;
  definition_revision: number;
  reasons: { message: string }[];
  summary: { id: string; options: Record<string, string>; model?: RegisteredVersion }[];
  agent_definition: CanvasDefinition;
};
type Plan = {
  token: string;
  paid_roles: string[];
  model_call_budgets?: { role: string; max_calls: number }[];
};
const outputLabels: Record<string, string> = {
  format: '별도 자막 형식',
  language: '출력 자막 언어',
  video_codec: '영상 코덱',
  subtitle_mode: '자막 방식',
  resolution: '해상도',
  quality_profile: '화질',
};
const choiceLabels: Record<string, string> = {
  from_transcript: '입력 자막 언어',
  burn: '영상에 입히기',
  soft: '선택 가능한 자막',
  original: '원본 크기',
  balanced: '균형',
  high: '높음',
  compact: '작은 용량',
  h264: 'H.264',
  hevc: 'HEVC',
  srt: 'SRT',
  srt_smi: 'SRT + SMI',
};
const post = <T,>(path: string, body: unknown, signal: AbortSignal) =>
  request<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  });

/** Existing normal preview/Create/Start, explicitly bound to an immutable copy. */
export const SavedSubtitleRender = ({
  copyId = '',
  audioAssetId = '',
  mode = 'render',
}: {
  copyId?: string;
  audioAssetId?: string;
  mode?: 'render' | 'translation' | 'audio';
}) => {
  const audio = mode === 'audio';
  const modelGoal = audio || mode === 'translation';
  const translating = mode === 'translation';
  const goalType = audio
    ? 'transcription_agent'
    : translating
      ? 'translation_agent'
      : 'subtitle_video_agent';
  const goalLabel = audio ? '전사 에이전트' : translating ? '번역 에이전트' : '자막 영상 에이전트';
  const [copy, setCopy] = useState<SavedCopy | null>(null);
  const [videos, setVideos] = useState<VideoAsset[]>([]);
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [catalog, setCatalog] = useState<CanvasSpec[]>([]);
  const [assetId, setAssetId] = useState(audioAssetId);
  const [workflowId, setWorkflowId] = useState('');
  const [graph, setGraph] = useState<CanvasDefinition | null>(null);
  const [goalId, setGoalId] = useState('');
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [modelRef, setModelRef] = useState<ModelReference>();
  const [language, setLanguage] = useState('auto');
  const [inspection, setInspection] = useState<{ key: string; value: Inspection } | null>(null);
  const [plan, setPlan] = useState<{ key: string; value: Plan } | null>(null);
  const [loading, setLoading] = useState(true);
  const [graphLoading, setGraphLoading] = useState(false);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState('');
  const [graphError, setGraphError] = useState('');
  const [checkError, setCheckError] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const [createdId, setCreatedId] = useState('');
  const [attempt, setAttempt] = useState(0);
  const pending = useRef(false);
  const nonce = useRef(crypto.randomUUID());
  const workflow = workflows.find((w) => w.id === workflowId);
  const goals = graph?.nodes.filter((n) => n.type === goalType) || [];
  const chosenGoal = goals.find((n) => n.id === goalId);
  const modelChoices = chosenGoal?.model_ref
    ? [chosenGoal.model_ref, ...(chosenGoal.fallback_refs || [])]
    : [];
  const descriptor = catalog.find((n) => n.id === goalType);
  const sourceReady = audio ? videos.some((v) => v.asset_id === assetId) : !!copy;
  const renderOptions = audio
    ? {
        audio_goal: {
          node_id: goalId,
          options: { ...overrides, source_language: language },
          ...(modelRef ? { model_ref: modelRef } : {}),
        },
      }
    : {
        saved_subtitle: { copy_id: copyId, srt_sha256: copy?.srt_sha256 },
        ...(translating
          ? {
              translation_goal: {
                node_id: goalId,
                options: overrides,
                ...(modelRef ? { model_ref: modelRef } : {}),
              },
            }
          : { render_goal: { node_id: goalId, options: overrides } }),
        input_language: language,
      };
  const inspectKey = JSON.stringify({
    workflowId,
    revision: workflow?.revision,
    goalId,
    overrides,
    copyId,
    sha: copy?.srt_sha256,
    mode,
    modelRef,
    ...(audio ? { language, assetId } : {}),
  });
  const selection = {
    asset_id: assetId,
    definition_id: workflowId,
    definition_revision: workflow?.revision,
    options: renderOptions,
  };
  const selectionKey = JSON.stringify(selection);
  const currentInspection = inspection?.key === inspectKey ? inspection.value : null;
  const currentPlan = plan?.key === selectionKey ? plan.value : null;
  const description =
    overrides.video_description ??
    chosenGoal?.options.video_description ??
    chosenGoal?.tool_settings?.translate?.video_description ??
    '';
  const descriptionValid = !translating || Array.from(description).length <= 2000;
  const ready =
    descriptionValid &&
    sourceReady &&
    !!currentInspection?.supported &&
    !!currentInspection.model_ready &&
    !!currentPlan &&
    !checking &&
    !submitted &&
    !pending.current;
  const effective = currentInspection?.summary.find((n) => n.id === goalId)?.options;
  const effectiveModel = currentInspection?.summary.find((n) => n.id === goalId)?.model;
  const fail = (reason: unknown) =>
    reason instanceof Error ? reason.message : '입력을 확인하지 못했습니다.';
  const changeWorkflow = (value: string) => {
    setWorkflowId(value);
    setGraph(null);
    setGoalId('');
    setOverrides({});
    setModelRef(undefined);
    setPlan(null);
    setCheckError('');
  };
  const create = async () => {
    if (!ready || !currentPlan || pending.current) {
      return;
    }
    pending.current = true;
    setSubmitted(true);
    setCheckError('');
    try {
      const job = await jsonPost<{ id: string }>('/work-entry/create', {
        ...selection,
        token: currentPlan.token,
        request_id: nonce.current,
        paid_confirmed:
          modelGoal && currentPlan.paid_roles.includes(audio ? 'transcription' : 'translation'),
      });
      setCreatedId(job.id);
      try {
        await startSavedJob(request, jsonPost, job.id, nonce.current);
      } finally {
        location.hash = `/jobs/${job.id}`;
      }
    } catch (reason) {
      setCheckError(`${fail(reason)} 작업 목록에서 생성 여부를 확인하세요.`);
    } finally {
      pending.current = false;
    }
  };
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError('');
    setCopy(null);
    void Promise.all([
      audio ? Promise.resolve(null) : getSubtitleCopy(copyId, controller.signal),
      request<{ videos: VideoAsset[] }>('/videos', { signal: controller.signal }),
      request<{ definitions: Workflow[] }>('/work-entry/workflows', { signal: controller.signal }),
      request<{ nodes: CanvasSpec[] }>('/work-entry/catalog', { signal: controller.signal }),
    ])
      .then(([saved, originals, definitions, nodes]) => {
        if (controller.signal.aborted) {
          return;
        }
        if (!audio && (!saved?.srt_sha256 || !/^[a-f0-9]{64}$/.test(saved.srt_sha256))) {
          throw new Error('저장 자막을 확인할 수 없습니다. 다시 불러오세요.');
        }
        setCopy(saved);
        setVideos(
          originals.videos.filter((v) => (audio ? v.media_kind === 'audio' : !v.media_kind)),
        );
        setWorkflows(definitions.definitions);
        setCatalog(nodes.nodes);
      })
      .catch((reason) => {
        if (!controller.signal.aborted) {
          setError(fail(reason));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [copyId, audio, attempt]);
  useEffect(() => {
    if (!workflowId || !workflow) {
      return;
    }
    const controller = new AbortController();
    setGraphLoading(true);
    setGraphError('');
    void request<CanvasDefinition>(
      `/work-entry/workflows/${workflowId}?revision=${workflow.revision}`,
      { signal: controller.signal },
    )
      .then((value) => {
        if (controller.signal.aborted) {
          return;
        }
        if (value.revision !== workflow.revision || value.catalog_version !== 2) {
          throw new Error('에이전트 워크플로우 버전을 다시 선택하세요.');
        }
        setGraph(value);
      })
      .catch((reason) => {
        if (!controller.signal.aborted) {
          setGraphError(fail(reason));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setGraphLoading(false);
        }
      });
    return () => controller.abort();
  }, [workflowId, workflow]);
  useEffect(() => {
    setInspection(null);
    setPlan(null);
    setCheckError('');
    if (
      !(audio ? sourceReady && language && modelChoices.length : !!copy) ||
      !workflow ||
      !goals.some((n) => n.id === goalId)
    ) {
      return;
    }
    if (!descriptionValid) {
      setCheckError('번역 참고 설명은 2000자 이내로 입력해 주세요.');
      return;
    }
    if (audio && overrides.llm_options) {
      try {
        const parsed = JSON.parse(overrides.llm_options);
        if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') {
          throw new Error();
        }
      } catch {
        setCheckError('모델 요청 옵션은 JSON 객체여야 합니다.');
        return;
      }
    }
    const controller = new AbortController();
    void post<Inspection>(
      '/work-entry/inspect',
      { definition_id: workflowId, definition_revision: workflow.revision, options: renderOptions },
      controller.signal,
    )
      .then((value) => {
        if (controller.signal.aborted) {
          return;
        }
        if (
          value.definition_revision !== workflow.revision ||
          value.agent_definition.nodes.length !== 1 ||
          value.agent_definition.nodes[0].id !== goalId
        ) {
          throw new Error('선택 에이전트 구성을 다시 확인하세요.');
        }
        setInspection({ key: inspectKey, value });
      })
      .catch((reason) => {
        if (!controller.signal.aborted) {
          setCheckError(fail(reason));
        }
      });
    return () => controller.abort();
    // All inspect request fields are represented by inspectKey. Language is
    // checked separately by preview; it does not change public goal settings.
  }, [inspectKey, graph, copy, sourceReady]);
  useEffect(() => {
    setPlan(null);
    nonce.current = crypto.randomUUID();
    if (
      !sourceReady ||
      !assetId ||
      !currentInspection?.supported ||
      !currentInspection.model_ready ||
      !language ||
      submitted
    ) {
      setChecking(false);
      return;
    }
    setCheckError('');
    const controller = new AbortController();
    setChecking(true);
    const timer = setTimeout(() => {
      void post<Plan>('/work-entry/preview', selection, controller.signal)
        .then((value) => {
          if (controller.signal.aborted) {
            return;
          }
          if (
            !/^[a-f0-9]{64}$/.test(value.token) ||
            !Array.isArray(value.paid_roles) ||
            value.paid_roles.some(
              (role) => !modelGoal || role !== (audio ? 'transcription' : 'translation'),
            )
          ) {
            throw new Error('자막 입력·실행 구성을 다시 확인하세요.');
          }
          setPlan({ key: selectionKey, value });
        })
        .catch((reason) => {
          if (!controller.signal.aborted) {
            setCheckError(fail(reason));
          }
        })
        .finally(() => {
          if (!controller.signal.aborted) {
            setChecking(false);
          }
        });
    }, 150);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
    // Selection is fully serialized, and inspection readiness is key-bound.
  }, [selectionKey, currentInspection, submitted]);
  return (
    <main className="video-main direct-subtitle-page saved-subtitle-render">
      <PageTitle>
        {audio ? '음성 전사 준비' : translating ? '자막 번역 준비' : '자막 영상 작업 준비'}
      </PageTitle>
      {audio ? (
        <a href={`#/videos/${assetId || audioAssetId}`}>원본 열기</a>
      ) : (
        <a href={`#/subtitles/saved/${copyId}`}>저장 자막 열기</a>
      )}
      <p>
        {audio
          ? '선택한 음성 원본으로 전사만 준비합니다.'
          : translating
            ? '저장한 자막으로 별도 번역 작업을 준비합니다. 전사·영상 제작은 실행하지 않습니다.'
            : '저장한 자막과 선택한 영상으로 별도 MP4 작업을 준비합니다.'}
      </p>
      {translating && (
        <p>
          작업 기록에 연결할 원본 영상이 필요합니다. 자막 시각이 해당 영상 길이 안에 있어야 합니다.
        </p>
      )}
      {loading && <p role="status">입력 목록 불러오는 중</p>}
      {error && (
        <>
          <p role="alert">{error}</p>
          <Button variant="quiet" onClick={() => setAttempt((v) => v + 1)}>
            다시 불러오기
          </Button>
        </>
      )}
      {copy && (
        <section aria-label="선택 자막">
          <h2>{copy.title}</h2>
          <p>{copy.filename}</p>
          <p>
            자막 {copy.cue_count}개 · 저장 시각 {new Date(copy.created_at).toLocaleString('ko-KR')}
          </p>
        </section>
      )}
      {audio && !loading && !error && !videos.some((v) => v.asset_id === audioAssetId) && (
        <p role="alert">선택 음성 원본을 확인할 수 없습니다. 원본 목록에서 다시 선택하세요.</p>
      )}
      {!loading && !error && !workflows.length && <p>사용 가능한 저장 워크플로우가 없습니다.</p>}
      <div className="saved-render-fields">
        <label>
          {audio ? '원본 음성' : '원본 영상'}
          <select
            aria-label={audio ? '원본 음성' : '원본 영상'}
            value={assetId}
            disabled={loading || (!audio && !copy) || submitted}
            onChange={(e) => setAssetId(e.target.value)}
          >
            <option value="">{audio ? '음성 선택' : '영상 선택'}</option>
            {videos.map((v) => (
              <option key={v.asset_id} value={v.asset_id}>
                {v.original_filename}
              </option>
            ))}
          </select>
        </label>
        {audio && videos.find((v) => v.asset_id === assetId) && (
          <p>
            {videos.find((v) => v.asset_id === assetId)?.media_type} ·{' '}
            {videos.find((v) => v.asset_id === assetId)?.media?.duration}초
          </p>
        )}
        <label>
          저장된 워크플로우
          <select
            aria-label="저장된 워크플로우"
            value={workflowId}
            disabled={loading || (!audio && !copy) || submitted}
            onChange={(e) => changeWorkflow(e.target.value)}
          >
            <option value="">워크플로우 선택</option>
            {workflows.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name} · v{w.revision}
              </option>
            ))}
          </select>
        </label>
        {graphLoading && <p role="status">워크플로우 불러오는 중</p>}
        {graphError && <p role="alert">{graphError}</p>}
        {graph && !goals.length && (
          <p>이 버전에는 {goalLabel}가 없습니다. 다른 워크플로우를 선택하세요.</p>
        )}
        <label>
          {goalLabel}
          <select
            aria-label={goalLabel}
            value={goalId}
            disabled={!goals.length || submitted}
            onChange={(e) => {
              setGoalId(e.target.value);
              setOverrides({});
              setModelRef(undefined);
              if (audio) {
                setLanguage(
                  goals.find((n) => n.id === e.target.value)?.options.source_language || 'auto',
                );
              }
            }}
          >
            <option value="">에이전트 선택</option>
            {goals.map((n, index) => (
              <option key={n.id} value={n.id}>
                {descriptor?.label || goalLabel}
                {goals.length > 1 ? ` ${index + 1}` : ''}
              </option>
            ))}
          </select>
        </label>
        <label>
          {audio ? '원문 언어' : '자막 언어'}
          <Input
            aria-label={audio ? '원문 언어' : '자막 언어'}
            value={language}
            disabled={submitted}
            placeholder="auto, en, pt-BR"
            onChange={(e) => setLanguage(e.target.value)}
          />
        </label>
        {modelGoal && chosenGoal && (
          <>
            {translating && (
              <label>
                번역할 언어
                <Input
                  aria-label="번역할 언어"
                  value={
                    overrides.target_language ??
                    effective?.target_language ??
                    chosenGoal.options.target_language ??
                    ''
                  }
                  disabled={submitted}
                  placeholder="ko, en, pt-BR"
                  onChange={(e) =>
                    setOverrides((previous) => ({ ...previous, target_language: e.target.value }))
                  }
                />
                <span>
                  {languageLabel(
                    overrides.target_language ??
                      effective?.target_language ??
                      chosenGoal.options.target_language,
                  )}
                </span>
              </label>
            )}
            {translating && (
              <label>
                번역 참고 설명
                <Textarea
                  aria-label="번역 참고 설명"
                  rows={4}
                  value={description}
                  disabled={submitted}
                  aria-invalid={!descriptionValid}
                  onChange={(event) =>
                    setOverrides((current) => ({
                      ...current,
                      video_description: event.target.value,
                    }))
                  }
                />
                <small>
                  선택 사항 · 이 번역에 참고할 인명, 장면, 전문 용어를 적어 주세요. 최대 2000자.
                </small>
              </label>
            )}
            <label>
              {audio ? '전사 모델' : '번역 모델'}
              <select
                aria-label={audio ? '전사 모델' : '번역 모델'}
                disabled={submitted || !modelChoices.length}
                value={JSON.stringify(modelRef || chosenGoal.model_ref) || ''}
                onChange={(e) => setModelRef(JSON.parse(e.target.value) as ModelReference)}
              >
                {!modelChoices.length && <option value="">고정된 등록 모델 없음</option>}
                {modelChoices.map((ref, index) => (
                  <option key={JSON.stringify(ref)} value={JSON.stringify(ref)}>
                    {index === 0 ? '저장 모델' : `대체 모델 ${index}`} · {ref.model_id} · v
                    {ref.revision}
                  </option>
                ))}
              </select>
            </label>
            {effectiveModel && (
              <p>
                {effectiveModel.name} · {effectiveModel.provider} · v{effectiveModel.revision}
              </p>
            )}
            <p>
              이 에이전트에 저장된 모델 버전 중 선택합니다. 나머지 후보는 대체 모델로 유지합니다.
            </p>
            <label>
              모델 요청 옵션 (JSON)
              <Textarea
                aria-label="모델 요청 옵션 (JSON)"
                value={
                  overrides.llm_options ??
                  effective?.llm_options ??
                  chosenGoal.options.llm_options ??
                  ''
                }
                disabled={submitted}
                maxLength={2048}
                onChange={(e) =>
                  setOverrides((previous) => ({ ...previous, llm_options: e.target.value }))
                }
              />
            </label>
          </>
        )}
        {!modelGoal &&
          effective &&
          descriptor &&
          Object.entries(outputLabels).map(([key, label]) => (
            <label key={key}>
              {label}
              <select
                aria-label={label}
                value={overrides[key] ?? effective[key]}
                disabled={submitted}
                onChange={(e) =>
                  setOverrides((previous) => ({ ...previous, [key]: e.target.value }))
                }
              >
                {descriptor.options[key]?.map((value) => (
                  <option key={value} value={value}>
                    {choiceLabels[value] || (key === 'language' ? languageLabel(value) : value)}
                  </option>
                ))}
              </select>
            </label>
          ))}
      </div>
      {currentInspection && (
        <>
          {currentInspection.reasons.map((reason, index) => (
            <p role="alert" key={index}>
              {reason.message}
            </p>
          ))}
          <WorkflowCanvas definition={currentInspection.agent_definition} catalog={catalog} />
        </>
      )}
      {checking && <p role="status">입력 확인 중</p>}
      {checkError && <p role="alert">{checkError}</p>}
      {currentPlan && (
        <p role="status">입력을 확인했습니다. 새 작업으로 만들고 시작할 수 있습니다.</p>
      )}
      {modelGoal && currentPlan && (
        <>
          {currentPlan.model_call_budgets?.map((budget, index) => (
            <p key={index}>
              {audio ? '전사' : '번역'} · 최대 {budget.max_calls}회 (기본·대체 모델 합계)
            </p>
          ))}
          {!!currentPlan.paid_roles.length && (
            <p>
              선택한 모델의 API 비용이 발생할 수 있습니다. 금액은 미산정이며, 작업 시작을 누르면
              표시된 모델·호출 범위로 실행합니다.
            </p>
          )}
          <p>이 화면의 확인만으로 모델을 호출하지 않습니다.</p>
        </>
      )}
      {submitted && <p role="status">생성 요청을 보냈습니다. 작업 목록에서 상태를 확인하세요.</p>}
      <div className="direct-subtitle-actions">
        <Button disabled={!ready} onClick={() => void create()}>
          새 작업 만들고 시작
        </Button>
        <a href={createdId ? `#/jobs/${createdId}` : '#/jobs'}>작업 목록 확인</a>
      </div>
    </main>
  );
};
