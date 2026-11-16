import { modelCallOptionLabel } from './model-call-budget';
import { FaceWorkflowReview } from './FaceWorkflowReview';
import { publicAgentGraph } from './job-graphs';
import type { GoalOutput } from './GoalResults';
import { JobFiles } from './JobFiles';
import { jobStateLabel } from './job-display';
import { languageLabel } from './language-label';
import { frozenGoalLanguages } from './goal-languages';
import { getJobStartState, startTrackedJob, subscribeJobStarts } from './job-start.mjs';
import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { request, mediaUrl } from './api';
import { jsonPost } from './video-api';
import type { ProcessingProjection } from './processing-review-state';
import { JobProcessingReview } from './JobProcessingReview';
import { ProjectionRecoveryPanel } from './ProjectionRecoveryPanel';
import { ModelRolePanel } from './ModelRolePanel';
import { JobTaskInspector } from './JobTaskInspector';
import { JobExecutionWorkspace, type WorkspaceTab } from './JobExecutionWorkspace';
import { JobLogExplorer } from './JobLogExplorer';
import { renewalBackend } from './preview';
import { SubtitleTrackReview } from './SubtitleTracksPanel';
import { PageTitle } from './PageTitle';
import { LoadingSkeleton } from './LoadingSkeleton';
import { Button } from './hangyeol/primitives/button';
import type { CanvasDefinition, CanvasSpec } from './WorkflowCanvas';
import { JobExecutionFlow } from './JobExecutionFlow';
import type { ExecutionProgressMap, ExecutionRunProgress } from './job-execution-flow';
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
  progress?: ExecutionRunProgress['progress'];
  status: string;
  started_at?: string | null;
  completed_at?: string | null;
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
    asset: {
      asset_id: string;
      original_filename: string;
      uploaded_by?: string;
      size_bytes?: number;
      sha256?: string;
    };
    inputs?: Record<string, { type: string }>;
    definition: CanvasDefinition;
    tool_definition?: CanvasDefinition;
    options?: { source_language?: string; target_language?: string };
  };
  runs: Run[];
  reviews: Review[];
};
type Plan = { token: string; ready: boolean; reasons: string[]; notice: string };
export const RenewalJobDetail = ({ id }: { id: string }) => <JobDetailSession key={id} id={id} />;

