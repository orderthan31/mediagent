import { useEffect, useState } from 'react';
import { request } from './api';
import { frontendOnly } from './preview';
import { Button } from './hangyeol/primitives/button';
import { BrokerAgentStatus } from './BrokerAgentStatus';
import { ProcessingReviewInbox } from './JobProcessingReview';
import { LoadingSkeleton } from './LoadingSkeleton';
import type { BrokerObservation } from './broker-agent-status';
import './agent-operations.css';

type Instance = {
  id: string;
  state: string;
  pid: number | null;
  in_flight: number;
  completed: number;
  observed_at: string;
};
export type AgentRuntime = {
  agent_id: string;
  revision: number;
  enabled: boolean | null;
  replicas: number | null;
  ready_replicas: number | null;
  draining_replicas: number | null;
  state: string;
  manageable: boolean;
  control_available?: boolean;
  control_registered?: boolean;
  observed_replicas?: number | null;
  control?: { request_id: string | null; phase: string | null; error_code?: string | null };
  runtime: string;
  max_replicas: number;
  concurrency_per_instance: number;
  dependencies: string[];
  unavailable_reason: string | null;
  instances: Instance[];
  observation_source?: string;
  observed_at?: string;
  consumers?: number | null;
  messages_ready?: number | null;
  observations?: BrokerObservation[];
  activity?: { running: number; expired: number; completed: number };
  telemetry?: boolean;
  ttl_seconds?: number;
  collector?: { healthy: boolean; received_at: string | null };
  workers?: {
    worker_id: string;
    boot_id: string;
    family: string;
    role: string;
    state: string;
    received_at: string | null;
    ticket_id: string | null;
    ticket_number: number | null;
    node_id: string | null;
    attempt_id: string | null;
    recent_events: {
      state: string;
      received_at: string;
      ticket_number: number | null;
      node_id: string | null;
    }[];
  }[];
};
const states: Record<string, string> = {
  ready: '준비됨',
  starting: '시작 중',
  draining: '작업 마무리 중',
  stopped: '중지됨',
  failed: '실패',
  degraded: '목표 미달',
  unknown: '상태 확인 필요',
};
export const AgentOperations = ({ identity }: { identity: string }) => {
  const [runtime, setRuntime] = useState<AgentRuntime | null>(null);
  const [brokerMode, setBrokerMode] = useState(false);
  const [enabled, setEnabled] = useState(false);
  const [replicas, setReplicas] = useState(1);
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const dirty =
    runtime && (enabled !== runtime.enabled || (enabled && replicas !== runtime.replicas));
  const accept = (value: AgentRuntime) => {
    setRuntime(value);
    setEnabled(value.enabled ?? false);
    setReplicas(value.replicas || 1);
    setRevision(value.revision);
  };
  const save = async () => {
    if (
      !runtime ||
      busy ||
      !Number.isInteger(replicas) ||
      replicas < 1 ||
      replicas > runtime.max_replicas
    ) {
      return;
    }
    setBusy(true);
    setError('');
    setNotice('');
    try {
      await request<AgentRuntime>(`/admin/agents/${identity}/configuration`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ revision, enabled, replicas: enabled ? replicas : 0 }),
      });
      // Confirm actual observed state with a separate read, not just the write response.
      const observed = await request<AgentRuntime>(`/admin/agents/${identity}`);
      accept(observed);
      setNotice(
        observed.state === 'ready'
          ? '설정과 실행 상태를 확인했습니다.'
          : observed.state === 'stopped'
            ? '에이전트가 중지됐습니다.'
            : '설정은 저장됐습니다. 아래 실제 실행 상태를 확인하세요.',
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '설정을 적용하지 못했습니다.');
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => {
    if (frontendOnly) {
      return;
    }
    const controller = new AbortController();
    let initial = true;
    let observedBroker = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const value = await request<AgentRuntime>(`/admin/agents/${identity}`, {
          signal: controller.signal,
        });
        if (!controller.signal.aborted) {
          setError('');
          observedBroker = ['amqp', 'fixed_host'].includes(value.observation_source ?? '');
          setBrokerMode(observedBroker);
          if (initial) {
            accept(value);
            initial = false;
          } else {
            setRuntime(value);
          }
        }
      } catch (reason) {
        if (!controller.signal.aborted) {
          // Keep read-only broker identities; never retain editable local controls after failure.
          if (!observedBroker) {
            setRuntime(null);
            initial = true;
          }
          setError(reason instanceof Error ? reason.message : '실행 상태를 불러오지 못했습니다.');
        }
      } finally {
        if (!controller.signal.aborted) {
          timer = setTimeout(poll, 3000);
        }
      }
    };
    void poll();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [identity]);
  if (!frontendOnly && brokerMode) {
    return (
      <>
        <BrokerAgentStatus runtime={runtime} error={error} onObserved={accept} />
        {identity === 'encode' && <ProcessingReviewInbox />}
      </>
    );
  }
  return (
    <section className="agent-operations" aria-label="에이전트 운영 관리">
      <h2>운영 관리</h2>
      {frontendOnly ? (
        <p role="status">
          미리보기에서는 실제 에이전트를 실행하거나 운영 설정을 변경하지 않습니다.
        </p>
      ) : (
        <>
          {error && (
            <p className="alert" role="alert">
              {error}
            </p>
          )}
          {notice && <p role="status">{notice}</p>}
          {!runtime ? (
            !error && <LoadingSkeleton layout="agent" label="실행 현황 불러오는 중" />
          ) : (
            <>
              <dl className="agent-operation-facts">
                <div>
                  <dt>실제 상태</dt>
                  <dd>{states[runtime.state] || runtime.state}</dd>
                </div>

                <div>
                  <dt>실행 개수</dt>
                  <dd>
                    목표 {runtime.replicas}개 · 준비 {runtime.ready_replicas}개 · 마무리 중{' '}
                    {runtime.draining_replicas}개
                  </dd>
                </div>
                <div>
                  <dt>동시 처리</dt>
                  <dd>인스턴스당 {runtime.concurrency_per_instance}개</dd>
                </div>
                <div>
                  <dt>실행 의존성</dt>
                  <dd>{runtime.dependencies.join(' · ') || '별도 실행환경 필요'}</dd>
                </div>
              </dl>
              {runtime.unavailable_reason && <p role="status">{runtime.unavailable_reason}</p>}
              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  void save();
                }}
              >
                <label className="agent-enable">
                  <input
                    type="checkbox"
                    aria-label="에이전트 활성화"
                    checked={enabled}
                    disabled={busy || !runtime.manageable}
                    onChange={(event) => {
                      setEnabled(event.target.checked);
                      setNotice('');
                    }}
                  />
                  에이전트 활성화
                </label>
                <label className="form-row">
                  <span>목표 실행 개수</span>
                  <input
                    type="number"
                    aria-label="목표 실행 개수"
                    min={1}
                    max={runtime.max_replicas}
                    step={1}
                    value={replicas}
                    disabled={busy || !runtime.manageable || !enabled}
                    onChange={(event) => {
                      setReplicas(Number(event.target.value));
                      setNotice('');
                    }}
                  />
                </label>
                <p className="form-note">
                  서버 전체에 적용됩니다. 비활성화·축소 시 새 작업 배정을 막고 진행 중 작업이 끝난
                  뒤 중지합니다. CPU 전체 상한은 16개입니다.
                </p>
                {revision !== runtime.revision && (
                  <p role="alert">
                    다른 관리자가 설정을 변경했습니다. 편집 내용을 확인한 뒤 최신 설정을 불러오세요.
                  </p>
                )}
                <div className="page-actions">
                  <Button
                    type="submit"
                    disabled={
                      busy ||
                      !runtime.manageable ||
                      !dirty ||
                      revision !== runtime.revision ||
                      !Number.isInteger(replicas) ||
                      replicas < 1 ||
                      replicas > runtime.max_replicas
                    }
                  >
                    설정 적용
                  </Button>
                  <Button
                    type="button"
                    variant="quiet"
                    disabled={busy}
                    onClick={() => {
                      accept(runtime);
                      setError('');
                      setNotice('최신 설정을 불러왔습니다.');
                    }}
                  >
                    최신 설정 불러오기
                  </Button>
                </div>
              </form>
              <div
                className="agent-instance-scroll"
                role="region"
                aria-label="실행 인스턴스"
                tabIndex={0}
              >
                <table>
                  <thead>
                    <tr>
                      <th>인스턴스</th>
                      <th>상태</th>
                      <th>처리 중</th>
                      <th>완료</th>
                      <th>프로세스</th>
                    </tr>
                  </thead>
                  <tbody>
                    {runtime.instances.map((instance) => (
                      <tr key={instance.id}>
                        <td>
                          <code title={instance.id}>{instance.id.slice(0, 8)}</code>
                        </td>
                        <td>{states[instance.state] || instance.state}</td>
                        <td>{instance.in_flight}</td>
                        <td>{instance.completed}</td>
                        <td>{instance.pid ?? '—'}</td>
                      </tr>
                    ))}
                    {!runtime.instances.length && (
                      <tr>
                        <td colSpan={5}>실행한 인스턴스가 없습니다.</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </>
      )}
    </section>
  );
};
