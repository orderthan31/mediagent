import { useEffect, useRef, useState } from 'react';
import { request, mediaUrl } from './api';
import { jsonPost } from './video-api';
import { PageTitle } from './PageTitle';
import { Button } from './hangyeol/primitives/button';
import { WorkflowCanvas, type CanvasDefinition, type CanvasSpec } from './WorkflowCanvas';
import { DataForm } from './DataForm';
import type { FieldSchema, FormData } from './form-contract';
import './job-detail.css';
import './workflow-tickets.css';
import './job-execution.css';
import './renewal-runtime.css';

type Reference = { storage_key: string; sha256: string; bytes: number; type: string };
type Run = {
  id: string;
  node_id: string;
  node_type: string;
  status: string;
  options: Record<string, string>;
  inputs: Record<string, Reference>;
  error_code?: string;
  result: {
    outputs: Record<string, Reference>;
    previews?: Record<string, { status: string }>;
    reused_from?: { job_id: string };
  } | null;
};
type Review = {
  id: string;
  node_run_id: string;
  revision: number;
  status: string;
  draft: FormData;
  contract: { fields: FieldSchema; source: Reference };
};
type State = {
  id: string;
  ticket_number: number;
  revision: number;
  status: string;
  parent_id: string | null;
  snapshot: {
    asset: { asset_id: string; original_filename: string };
    definition: CanvasDefinition;
  };
  runs: Run[];
  reviews: Review[];
};
type Plan = { token: string; ready: boolean; reasons: string[]; notice: string };
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
  const run = job?.runs.find((item) => item.node_id === selected);
  const node = job?.snapshot.definition.nodes.find((item) => item.id === selected);
  const review = job?.reviews.find((item) => item.node_run_id === run?.id);
  const outputs = run?.result?.outputs || {};
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
      <PageTitle>{job ? `작업 #${job.ticket_number}` : '작업 불러오는 중'}</PageTitle>
      {error && (
        <p role="alert" className="alert">
          {error}
        </p>
      )}
      {job && (
        <>
          <div className="job-detail-toolbar">
            <a href={'#/videos/' + job.snapshot.asset.asset_id}>
              {job.snapshot.asset.original_filename}
            </a>
            <strong role="status">{labels[job.status] || job.status}</strong>
            <Button variant="quiet" disabled={busy} onClick={() => void action(reload)}>
              새로고침
            </Button>
          </div>
          {job.parent_id && (
            <p>
              원 작업 <a href={'#/jobs/' + job.parent_id}>복구 출처 열기</a> · 원 기록은 변경하지
              않습니다.
            </p>
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
                  { label: labels[item.status] || item.status, state: item.status },
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
                    <p>{run ? labels[run.status] || run.status : '아직 실행하지 않았습니다.'}</p>
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
                          run?.result?.previews?.[port]?.status !== 'failed' && (
                            <video
                              src={url(port) + '/preview'}
                              controls
                              preload="metadata"
                              style={{ maxWidth: '100%' }}
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
                            {run?.result?.previews?.[port]?.status !== 'failed' ? (
                              <a href={url(port) + '/preview?download=true'} download>
                                WebM 받기
                              </a>
                            ) : (
                              <p role="status">
                                웹 전용 WebM 생성에 실패했습니다. 작업 결과 원본은 보존되어
                                있습니다.
                              </p>
                            )}
                          </>
                        ) : (
                          <a href={url(port)} target="_blank" rel="noreferrer">
                            산출물 열기
                          </a>
                        )}
                        <p>
                          {ref.bytes.toLocaleString()} bytes · SHA-256 {ref.sha256}
                        </p>
                      </section>
                    ))}
                    {review && (
                      <section aria-label="공통 검수">
                        <h4>자료 확인</h4>
                        <DataForm
                          schema={review.contract.fields}
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
          <section
            className="ticket-panel"
            aria-label="실행 승인"
            hidden={job.status === 'completed'}
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
                disabled={busy}
                onClick={() =>
                  void action(async () => {
                    await jsonPost(base + '/cancel', { revision: job.revision });
                    setConsent(null);
                    setPlan(null);
                  })
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
        </>
      )}
    </main>
  );
};
