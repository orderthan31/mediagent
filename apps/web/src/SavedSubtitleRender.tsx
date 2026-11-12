import { useEffect, useRef, useState } from 'react';
import { request } from './api';
import { jsonPost, type VideoAsset } from './video-api';
import { getSubtitleCopy } from './subtitle-copies';
import { startSavedJob } from './job-start.mjs';
import { PageTitle } from './PageTitle';
import { Button } from './hangyeol/primitives/button';
import { Input } from './hangyeol/primitives/input';
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
  summary: { id: string; options: Record<string, string> }[];
  agent_definition: CanvasDefinition;
};
type Plan = { token: string; paid_roles: string[] };
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
export const SavedSubtitleRender = ({ copyId }: { copyId: string }) => {
  const [copy, setCopy] = useState<SavedCopy | null>(null);
  const [videos, setVideos] = useState<VideoAsset[]>([]);
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [catalog, setCatalog] = useState<CanvasSpec[]>([]);
  const [assetId, setAssetId] = useState('');
  const [workflowId, setWorkflowId] = useState('');
  const [graph, setGraph] = useState<CanvasDefinition | null>(null);
  const [goalId, setGoalId] = useState('');
  const [overrides, setOverrides] = useState<Record<string, string>>({});
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
  const goals = graph?.nodes.filter((n) => n.type === 'subtitle_video_agent') || [];
  const descriptor = catalog.find((n) => n.id === 'subtitle_video_agent');
  const renderOptions = {
    saved_subtitle: { copy_id: copyId, srt_sha256: copy?.srt_sha256 },
    render_goal: { node_id: goalId, options: overrides },
    input_language: language,
  };
  const inspectKey = JSON.stringify({
    workflowId,
    revision: workflow?.revision,
    goalId,
    overrides,
    copyId,
    sha: copy?.srt_sha256,
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
  const ready =
    !!copy &&
    !!currentInspection?.supported &&
    !!currentInspection.model_ready &&
    !!currentPlan &&
    !checking &&
    !submitted &&
    !pending.current;
  const effective = currentInspection?.summary.find((n) => n.id === goalId)?.options;
  const fail = (reason: unknown) =>
    reason instanceof Error ? reason.message : '입력을 확인하지 못했습니다.';
  const changeWorkflow = (value: string) => {
    setWorkflowId(value);
    setGraph(null);
    setGoalId('');
    setOverrides({});
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
        paid_confirmed: false,
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
      getSubtitleCopy(copyId, controller.signal),
      request<{ videos: VideoAsset[] }>('/videos', { signal: controller.signal }),
      request<{ definitions: Workflow[] }>('/work-entry/workflows', { signal: controller.signal }),
      request<{ nodes: CanvasSpec[] }>('/work-entry/catalog', { signal: controller.signal }),
    ])
      .then(([saved, originals, definitions, nodes]) => {
        if (controller.signal.aborted) {
          return;
        }
        if (!saved.srt_sha256 || !/^[a-f0-9]{64}$/.test(saved.srt_sha256)) {
          throw new Error('저장 자막을 확인할 수 없습니다. 다시 불러오세요.');
        }
        setCopy(saved);
        setVideos(originals.videos);
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
  }, [copyId, attempt]);
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
    if (!copy || !workflow || !goals.some((n) => n.id === goalId)) {
      return;
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
          throw new Error('자막 영상 구성을 다시 확인하세요.');
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
  }, [inspectKey, graph, copy]);
  useEffect(() => {
    setPlan(null);
    setCheckError('');
    nonce.current = crypto.randomUUID();
    if (
      !copy ||
      !assetId ||
      !currentInspection?.supported ||
      !currentInspection.model_ready ||
      !language ||
      submitted
    ) {
      setChecking(false);
      return;
    }
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
            value.paid_roles.length
          ) {
            throw new Error('자막 영상의 입력·실행 구성을 다시 확인하세요.');
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
      <PageTitle>자막 영상 작업 준비</PageTitle>
      <a href={`#/subtitles/saved/${copyId}`}>저장 자막 열기</a>
      <p>저장한 자막과 선택한 영상으로 별도 MP4 작업을 준비합니다.</p>
      {loading && <p role="status">저장 자막과 원본 목록 불러오는 중</p>}
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
      <div className="saved-render-fields">
        <label>
          원본 영상
          <select
            aria-label="원본 영상"
            value={assetId}
            disabled={loading || !copy || submitted}
            onChange={(e) => setAssetId(e.target.value)}
          >
            <option value="">영상 선택</option>
            {videos.map((v) => (
              <option key={v.asset_id} value={v.asset_id}>
                {v.original_filename}
              </option>
            ))}
          </select>
        </label>
        <label>
          저장된 워크플로우
          <select
            aria-label="저장된 워크플로우"
            value={workflowId}
            disabled={loading || !copy || submitted}
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
          <p>이 버전에는 자막 영상 에이전트가 없습니다. 다른 워크플로우를 선택하세요.</p>
        )}
        <label>
          자막 영상 에이전트
          <select
            aria-label="자막 영상 에이전트"
            value={goalId}
            disabled={!goals.length || submitted}
            onChange={(e) => {
              setGoalId(e.target.value);
              setOverrides({});
            }}
          >
            <option value="">에이전트 선택</option>
            {goals.map((n) => (
              <option key={n.id} value={n.id}>
                {descriptor?.label || '자막 영상'} · {n.id}
              </option>
            ))}
          </select>
        </label>
        <label>
          자막 언어
          <Input
            value={language}
            disabled={submitted}
            placeholder="auto, en, pt-BR"
            onChange={(e) => setLanguage(e.target.value)}
          />
        </label>
        {effective &&
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
