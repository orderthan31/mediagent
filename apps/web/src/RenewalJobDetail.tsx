import { modelCallOptionLabel } from './model-call-budget';
import { FaceWorkflowReview } from './FaceWorkflowReview';
import { publicAgentGraph } from './job-graphs';
import type { GoalOutput } from './GoalResults';
import { JobFiles, outputLabel } from './JobFiles';
import { jobStateLabel } from './job-display';
import { languageLabel } from './language-label';
import { frozenGoalLanguages } from './goal-languages';
import { getJobStartState, startTrackedJob, subscribeJobStarts } from './job-start.mjs';
import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { request, mediaUrl } from './api';
import { jsonPost } from './video-api';
import { FullVideoPreview } from './FullVideoPreview';
import type { ProcessingProjection } from './processing-review-state';
import { JobProcessingReview } from './JobProcessingReview';
import { ProjectionRecoveryPanel } from './ProjectionRecoveryPanel';
import { ModelRolePanel } from './ModelRolePanel';
import { TaskResultTabs } from './TaskResultTabs';
import { renewalBackend } from './preview';
import { SrtCopyAction } from './SrtCopyEditor';
import { artifactSrtSource } from './srt-copy';
import { SubtitleTrackReview, SubtitleOutputs } from './SubtitleTracksPanel';
import { PageTitle } from './PageTitle';
import { LoadingSkeleton } from './LoadingSkeleton';
import { Button } from './hangyeol/primitives/button';
import { WorkflowCanvas, type CanvasDefinition, type CanvasSpec } from './WorkflowCanvas';
import { DataForm } from './DataForm';
import type { FieldSchema, FormData } from './form-contract';
import './job-detail.css';
import './workflow-tickets.css';
import './job-execution.css';
import './renewal-runtime.css';

type Reference = { storage_key: string; sha256: string; bytes: number; type: string };
type TranslationTrace = {
  model?: { model_id: string; revision: number };
  selected?: { remote_model: string } | null;
  attempts?: {
    index: number;
    remote_model: string;
    protocol: string;
    revision: number;
    connection_revision: number;
    status: string;
    error?: string;
    transition?: string;
  }[];
};
type VocalTrace = {
  status?: string;
  held?: boolean;
  error?: string | null;
  call_count?: number;
  reused_chunks?: number;
  chunks?: unknown[];
};
type Run = {
  id: string;
  node_id: string;
  node_type: string;
  display_status?: string;
  display_reason?: string;
  status: string;
  dispatch?: { phase: string };
  options: Record<string, string>;
  inputs: Record<string, Reference>;
  error_code?: string;
  translation?: TranslationTrace;
  transcription?: TranslationTrace;
  vocalization?: VocalTrace;
  result: {
    outputs: Record<string, Reference>;
    previews?: Record<string, { status: string }>;
    reused_from?: { job_id: string };
    translation?: TranslationTrace;
    transcription?: TranslationTrace;
    vocalization?: VocalTrace;
  } | null;
};
type Review = {
  id: string;
  node_run_id: string;
  revision: number;
  status: string;
  draft: FormData;
  contract: {
    fields: FieldSchema;
    source: Reference;
    kind?: string;
    audio?: { duration_seconds: number; source_frames: number; source_sha256: string };
  };
};
type AgentToolState = {
  node_id: string;
  role: string;
  label: string;
  state: string;
  reason: string;
  run_id: string | null;
};
type WorkflowAgentState = {
  id: string;
  type: string;
  label: string;
  state: string;
  status_label: string;
  reason: string;
  selected_tool_id: string;
  tools: AgentToolState[];
  outputs?: GoalOutput[];
};
type State = {
  selected_inputs?: {
    input: string;
    kind: string;
    language?: string;
    segments?: number;
    job_id?: string;
    copy_id?: string;
    filename?: string;
  }[];
  agent_workflow?: {
    definition: CanvasDefinition;
    nodes: WorkflowAgentState[];
    edges: Record<string, { state: string; label: string }>;
    legacy_projection: boolean;
  } | null;
  output_mode?: string | null;
  artifact_manifest?: {
    layout: string;
    entry_count: number;
    reference: Reference | null;
  };
  processing_review?: ProcessingProjection | null;
  access?: { can_manage: boolean };
  executed_by?: string;
  asset_owner_id?: string;
  id: string;
  ticket_number: number;
  revision: number;
  status: string;
  execution_state?: string | null;
  display_status?: string;
  parent_id: string | null;
  snapshot: {
    asset: { asset_id: string; original_filename: string; uploaded_by?: string };
    inputs?: Record<string, { type: string }>;
    definition: CanvasDefinition;
    tool_definition?: CanvasDefinition;
    options?: { source_language?: string; target_language?: string };
  };
  runs: Run[];
  reviews: Review[];
};
type Plan = { token: string; ready: boolean; reasons: string[]; notice: string };
const translationLabels: Record<string, string> = {
  completed: '완료',
  failed: '실패',
  skipped: '사용 불가',
  started: '호출 중',
  cancelled: '취소',
  next_candidate: '다음 후보',
  stop: '중단',
  exhausted: '후보 소진',
  adopted: '최종 채택',
  rate_limited: '요청 한도',
  upstream_failure: '서버 오류',
  invalid_response: '응답 형식 오류',
  unavailable: '사용 불가',
  outcome_unknown: '전송 결과 불명',
  authentication_failed: '인증 거부',
  request_rejected: '요청 거부',
};
const labels: Record<string, string> = {
  held: '보류 · 응답 확인 필요',
  draft: '실행 전',
  waiting: '대기',
  running: '처리 중',
  completed: '완료',
  failed: '실패',
  cancelled: '취소',
  cancelling: '취소 접수 · 진행 처리 정리 중',
  review_required: '검수 대기',
  skipped: '미선택',
  blocked: '선행 실패로 차단',
  quarantined: '늦은 결과 격리',
};