const JobDetailSession = ({ id }: { id: string }) => {
  const start = useSyncExternalStore(subscribeJobStarts, () => getJobStartState(id));
  const [job, setJob] = useState<State | null>(null);

  const [modelRolesEnabled, setModelRolesEnabled] = useState(false);
  const [selected, setSelected] = useState('');
  const [selectedTool, setSelectedTool] = useState('');
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [, setPlan] = useState<Plan | null>(null);
  const [, setConsent] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [cancelBusy, setCancelBusy] = useState(false);
  const [error, setError] = useState('');
  const [loadError, setLoadError] = useState('');
  const [workspaceTab, setWorkspaceTab] = useState<WorkspaceTab>('progress');
  const [logRunId, setLogRunId] = useState('');
  const [dataRunId, setDataRunId] = useState('');
  const [dataSelectionRequest, setDataSelectionRequest] = useState(0);
  const [logFocusRequest, setLogFocusRequest] = useState(0);
  const [logFocusErrors, setLogFocusErrors] = useState(false);
  const [manualSelection, setManualSelection] = useState(0);
  const [panelRequest, setPanelRequest] = useState(0);
  const resultsPanel = useRef<HTMLElement>(null);
  const filesPanel = useRef<HTMLDivElement>(null);
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
  const inspectStage = (agentId: string, toolId?: string) => {
    setWorkspaceTab('progress');
    setDetailsOpen(true);
    setSelected(agentId);
    setSelectedTool(toolId || '');
    setManualSelection((value) => value + 1);
    setPanelRequest((value) => value + 1);
  };
  const openRunLogs = (identity: string, errorsOnly = false) => {
    setLogRunId(identity);
    setWorkspaceTab('logs');
    setLogFocusErrors(errorsOnly);
    setLogFocusRequest((value) => value + 1);
  };
  const openLogs = (agentId: string, toolId: string) => {
    const item = job?.agent_workflow?.nodes
      .find((agent) => agent.id === agentId)
      ?.tools.find((candidate) => candidate.node_id === toolId);
    if (item?.run_id) {
      openRunLogs(item.run_id, ['failed', 'quarantined'].includes(item.state));
    }
  };
  const openRecovery = (agentId: string, toolId: string) => inspectStage(agentId, toolId);
  const inspectRun = (identity: string) => {
    const agent = job?.agent_workflow?.nodes.find((candidate) =>
      candidate.tools.some((item) => item.run_id === identity),
    );
    const item = agent?.tools.find((candidate) => candidate.run_id === identity);
    if (agent && item) {
      inspectStage(agent.id, item.node_id);
    }
  };
  const openData = (identity = '') => {
    setDataRunId(identity);
    setDataSelectionRequest((value) => value + 1);
    setWorkspaceTab('data');
  };
  useEffect(() => {
    if (panelRequest) {
      const frame = requestAnimationFrame(() => {
        if (workspaceTab === 'progress') {
          const panel = resultsPanel.current?.querySelector<HTMLElement>('.unit-recovery');
          if (panel) {
            panel.querySelector<HTMLButtonElement>('button')?.focus({ preventScroll: true });
            panel.scrollIntoView({ block: 'start' });
            return;
          }
        }
        const tab =
          resultsPanel.current?.querySelector<HTMLButtonElement>('.job-task-inspector h3');
        tab?.focus({ preventScroll: true });
        tab?.scrollIntoView({ block: 'nearest' });
      });
      return () => cancelAnimationFrame(frame);
    }
  }, [selected, panelRequest, workspaceTab]);
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
                  {renewalBackend &&
                    canManage &&
                    ['transcribe', 'translate'].includes(failed.role) && (
                      <Button
                        variant="secondary"
                        onClick={() => openRecovery(agent.id, failed.node_id)}
                      >
                        구간 복구
                      </Button>
                    )}
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
          {!canManage && <p>읽기 전용</p>}
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
          <JobExecutionWorkspace
            activeTab={workspaceTab}
            onTabChange={setWorkspaceTab}
            status={jobStateLabel(job)}
            selectedStageId={selected}
            metadata={[
              { label: '작업', value: `#${job.ticket_number}` },
              ...frozenGoalLanguages(job.snapshot.definition).map((item) => ({
                label: item.label,
                value: languageLabel(item.value),
              })),
            ]}
            stages={(job.agent_workflow?.nodes || []).map((agent) => {
              const selectedTool = agent.tools.find(
                (item) => item.node_id === agent.selected_tool_id,
              );
              const currentRun = job.runs.find((item) => item.id === selectedTool?.run_id);
              return {
                id: agent.id,
                label: agent.label,
                state: agent.state,
                reason: agent.reason,
                runId: currentRun?.id,
                completed: currentRun?.progress?.completed_segments,
                failed: currentRun?.progress?.failed_segments,
                planned: currentRun?.progress?.planned_segments,
              };
            })}
            onStageSelect={(identity) => inspectStage(identity)}
            onStageLogs={(identity, runId) =>
              openRunLogs(
                runId,
                !!job.agent_workflow?.nodes.some(
                  (agent) =>
                    agent.id === identity && ['failed', 'quarantined'].includes(agent.state),
                ),
              )
            }
            progress={
              <section className="job-execution" ref={resultsPanel}>
                {!agentDefinition && (
                  <p role="alert">워크플로우를 불러오지 못했습니다. 새로고침해 주세요.</p>
                )}
                {agentDefinition && (
                  <JobExecutionFlow
                    executionId={job.id}
                    definition={agentDefinition}
                    agents={job.agent_workflow?.nodes || []}
                    selectedNodeId={selected || undefined}
                    interactionKey={manualSelection}
                    onSelect={(identity, source) => {
                      setSelected(identity);
                      setSelectedTool('');
                      if (source !== 'follow') {
                        setDetailsOpen(true);
                        setPanelRequest((value) => value + 1);
                      }
                    }}
                    progressByRunId={
                      Object.fromEntries(
                        job.runs
                          .filter((item) => item.progress)
                          .map((item) => [
                            item.id,
                            {
                              run_id: item.id,
                              state: item.status,
                              display_state: item.display_status || item.status,
                              progress: item.progress,
                            },
                          ]),
                      ) as ExecutionProgressMap
                    }
                    edgeStates={job.agent_workflow?.edges || {}}
                    details={
                      selected && detailsOpen ? (
                        <section className="execution-node-body renewal-node-results">
                          <JobTaskInspector
                            key={`${id}:${selected}`}
                            jobId={id}
                            runId={run?.id}
                            canManage={canManage}
                            unitRecoveryEnabled={
                              renewalBackend &&
                              ['transcribe', 'translate'].includes(
                                tool?.role || run?.node_type || '',
                              )
                            }
                            onChanged={async () => {
                              await reload();
                            }}
                            title={currentAgent?.label || '선택한 단계'}
                            state={tool?.state || run?.display_status || run?.status || 'waiting'}
                            toolbar={
                              currentAgent && (
                                <label className="job-task-run-picker">
                                  실행 단계
                                  <select
                                    aria-label="실행 단계"
                                    value={tool?.node_id || ''}
                                    onChange={(event) => setSelectedTool(event.target.value)}
                                  >
                                    {currentAgent.tools.map((item) => (
                                      <option key={item.node_id} value={item.node_id}>
                                        {item.label}
                                      </option>
                                    ))}
                                  </select>
                                </label>
                              )
                            }
                          >
                            {run?.display_reason && run.display_reason !== currentAgent?.reason && (
                              <p role="alert">{run.display_reason}</p>
                            )}
                            {run?.error_code && (
                              <p role="alert">{run.error_code} · 자동 재실행하지 않습니다.</p>
                            )}
                            {run?.result?.reused_from && (
                              <p>
                                이 결과는{' '}
                                <a href={'#/jobs/' + run.result.reused_from.job_id}>원 작업</a>의
                                완료
                              </p>
                            )}
                            {run?.status === 'completed' && !review && (
                              <p>
                                <Button variant="quiet" onClick={() => openData(run?.id || '')}>
                                  결과 파일로 이동
                                </Button>
                              </p>
                            )}
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
                              ![
                                'subtitle_tracks_v1',
                                'face_select',
                                'face_confirm_preview',
                              ].includes(review.contract.kind || '') &&
                              !canManage && (
                                <section
                                  className="execution-review"
                                  aria-label="검수 내용 읽기 전용"
                                >
                                  <h4>검수 내용 · 읽기 전용</h4>
                                  <pre>{JSON.stringify(review.draft, null, 2)}</pre>
                                </section>
                              )}
                            {review &&
                              ![
                                'subtitle_tracks_v1',
                                'face_select',
                                'face_confirm_preview',
                              ].includes(review.contract.kind || '') &&
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
                                        원본 길이{' '}
                                        {review.contract.audio?.duration_seconds.toFixed(3)}초 · 각
                                        목록 최대 1,024개
                                      </p>
                                    </>
                                  )}
                                  <DataForm
                                    schema={reviewFields!}
                                    value={drafts[review.id] ?? review.draft}
                                    disabled={busy || review.status === 'confirmed'}
                                    onChange={(value) => {
                                      if (
                                        value &&
                                        typeof value === 'object' &&
                                        !Array.isArray(value)
                                      ) {
                                        setDrafts((previous) => ({
                                          ...previous,
                                          [review.id]: value,
                                        }));
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
                                        await jsonPost(
                                          '/renewal/reviews/' + review.id + '/confirm',
                                          {
                                            revision: review.revision,
                                          },
                                        );
                                        setPlan(null);
                                        setConsent(null);
                                      })
                                    }
                                  >
                                    검수 확정
                                  </Button>
                                  <p>
                                    확정은 실행이 아닙니다. 새 계획 확인 뒤 별도로 이어 실행합니다.
                                  </p>
                                </section>
                              )}
                          </JobTaskInspector>
                        </section>
                      ) : null
                    }
                  />
                )}
              </section>
            }
            data={
              <div ref={filesPanel} data-selected-run={dataRunId || undefined}>
                <JobFiles
                  base={base}
                  runs={job.runs}
                  agents={job.agent_workflow?.nodes}
                  stageLabels={Object.fromEntries(
                    (job.agent_workflow?.nodes || []).flatMap((agent) =>
                      agent.tools.map((item) => [item.node_id, `${agent.label} · ${item.label}`]),
                    ),
                  )}
                  selectedRunId={dataRunId || undefined}
                  selectionRequest={dataSelectionRequest}
                  onOpenLogs={(identity) =>
                    openRunLogs(
                      identity,
                      ['failed', 'quarantined'].includes(
                        job.runs.find((item) => item.id === identity)?.display_status ||
                          job.runs.find((item) => item.id === identity)?.status ||
                          '',
                      ),
                    )
                  }
                  originalSource={{
                    asset_id: job.snapshot.asset.asset_id,
                    original_filename: job.snapshot.asset.original_filename,
                    bytes: job.snapshot.asset.size_bytes,
                    sha256: job.snapshot.asset.sha256,
                  }}
                  stale={!!loadError}
                  subtitleOutputsEnabled={
                    !!toolDefinition?.nodes.some((item) => item.type === 'subtitle_outputs')
                  }
                  revision={job.revision}
                />
              </div>
            }
            logs={
              <JobLogExplorer
                jobId={id}
                enabled={workspaceTab === 'logs'}
                runs={job.runs.map((item) => {
                  const agent = job.agent_workflow?.nodes.find((candidate) =>
                    candidate.tools.some((tool) => tool.run_id === item.id),
                  );
                  const tool = agent?.tools.find((candidate) => candidate.run_id === item.id);
                  return {
                    id: item.id,
                    node_id: item.node_id,
                    label: tool?.label || item.node_type,
                    agentLabel: agent?.label,
                  };
                })}
                runId={logRunId}
                onRunChange={setLogRunId}
                focusRequest={logFocusRequest}
                focusErrors={logFocusErrors}
                onOpenData={openData}
                onOpenStage={inspectRun}
              />
            }
          />
          {job.status === 'failed' && <ProjectionRecoveryPanel key={job.id} jobId={job.id} />}
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
