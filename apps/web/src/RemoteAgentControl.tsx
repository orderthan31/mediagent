import { useEffect, useRef, useState } from 'react';
import { ApiError, request } from './api';
import { Button } from './hangyeol/primitives/button';
import type { AgentRuntime } from './AgentOperations';

type Intent = { revision: number; enabled: boolean; replicas: number; request_id: string };
export const RemoteAgentControl = ({
  runtime,
  unavailable,
  onObserved,
}: {
  runtime: AgentRuntime;
  unavailable: boolean;
  onObserved: (value: AgentRuntime) => void;
}) => {
  const [count, setCount] = useState(runtime.replicas || 1);
  const [revision, setRevision] = useState(runtime.revision);
  const [edited, setEdited] = useState(false);
  const [sending, setSending] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [error, setError] = useState('');
  const inFlight = useRef(false);
  const intent = useRef<Intent | null>(null);
  const phase = runtime.control?.phase;
  const disabled = unavailable || !runtime.manageable || !!phase || sending;
  const accept = (value: AgentRuntime) => {
    onObserved(value);
    setRevision(value.revision);
    if (value.replicas && value.replicas > 0) {
      setCount(value.replicas);
    }
    setEdited(false);
  };
  const send = async (enabled: boolean) => {
    if (disabled || conflict || inFlight.current) {
      return;
    }
    if (enabled && (!Number.isInteger(count) || count < 1 || count > runtime.max_replicas)) {
      setError('실행 개수를 확인해 주세요.');
      return;
    }
    const body = intent.current ?? {
      revision,
      enabled,
      replicas: enabled ? count : 0,
      request_id: crypto.randomUUID().replaceAll('-', ''),
    };
    intent.current = body;
    inFlight.current = true;
    setSending(true);
    setError('');
    try {
      await request(`/admin/agents/${runtime.agent_id}/configuration`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      // The receipt is admission, not proof of a started/stopped process.
      const observed = await request<AgentRuntime>(`/admin/agents/${runtime.agent_id}`);
      accept(observed);
      intent.current = null;
      setUncertain(false);
    } catch (reason) {
      if (reason instanceof ApiError && [403, 409, 422].includes(reason.status)) {
        intent.current = null;
        setUncertain(false);
        setConflict(reason.status === 409);
        setError(
          reason.status === 409
            ? '설정이 변경됐거나 다른 요청을 처리 중입니다.'
            : reason.status === 403
              ? '관리자 권한이 필요합니다.'
              : '실행 개수를 확인해 주세요.',
        );
      } else {
        // Never mint a new request ID for an unknown outcome.
        setUncertain(true);
        setError('요청 결과 확인이 필요합니다.');
      }
    } finally {
      inFlight.current = false;
      setSending(false);
    }
  };
  const reload = async () => {
    if (inFlight.current) {
      return;
    }
    inFlight.current = true;
    setSending(true);
    try {
      const observed = await request<AgentRuntime>(`/admin/agents/${runtime.agent_id}`);
      accept(observed);
      setConflict(false);
      setError('');
      if (
        !intent.current ||
        observed.control?.request_id === intent.current.request_id ||
        observed.revision > intent.current.revision
      ) {
        intent.current = null;
        setUncertain(false);
      }
    } catch {
      setError('실행 상태 조회 실패');
    } finally {
      inFlight.current = false;
      setSending(false);
    }
  };
  useEffect(() => {
    if (!edited && !intent.current && !inFlight.current) {
      setRevision(runtime.revision);
      if (runtime.replicas && runtime.replicas > 0) {
        setCount(runtime.replicas);
      }
    }
  }, [runtime.revision, runtime.replicas, edited]);
  return (
    <section className="remote-agent-control" role="region" aria-label="에이전트 제어">
      <h2>실행 설정</h2>
      <p>확인된 실행 개수: {runtime.observed_replicas ?? '확인 불가'}</p>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (!uncertain) {
            void send(true);
          }
        }}
      >
        <label>
          실행 개수
          <input
            aria-label="실행 개수"
            type="number"
            min={1}
            max={runtime.max_replicas}
            step={1}
            value={count}
            disabled={disabled || uncertain || conflict}
            onChange={(event) => {
              setCount(Number(event.target.value));
              setEdited(true);
            }}
          />
        </label>
        <div className="page-actions">
          <Button type="submit" disabled={disabled || uncertain || conflict}>
            {runtime.enabled ? '개수 적용' : '시작'}
          </Button>
          <Button
            type="button"
            variant="secondary"
            disabled={disabled || uncertain || conflict || runtime.observed_replicas === 0}
            onClick={() => void send(false)}
          >
            중지
          </Button>
          {uncertain && (
            <Button
              type="button"
              disabled={disabled}
              onClick={() => void send(intent.current?.enabled ?? true)}
            >
              같은 요청 다시 확인
            </Button>
          )}
          <Button type="button" variant="quiet" disabled={sending} onClick={() => void reload()}>
            {conflict ? '최신 설정 불러오기' : '상태 새로고침'}
          </Button>
        </div>
      </form>
      {phase && <p role="status">{phase === 'unknown' ? '제어 결과 확인 불가' : '적용 중'}</p>}
      {error && <p role="alert">{error}</p>}
    </section>
  );
};
