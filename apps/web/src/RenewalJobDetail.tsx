import { useEffect, useRef, useState } from 'react';
import { request, mediaUrl } from './api';
import { jsonPost } from './video-api';
import { FullVideoPreview } from './FullVideoPreview';
import { dispatchLabel } from './dispatch-status';
import { processingLabel, type ProcessingProjection } from './processing-review-state';
import { JobProcessingReview } from './JobProcessingReview';
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
  selected?: { remote_model: string } | null;
  attempts: {
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
type Run = {
  id: string;
  node_id: string;
  node_type: string;
  status: string;
  dispatch?: { phase: string };
  options: Record<string, string>;
  inputs: Record<string, Reference>;
  error_code?: string;
  translation?: TranslationTrace;
  transcription?: TranslationTrace;
  result: {
    outputs: Record<string, Reference>;
    previews?: Record<string, { status: string }>;
    reused_from?: { job_id: string };
    translation?: TranslationTrace;
    transcription?: TranslationTrace;
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
type State = {
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
  parent_id: string | null;
  snapshot: {
    asset: { asset_id: string; original_filename: string; uploaded_by?: string };
    definition: CanvasDefinition;
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
  draft: '실행 전',
  waiting: '실행 대기',
  running: '처리 중',
  completed: '완료',
  failed: '실패 · 기록 보존',
  cancelled: '취소 · 기록 보존',
  cancelling: '취소 접수 · 진행 처리 정리 중',
  review_required: '검수 대기',
  skipped: '미선택',
  blocked: '선행 실패로 차단',
  quarantined: '늦은 결과 격리',
};

export const RenewalJobDetail = ({ id }: { id: string }) => {
  const [job, setJob] = useState<State | null>(null);
  const [catalog, setCatalog] = useState<CanvasSpec[]>([]);
  const [selected, setSelected] = useState('');
  const [plan, setPlan] = useState<Plan | null>(null);
  const [consent, setConsent] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [cancelBusy, setCancelBusy] = useState(false);
  const [error, setError] = useState('');
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
  const canManage = job?.access?.can_manage === true;
  const run = job?.runs.find((item) => item.node_id === selected);
  const node = job?.snapshot.definition.nodes.find((item) => item.id === selected);
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
  const translation =
    run?.result?.transcription ||
    run?.transcription ||
    run?.result?.translation ||
    run?.translation;
  const traceLabel = run?.node_type === 'transcribe' ? '전사' : '번역';
  const url = (port: string) =>
    mediaUrl(`${base}/artifacts/${run?.id}/${encodeURIComponent(port)}`);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      try {
        const [next, specs] = await Promise.all([
          request<State>(base, { signal: controller.signal }),
          request<{ nodes: CanvasSpec[] }>('/work-entry/catalog', { signal: controller.signal }),
        ]);
        if (!controller.signal.aborted) {
          setJob(next);
          setCatalog(specs.nodes);
        }
      } catch (reason) {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : '작업 조회 실패');
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
  }, [base]);
  return (
    <main className="job-detail ticket-detail job-detail-canvas">
      <PageTitle>{job ? `작업 #${job.ticket_number}` : '작업'}</PageTitle>
      {error && (
        <p role="alert" className="alert">
          {error}
        </p>
      )}
      {!job && !error && <LoadingSkeleton layout="canvas" label="작업 상세 불러오는 중" />}
      {job && (
        <>
          <div className="job-detail-toolbar">
            <a href={'#/videos/' + job.snapshot.asset.asset_id}>
              {job.snapshot.asset.original_filename}
            </a>
            <strong role="status">
              {processingLabel(job.processing_review) || labels[job.status] || job.status}
            </strong>
            <Button variant="quiet" disabled={busy} onClick={() => void action(reload)}>
              새로고침
            </Button>
          </div>
          <section className="shared-job-custody" aria-label="자료와 실행 기록">
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
          </section>
          {job.artifact_manifest && (
            <section className="shared-job-custody" aria-label="티켓별 산출물">
              <strong>정상 채택 산출물 {job.artifact_manifest.entry_count}개</strong>
              <p>
                {job.artifact_manifest.layout === 'ticket_v1'
                  ? '티켓 기준 저장 · 중간·최종 산출물을 포함합니다.'
                  : '기존 CAS 참조 · 자료를 이동하지 않고 조회합니다.'}
              </p>
              {job.artifact_manifest.entry_count > 0 && (
                <a href={mediaUrl(base + '/manifest?download=true')} download>
                  산출물 manifest 받기
                </a>
              )}
            </section>
          )}
          {job.snapshot.options?.target_language && (
            <p>
              원문/대상 언어: {job.snapshot.options.source_language} →{' '}
              {job.snapshot.options.target_language} · 티켓 고정 설정
            </p>
          )}
          {job.parent_id && (
            <p>
              원 작업 <a href={'#/jobs/' + job.parent_id}>복구 출처 열기</a> · 원 기록은 변경하지
              않습니다.
            </p>
          )}
          {job.processing_review && (
            <JobProcessingReview jobId={id} onChanged={() => void reload()} />
          )}
          <section className="job-execution">
            <WorkflowCanvas
              definition={job.snapshot.definition}
              catalog={catalog}
              onSelect={setSelected}
              inputLabel={job.snapshot.asset.original_filename}
              inputThumbnail={mediaUrl('/videos/' + job.snapshot.asset.asset_id + '/thumbnail')}
              nodeStates={Object.fromEntries(
                job.runs.map((item) => [
                  item.node_id,
                  {
                    label:
                      job.processing_review?.source_attempt_id === item.id
                        ? '원 실행 기록 보존'
                        : labels[item.status] || item.status,
                    state:
                      job.processing_review?.source_attempt_id === item.id
                        ? 'review_required'
                        : item.status,
                  },
                ]),
              )}
              detailsLabel="노드 실행 결과"
              details={
                selected ? (
                  <section className="execution-node-body renewal-node-results">
                    <h3>
                      {node
                        ? catalog.find((spec) => spec.id === node.type)?.label || node.type
                        : '원본 입력'}
                    </h3>
                    {node && (
                      <dl>
                        {Object.entries(node.options).map(([key, value]) => (
                          <div key={key}>
                            <dt>{key}</dt>
                            <dd>{value}</dd>
                          </div>
                        ))}
                      </dl>
                    )}
                    <p>
                      {run
                        ? dispatchLabel(run.status, run.dispatch?.phase) ||
                          labels[run.status] ||
                          run.status
                        : '아직 실행하지 않았습니다.'}
                    </p>
                    {Object.entries(run?.inputs || {}).map(([port, ref]) => (
                      <section className="execution-artifact" key={port}>
                        <h4>고정 입력 · {port}</h4>
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
                          href={mediaUrl(`${base}/inputs/${run?.id}/${encodeURIComponent(port)}`)}
                        >
                          입력 자료 열기
                        </a>
                      </section>
                    ))}
                    {translation && (
                      <section aria-label={`${traceLabel} 실행 기록`}>
                        <h4>{traceLabel} 실행 기록</h4>
                        <p>최종 채택: {translation.selected?.remote_model || '없음'}</p>
                        <ol>
                          {translation.attempts.map((attempt) => (
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
                      </section>
                    )}
                    {run?.error_code && (
                      <p role="alert">{run.error_code} · 자동 재실행하지 않습니다.</p>
                    )}
                    {run?.result?.reused_from && (
                      <p>
                        이 결과는 <a href={'#/jobs/' + run.result.reused_from.job_id}>원 작업</a>의
                        검증된 완료 결과입니다.
                      </p>
                    )}
                    {Object.entries(outputs).map(([port, ref]) => (
                      <section className="execution-artifact" key={port}>
                        <h4>
                          {port} · {ref.type}
                        </h4>
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
                              산출물 열기
                            </a>
                            <a href={url(port) + '?download=true'} download>
                              산출물 받기
                            </a>
                          </>
                        )}
                        <p>
                          {ref.bytes.toLocaleString()} bytes · SHA-256 {ref.sha256}
                        </p>
                      </section>
                    ))}
                    {review && !canManage && (
                      <section className="execution-review" aria-label="검수 내용 읽기 전용">
                        <h4>검수 내용 · 읽기 전용</h4>
                        <pre>{JSON.stringify(review.draft, null, 2)}</pre>
                      </section>
                    )}
                    {review && canManage && (
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
                              원본 오디오의 초 단위 구간입니다. 보호 구간은 적용 시 앞뒤 0.3초를 더
                              보호하며, 겹친 제거 제안은 전체 취소합니다.
                            </p>
                            <p>
                              후속 음성 필터가 off면 보호·제거 결정은 적용하지 않습니다. NVIDIA
                              VAD를 선택하면 마지막에 VAD 유지 구간과 겹치는 부분만 남습니다.
                            </p>
                            <p>
                              직접 지정한 결정입니다. 자동 보컬 탐지·확인 결과가 아닙니다.
                              저장·확정만으로 실행하지 않습니다.
                            </p>
                            <p>
                              원본 길이 {review.contract.audio?.duration_seconds.toFixed(3)}초 · 각
                              목록 최대 1,024개
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
                          disabled={busy || review.status === 'confirmed' || review.id in drafts}
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
                  </section>
                ) : (
                  <p>노드를 선택하면 적용 설정과 실제 산출물을 확인할 수 있습니다.</p>
                )
              }
            />
          </section>
          {canManage && (
            <section
              className="ticket-panel"
              aria-label="실행 승인"
              hidden={job.status === 'completed' || !!job.processing_review}
            >
              {['draft', 'review_required'].includes(job.status) && (
                <>
                  <Button
                    variant="secondary"
                    disabled={busy}
                    onClick={() =>
                      void action(async () => {
                        const next = await request<Plan>(base + '/plan');
                        setPlan(next);
                        setConsent(null);
                        nonces.current.confirm = crypto.randomUUID();
                        nonces.current.admit = crypto.randomUUID();
                      })
                    }
                  >
                    실행 계획 확인
                  </Button>
                  {plan && (
                    <>
                      <p>{plan.notice}</p>
                      {plan.reasons.map((reason) => (
                        <p key={reason} role="status">
                          {reason}
                        </p>
                      ))}
                      <Button
                        disabled={busy || !plan.ready || !!consent}
                        onClick={() =>
                          void action(async () => {
                            const response = await jsonPost<{ id: string }>(base + '/confirm', {
                              token: plan.token,
                              request_id: nonces.current.confirm,
                            });
                            setConsent(response.id);
                          })
                        }
                      >
                        계획 동의 저장
                      </Button>
                    </>
                  )}
                </>
              )}
              {consent && (
                <Button
                  disabled={busy}
                  onClick={() =>
                    void action(async () => {
                      await jsonPost(base + '/admit', {
                        consent_id: consent,
                        request_id: nonces.current.admit,
                      });
                      setConsent(null);
                      setPlan(null);
                      await jsonPost(base + '/run', {});
                    })
                  }
                >
                  실행 요청
                </Button>
              )}
              {['waiting', 'running'].includes(job.status) && (
                <Button
                  disabled={busy}
                  onClick={() => void action(() => jsonPost(base + '/run', {}))}
                >
                  승인된 처리 진행
                </Button>
              )}
              {['draft', 'waiting', 'running', 'review_required'].includes(job.status) && (
                <Button
                  variant="secondary"
                  disabled={cancelBusy}
                  onClick={() =>
                    void (async () => {
                      setCancelBusy(true);
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