export const RenewalJobDetail = ({ id }: { id: string }) => {
  const start = useSyncExternalStore(subscribeJobStarts, () => getJobStartState(id));
  const [job, setJob] = useState<State | null>(null);
  const [catalog, setCatalog] = useState<CanvasSpec[]>([]);
  const [modelRolesEnabled, setModelRolesEnabled] = useState(false);
  const [selected, setSelected] = useState('');
  const [selectedTool, setSelectedTool] = useState('');
  const [, setPlan] = useState<Plan | null>(null);
  const [, setConsent] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [cancelBusy, setCancelBusy] = useState(false);
  const [error, setError] = useState('');
  const [loadError, setLoadError] = useState('');
  const [resultsTab, setResultsTab] = useState<'output' | 'logs'>('output');
  const [panelRequest, setPanelRequest] = useState(0);
  const resultsPanel = useRef<HTMLElement>(null);
  const processingPanel = useRef<HTMLDivElement>(null);
  const [risk, setRisk] = useState(false);
  const [drafts, setDrafts] = useState<Record<string, FormData>>({});
  const nonces = useRef({
    confirm: crypto.randomUUID(),
    admit: crypto.randomUUID(),
    recover: crypto.randomUUID(),
  });
  const base = '/renewal/jobs/' + id;
  const reload = async () => {
    const next = await request<State>(base);
    setJob(next);
    setLoadError('');
    return next;
  };
  const action = async (operation: () => Promise<unknown>) => {
    if (busy) {
      return;
    }
    setBusy(true);
    setError('');
    try {
      await operation();
      await reload();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '요청 실패');
    } finally {
      setBusy(false);
    }
  };
  const faceDefinition = job?.agent_workflow?.definition;
  const agentDefinition =
    publicAgentGraph(job) ||
    (faceDefinition?.catalog_version === 2 &&
    faceDefinition.input_profile === 'face_workflow_v1' &&
    faceDefinition.nodes.length === 1 &&
    faceDefinition.nodes[0].type === 'faceswap_agent'
      ? faceDefinition
      : null);
  const canManage = job?.access?.can_manage === true;
  const currentAgent = job?.agent_workflow?.nodes.find((item) => item.id === selected);
  const tool =
    currentAgent?.tools.find((item) => item.node_id === selectedTool) ||
    currentAgent?.tools.find((item) => item.node_id === currentAgent.selected_tool_id);
  const internalId = tool?.node_id || selected;
  const run = job?.runs.find((item) => item.node_id === internalId);
  const toolDefinition = job?.snapshot.tool_definition || job?.snapshot.definition;
  const review = job?.reviews.find((item) => item.node_run_id === run?.id);
  const reviewFields =
    review && ['audio_regions_v1', 'audio_regions_long_v5'].includes(review.contract.kind || '')
      ? {
          ...review.contract.fields,
          propertyOrder: ['protected', 'removals', 'approved'],
          properties: Object.fromEntries(
            Object.entries(review.contract.fields.properties || {}).map(([key, field]) => [
              key,
              field.type === 'array' && field.items
                ? { ...field, items: { ...field.items, propertyOrder: ['start', 'end', 'kind'] } }
                : field,
            ]),
          ),
        }
      : review?.contract.fields;
  const outputs = run?.status === 'completed' ? run.result?.outputs || {} : {};
  const vocalization = run?.result?.vocalization || run?.vocalization;
  const translation =
    run?.result?.transcription ||
    run?.transcription ||
    run?.result?.translation ||
    run?.translation;
  const traceLabel = run?.node_type === 'transcribe' ? '전사' : '번역';
  const url = (port: string) =>
    mediaUrl(`${base}/artifacts/${run?.id}/${encodeURIComponent(port)}`);
  const failedSteps =
    job?.agent_workflow?.nodes.flatMap((agent) => {
      const failed = agent.tools.find(
        (item) =>
          ['failed', 'held', 'quarantined'].includes(item.state) &&
          job.runs.some(
            (attempt) => attempt.id === item.run_id && attempt.node_id === item.node_id,
          ),
      );
      return failed ? [{ agent, tool: failed }] : [];
    }) || [];
  const openLogs = (agentId: string, toolId: string) => {
    setSelected(agentId);
    setSelectedTool(toolId);
    setResultsTab('logs');
    setPanelRequest((value) => value + 1);
  };
  useEffect(() => {
    if (panelRequest) {
      const frame = requestAnimationFrame(() => {
        const tab = resultsPanel.current?.querySelector<HTMLButtonElement>(
          '[role="tab"][aria-selected="true"]',
        );
        tab?.focus({ preventScroll: true });
        tab?.scrollIntoView({ block: 'nearest' });
      });
      return () => cancelAnimationFrame(frame);
    }
  }, [selected, panelRequest]);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      try {
        const [next, specs] = await Promise.all([
          request<State>(base, { signal: controller.signal }),
          request<{ nodes: CanvasSpec[]; independent_model_roles?: boolean }>(
            '/work-entry/catalog',
            { signal: controller.signal },
          ),
        ]);
        if (!controller.signal.aborted) {
          setJob(next);
          setCatalog(specs.nodes);
          setModelRolesEnabled(specs.independent_model_roles === true);
          setLoadError('');
        }
      } catch (reason) {
        if (!controller.signal.aborted) {
          setLoadError(reason instanceof Error ? reason.message : '작업 조회 실패');
        }
      } finally {
        if (!controller.signal.aborted) {
          timer = setTimeout(load, 4000);
        }
      }
    };
    void load();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [base, start?.pending]);
  return (
    <main className="job-detail ticket-detail job-detail-canvas">
      <PageTitle>{job ? `작업 #${job.ticket_number}` : '작업'}</PageTitle>
      {start?.pending && (
        <p role="status" data-start-stage={start.stage}>
          시작 준비 중 ·{' '}
          {
            (
              {
                checking: '작업 상태 확인 중',
                'prepare-start': '시작 설정 준비 중',
                plan: '원본과 실행 계획 확인 중',
                confirm: '실행 범위 승인 중',
                admit: '실행 접수 중',
                run: '실행 요청 응답 대기 중',
              } as Record<string, string>
            )[start.stage]
          }
          {' · 응답에 시간이 걸릴 수 있습니다. 다시 시작을 누르지 않아도 됩니다.'}
        </p>
      )}
      {start?.error && (
        <p role="alert" className="alert">
          {start.error} · 자동으로 다시 요청하지 않습니다. 현재 작업 상태를 확인해 주세요.
        </p>
      )}
      {error && (
        <p role="alert" className="alert">
          {error}
        </p>
      )}
      {loadError && (
        <p role="alert">
          {loadError}
          {job && ' · 마지막으로 확인한 상태입니다.'}
        </p>
      )}
      {!job && !error && !loadError && (
        <LoadingSkeleton layout="canvas" label="작업 상세 불러오는 중" />
      )}
      {job && (
        <>
          <div className="job-detail-toolbar">
            <a href={'#/videos/' + job.snapshot.asset.asset_id}>
              {job.snapshot.asset.original_filename}
            </a>
            <strong role="status">{jobStateLabel(job)}</strong>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              {canManage && job.status === 'draft' && (
                <Button
                  disabled={busy || start?.pending}
                  onClick={() =>
                    void startTrackedJob(request, jsonPost, id, crypto.randomUUID()).catch(() => {})
                  }
                >
                  작업 시작
                </Button>
              )}
              <Button variant="quiet" disabled={busy} onClick={() => void action(reload)}>
                새로고침
              </Button>
            </div>
          </div>
          {!!failedSteps.length && (
            <div className="job-failure-actions" aria-label="실패 단계 확인">
              {failedSteps.map(({ agent, tool: failed }) => (
                <div key={agent.id}>
                  <span>{agent.label}</span>
                  <Button variant="secondary" onClick={() => openLogs(agent.id, failed.node_id)}>
                    로그 보기
                  </Button>
                  {agent.reason && <p role="alert">{agent.reason}</p>}
                </div>
              ))}
            </div>
          )}
          {job.processing_review && (
            <Button
              variant="quiet"
              onClick={() => {
                processingPanel.current?.scrollIntoView({ block: 'start' });
                processingPanel.current?.focus();
              }}
            >
              처리 확인
            </Button>
          )}
          {canManage && job.status === 'draft' && (
            <p className="job-start-scope">
              {toolDefinition?.nodes
                .filter(
                  (n) => n.model_ref && ['transcribe', 'translate', 'vocalize'].includes(n.type),
                )
                .map(
                  (n) =>
                    `${n.type === 'transcribe' ? '전사' : n.type === 'translate' ? '번역' : '보컬'} ${modelCallOptionLabel(n.options.max_model_calls)}`,
                )
                .join(' · ')}
              {' · 외부 모델 API 비용은 선택한 공급자 요금이 적용됩니다.'}
            </p>
          )}
          {job.output_mode === 'controlled' && <strong className="output-kind">통제 출력</strong>}
          <details className="shared-job-custody" aria-label="자료와 실행 기록">
            <summary>자료·실행 기록</summary>
            {!canManage && <strong>공용 읽기 전용</strong>}
            <dl>
              <div>
                <dt>원본 업로더</dt>
                <dd>{job.snapshot.asset.uploaded_by || job.asset_owner_id || '기록 없음'}</dd>
              </div>
              <div>
                <dt>작업 생성·실행 계정</dt>
                <dd>{job.executed_by || '기록 없음'}</dd>
              </div>
            </dl>
          </details>
          <JobFiles
            base={base}
            runs={job.runs}
            agents={job.agent_workflow?.nodes}
            manifest={job.artifact_manifest}
            stale={!!loadError}
          />
          {job.selected_inputs?.map((input) => (
            <p key={input.input}>
              {input.input === 'photo'
                ? '선택 사진 원본'
                : input.input === 'audio'
                  ? '같은 영상의 추출 WAV'
                  : '선택 시간 자막'}
              {input.segments !== undefined && ` · ${input.segments}구간`}
              {input.language &&
                ` · 원문 언어: ${input.language === 'auto' ? '미지정' : languageLabel(input.language)}`}
              {input.job_id && (
                <>
                  {' '}
                  · <a href={`#/jobs/${input.job_id}`}>입력 출처 작업</a>
                </>
              )}
              {input.kind === 'saved_subtitle' && input.copy_id && (
                <>
                  {' '}
                  ·{' '}
                  <a href={`#/subtitles/saved/${input.copy_id}`}>
                    저장 자막: {input.filename || '수정본'}
                  </a>
                </>
              )}
            </p>
          ))}
          {!job.agent_workflow && job.snapshot.options?.target_language && (
            <p>
              원문/대상 언어: {languageLabel(job.snapshot.options.source_language)} →{' '}
              {languageLabel(job.snapshot.options.target_language)}
            </p>
          )}
          {job.agent_workflow &&
            frozenGoalLanguages(job.snapshot.definition).map((language) => (
              <p key={language.id}>
                {language.label}: {languageLabel(language.value)}
              </p>
            ))}
          {job.parent_id && (
            <p>
              원 작업 <a href={'#/jobs/' + job.parent_id}>복구 출처 열기</a> · 원 기록은 변경하지
              않습니다.
            </p>
          )}
          {modelRolesEnabled && !job.agent_workflow && (
            <ModelRolePanel
              observationOnly
              key={id}
              jobId={id}
              revision={job.revision}
              status={job.status}
              canManage={canManage}
              hasRuns={job.runs.length > 0}
              onChanged={async () => {
                setPlan(null);
                setConsent(null);
                await reload();
              }}
            />
          )}
          {job.processing_review && (
            <div id="job-processing-review" ref={processingPanel} tabIndex={-1}>
              <JobProcessingReview jobId={id} onChanged={() => void reload()} />
            </div>
          )}
          <section className="job-execution" ref={resultsPanel}>
            {!agentDefinition && (
              <p role="alert">워크플로우를 불러오지 못했습니다. 새로고침해 주세요.</p>
            )}
            {agentDefinition && (
              <WorkflowCanvas
                definition={agentDefinition}
                catalog={catalog}
                selectedNodeId={selected}
                onSelect={(identity) => {
                  setSelected(identity);
                  setSelectedTool('');
                  setResultsTab('output');
                }}
                edgeStates={job.agent_workflow?.edges || {}}
                inputLabel={job.snapshot.asset.original_filename}
                inputThumbnail={
                  job.snapshot.inputs?.video?.type === 'video'
                    ? mediaUrl('/videos/' + job.snapshot.asset.asset_id + '/thumbnail')
                    : undefined
                }
                nodeStates={
                  job.agent_workflow
                    ? Object.fromEntries(
                        job.agent_workflow.nodes.map((agent) => [
                          agent.id,
                          { state: agent.state, label: agent.status_label, reason: agent.reason },
                        ]),
                      )
                    : Object.fromEntries(
                        job.runs.map((item) => [
                          item.node_id,
                          {
                            label:
                              !item.display_status &&
                              job.processing_review?.source_attempt_id === item.id
                                ? '원 실행 기록 보존'
                                : labels[item.display_status || item.status] || item.status,
                            state:
                              !item.display_status &&
                              job.processing_review?.source_attempt_id === item.id
                                ? 'review_required'
                                : item.display_status || item.status,
                          },
                        ]),
                      )
                }
                detailsLabel="노드 실행 결과"
                details={
                  selected ? (
                    <section className="execution-node-body renewal-node-results">
                      <TaskResultTabs
                        key={`${id}:${selected}`}
                        jobId={id}
                        runId={run?.id}
                        canManage={canManage}
                        unitRecoveryEnabled={renewalBackend}
                        onChanged={async () => {
                          await reload();
                        }}
                        activeTab={resultsTab}
                        onTabChange={setResultsTab}
                        initialState={
                          tool?.state || run?.display_status || run?.status || 'waiting'
                        }
                        toolbar={
                          currentAgent && (
                            <ol className="workflow-agent-tools" aria-label="에이전트 내부 처리">
                              {currentAgent.tools.map((item) => (
                                <li key={item.node_id} data-state={item.state}>
                                  <button
                                    type="button"
                                    aria-pressed={tool?.node_id === item.node_id}
                                    onClick={() => setSelectedTool(item.node_id)}
                                  >
                                    <span>{item.label}</span>
                                    <span>
                                      {(
                                        {
                                          waiting: '대기',
                                          preparing: '준비 중',
                                          running: '처리 중',
                                          completed: '완료',
                                          failed: '오류',
                                          cancelled: '취소됨',
                                        } as Record<string, string>
                                      )[item.state] || '확인 필요'}
                                    </span>
                                  </button>
                                </li>
                              ))}
                            </ol>
                          )
                        }
                      >
                        {modelRolesEnabled &&
                          currentAgent &&
                          ['transcription_agent', 'translation_agent'].includes(
                            currentAgent.type,
                          ) && (
                            <ModelRolePanel
                              key={`${id}:${currentAgent.id}`}
                              observationOnly
                              roleFilter={
                                currentAgent.type === 'transcription_agent'
                                  ? 'transcription'
                                  : 'translation'
                              }
                              jobId={id}
                              revision={job.revision}
                              status={job.status}
                              canManage={false}
                              hasRuns={job.runs.length > 0}
                              onChanged={reload}
                            />
                          )}
                        {run?.display_reason && run.display_reason !== currentAgent?.reason && (
                          <p role="alert">{run.display_reason}</p>
                        )}
                        {!Object.keys(outputs).length && <p>아직 출력 결과가 없습니다.</p>}
                        {Object.entries(run?.inputs || {}).map(([port, ref]) => (
                          <section className="execution-artifact" key={port}>
                            <h4>
                              {ref.type === 'video'
                                ? '입력 영상'
                                : ref.type === 'audio'
                                  ? '입력 음성'
                                  : '입력 자료'}
                            </h4>
                            {ref.type === 'video' && (
                              <video
                                controls
                                preload="metadata"
                                style={{ maxWidth: '100%' }}
                                src={mediaUrl(
                                  `${base}/inputs/${run?.id}/${encodeURIComponent(port)}/preview`,
                                )}
                              />
                            )}
                            <a
                              target="_blank"
                              rel="noreferrer"
                              href={mediaUrl(
                                `${base}/inputs/${run?.id}/${encodeURIComponent(port)}`,
                              )}
                            >
                              입력 자료 열기
                            </a>
                          </section>
                        ))}
                        {vocalization && (
                          <section aria-label="보컬 판정 실행 기록">
                            <h4>보컬 판정 실행 기록</h4>
                            <p>
                              기록된 호출: {vocalization.call_count ?? '확인 중'} · 완료 결과
                              재사용: {vocalization.reused_chunks ?? '확인 중'}
                            </p>
                            {vocalization.held && (
                              <p role="alert">
                                응답 확인이 필요해 중단했습니다. 자동으로 다시 호출하지 않습니다.
                              </p>
                            )}
                            {vocalization.error && (
                              <p>{translationLabels[vocalization.error] || vocalization.error}</p>
                            )}
                          </section>
                        )}
                        {translation && (
                          <section aria-label={`${traceLabel} 실행 기록`}>
                            <h4>{traceLabel} 실행 기록</h4>
                            <p>
                              사용 모델:{' '}
                              {translation.selected?.remote_model ||
                                translation.model?.model_id ||
                                '확인 기록 없음'}
                            </p>
                            <details>
                              <summary>모델 호출 상세</summary>
                              <ol>
                                {(translation.attempts || []).map((attempt) => (
                                  <li key={attempt.index}>
                                    {attempt.remote_model} · {attempt.protocol} · 모델 개정{' '}
                                    {attempt.revision} / 연결 개정 {attempt.connection_revision} ·{' '}
                                    {translationLabels[attempt.status] || attempt.status}
                                    {attempt.error
                                      ? ` · ${translationLabels[attempt.error] || attempt.error}`
                                      : ''}
                                    {attempt.transition
                                      ? ` · ${translationLabels[attempt.transition] || attempt.transition}`
                                      : ''}
                                  </li>
                                ))}
                              </ol>
                            </details>
                          </section>
                        )}
                        {run?.error_code && (
                          <p role="alert">{run.error_code} · 자동 재실행하지 않습니다.</p>
                        )}
                        {run?.result?.reused_from && (
                          <p>
                            이 결과는{' '}
                            <a href={'#/jobs/' + run.result.reused_from.job_id}>원 작업</a>의 완료
                          </p>
                        )}
                        {Object.entries(outputs).map(([port, ref]) => (
                          <section className="execution-artifact" key={port}>
                            <h4>{outputLabel(port, ref.type)}</h4>
                            {ref.type === 'video' &&
                              run?.result?.previews?.[port]?.status === 'ready' && (
                                <video
                                  src={url(port) + '/preview'}
                                  controls
                                  preload="metadata"
                                  style={{ maxWidth: '100%' }}
                                />
                              )}
                            {ref.type === 'video' && (
                              <FullVideoPreview
                                resource={`${base}/artifacts/${run?.id}/${encodeURIComponent(port)}/preview/full`}
                              />
                            )}
                            {ref.type === 'audio' && (
                              <audio src={url(port)} controls preload="metadata" />
                            )}
                            {ref.type === 'video' ? (
                              <>
                                <a href={url(port) + '?download=true'} download>
                                  작업 결과 원본 받기
                                </a>
                                {run?.result?.previews?.[port]?.status === 'ready' ? (
                                  <a href={url(port) + '/preview?download=true'} download>
                                    이전 30초 WebM 받기
                                  </a>
                                ) : (
                                  <p role="status">
                                    웹 전용 WebM 생성에 실패했습니다. 작업 결과 원본은 보존되어
                                    있습니다.
                                  </p>
                                )}
                              </>
                            ) : (
                              <>
                                <a href={url(port)} target="_blank" rel="noreferrer">
                                  파일 보기
                                </a>
                                <a href={url(port) + '?download=true'} download>
                                  파일 받기
                                </a>
                                <SrtCopyAction source={artifactSrtSource(base, run, port)} />
                              </>
                            )}
                            <details>
                              <summary>파일 상세</summary>
                              <p>{ref.bytes.toLocaleString()} bytes</p>
                            </details>
                          </section>
                        ))}
                        {review?.contract.kind === 'subtitle_tracks_v1' && (
                          <SubtitleTrackReview
                            review={review}
                            canManage={canManage}
                            assetId={job.snapshot.asset.asset_id}
                            onChanged={() => {
                              setPlan(null);
                              setConsent(null);
                              void reload();
                            }}
                          />
                        )}
                        {review &&
                          ['face_select', 'face_confirm_preview'].includes(
                            review.contract.kind || '',
                          ) && (
                            <FaceWorkflowReview
                              key={review.id}
                              initial={review}
                              jobId={job.id}
                              canManage={canManage}
                              active={job.status === 'review_required'}
                              changed={async () => {
                                setPlan(null);
                                setConsent(null);
                                await reload();
                              }}
                            />
                          )}
                        {review &&
                          !['subtitle_tracks_v1', 'face_select', 'face_confirm_preview'].includes(
                            review.contract.kind || '',
                          ) &&
                          !canManage && (
                            <section className="execution-review" aria-label="검수 내용 읽기 전용">
                              <h4>검수 내용 · 읽기 전용</h4>
                              <pre>{JSON.stringify(review.draft, null, 2)}</pre>
                            </section>
                          )}
                        {review &&
                          !['subtitle_tracks_v1', 'face_select', 'face_confirm_preview'].includes(
                            review.contract.kind || '',
                          ) &&
                          canManage && (
                            <section
                              aria-label="공통 검수"
                              className={
                                ['audio_regions_v1', 'audio_regions_long_v5'].includes(
                                  review.contract.kind || '',
                                )
                                  ? 'audio-region-review'
                                  : undefined
                              }
                            >
                              <h4>
                                {['audio_regions_v1', 'audio_regions_long_v5'].includes(
                                  review.contract.kind || '',
                                )
                                  ? '음성 보호·제거 구간 검수'
                                  : '자료 확인'}
                              </h4>
                              {['audio_regions_v1', 'audio_regions_long_v5'].includes(
                                review.contract.kind || '',
                              ) && (
                                <>
                                  <audio
                                    controls
                                    preload="none"
                                    src={mediaUrl('/renewal/reviews/' + review.id + '/source')}
                                  />
                                  <p>
                                    원본 오디오의 초 단위 구간입니다. 보호 구간은 적용 시 앞뒤
                                    0.3초를 더 보호하며, 겹친 제거 제안은 전체 취소합니다.
                                  </p>
                                  <p>
                                    후속 음성 필터가 off면 보호·제거 결정은 적용하지 않습니다.
                                    NVIDIA VAD를 선택하면 마지막에 VAD 유지 구간과 겹치는 부분만
                                    남습니다.
                                  </p>
                                  <p>
                                    직접 지정한 결정입니다. 자동 보컬 탐지·확인 결과가 아닙니다.
                                    저장·확정만으로 실행하지 않습니다.
                                  </p>
                                  <p>
                                    원본 길이 {review.contract.audio?.duration_seconds.toFixed(3)}초
                                    · 각 목록 최대 1,024개
                                  </p>
                                </>
                              )}
                              <DataForm
                                schema={reviewFields!}
                                value={drafts[review.id] ?? review.draft}
                                disabled={busy || review.status === 'confirmed'}
                                onChange={(value) => {
                                  if (value && typeof value === 'object' && !Array.isArray(value)) {
                                    setDrafts((previous) => ({ ...previous, [review.id]: value }));
                                  }
                                }}
                              />
                              <Button
                                variant="secondary"
                                disabled={busy || review.status === 'confirmed'}
                                onClick={() =>
                                  void action(async () => {
                                    await jsonPost('/renewal/reviews/' + review.id + '/save', {
                                      revision: review.revision,
                                      draft: drafts[review.id] ?? review.draft,
                                    });
                                    setDrafts((previous) => {
                                      const next = { ...previous };
                                      delete next[review.id];
                                      return next;
                                    });
                                    setPlan(null);
                                    setConsent(null);
                                  })
                                }
                              >
                                검수 저장
                              </Button>
                              <Button
                                disabled={
                                  busy || review.status === 'confirmed' || review.id in drafts
                                }
                                onClick={() =>
                                  void action(async () => {
                                    await jsonPost('/renewal/reviews/' + review.id + '/confirm', {
                                      revision: review.revision,
                                    });
                                    setPlan(null);
                                    setConsent(null);
                                  })
                                }
                              >
                                검수 확정
                              </Button>
                              <p>확정은 실행이 아닙니다. 새 계획 확인 뒤 별도로 이어 실행합니다.</p>
                            </section>
                          )}
                      </TaskResultTabs>
                    </section>
                  ) : (
                    <p>태스크를 선택하면 출력과 로그를 확인할 수 있습니다.</p>
                  )
                }
              />
            )}
          </section>
          {job.status === 'failed' && <ProjectionRecoveryPanel key={job.id} jobId={job.id} />}
          {toolDefinition?.nodes.some((item) => item.type === 'subtitle_outputs') && (
            <SubtitleOutputs jobId={job.id} revision={job.revision} />
          )}
          {canManage && (
            <section
              className="ticket-panel"
              aria-label="실행 승인"
              hidden={job.status === 'completed' || !!job.processing_review}
            >
              {['draft', 'waiting', 'running', 'review_required'].includes(job.status) && (
                <Button
                  variant="secondary"
                  disabled={cancelBusy}
                  onClick={() =>
                    void (async () => {
                      setCancelBusy(true);
                      setError('');
                      try {
                        const current = await reload();
                        if (
                          current.access?.can_manage !== true ||
                          !['draft', 'waiting', 'running', 'review_required'].includes(
                            current.status,
                          )
                        ) {
                          return;
                        }
                        await jsonPost(base + '/cancel', { revision: current.revision });
                        setConsent(null);
                        setPlan(null);
                        await reload();
                      } catch (reason) {
                        setError(reason instanceof Error ? reason.message : '취소 요청 실패');
                      } finally {
                        setCancelBusy(false);
                      }
                    })()
                  }
                >
                  작업 취소
                </Button>
              )}
              {['failed', 'cancelled'].includes(job.status) && (
                <>
                  <label>
                    <input
                      type="checkbox"
                      checked={risk}
                      onChange={(event) => setRisk(event.target.checked)}
                    />
                    미확정 처리의 중복 실행 위험을 확인했고, 새 복구 작업을 만들겠습니다.
                  </label>
                  <Button
                    disabled={busy || !risk}
                    onClick={() =>
                      void action(async () => {
                        const next = await jsonPost<{ id: string }>(base + '/recover', {
                          request_id: nonces.current.recover,
                          acknowledge_duplicate_risk: risk,
                        });
                        location.hash = '/jobs/' + next.id;
                      })
                    }
                  >
                    새 복구 작업 만들기
                  </Button>
                </>
              )}
            </section>
          )}
        </>
      )}
    </main>
  );
};
