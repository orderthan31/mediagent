import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, request } from './api';
import { Button } from './hangyeol/primitives/button';
import { LoadingSkeleton } from './LoadingSkeleton';
import './control-recovery.css';

type Choice = 'hold' | 'confirm_observed' | 'quarantine_failed';
type Evidence = {
  request: { request_id: string; phase: string; actor_id: string };
  group_revision: number;
  observation_revision: number;
  review_revision: number;
  contract_sha256: string;
  targets: { worker_id: string; target_id: string | null; image_id: string | null }[];
  actions: {
    id: string;
    worker_id: string;
    action: string;
    phase: string;
    issue_count: number;
    before_boot_id: string | null;
    issued_at: string | null;
  }[];
  observed: {
    id: string;
    running: boolean;
    state: string;
    boot_id: string | null;
    exit_code: number | null;
  }[];
  ack_evidence: { action_id: string; valid: boolean; receipt_sha256: string | null }[];
};
type Plan = { id: string; context: Evidence; allowed: Choice[] };
type Decision = {
  id: string;
  request_id: string;
  actor_name: string;
  choice: Choice;
  reason: string;
  created_at: string;
  result: null | {
    outcome: string;
    created_at: string;
    evidence: { current_context: Evidence | null };
  };
};
type Status = {
  request_id: string | null;
  group_revision: number;
  review_revision: number;
  observation_revision: number;
  quarantined: boolean;
  pending_decision: string | null;
  history: Decision[];
};
type Intent = { plan_id: string; decision_id: string; choice: Choice; reason: string };
const choices: Record<Choice, string> = {
  hold: '보류',
  confirm_observed: '관측 결과 확정',
  quarantine_failed: '실패 확인 · 격리',
};
const outcomes: Record<string, string> = {
  held: '보류 · 원래 봉쇄 유지',
  observed_completed: '관리자 관측 확정',
  failed_quarantined: '실패 확인 · 격리 유지',
  rejected_stale: '근거 변경 · 새 확인 필요',
};
const Facts = ({ value }: { value: Evidence }) => (
  <div className="recovery-facts">
    <p>
      원 요청 <code>{value.request.request_id}</code>
    </p>
    {value.targets.map((target) => {
      const action = value.actions.find((item) => item.worker_id === target.worker_id);
      const observed = value.observed.find((item) => item.id === target.worker_id);
      const ack = value.ack_evidence.find((item) => item.action_id === action?.id);
      return (
        <dl key={target.worker_id}>
          <div>
            <dt>실행 ID</dt>
            <dd>
              <code>{target.worker_id}</code>
            </dd>
          </div>
          <div>
            <dt>확인 결과</dt>
            <dd>
              {observed
                ? observed.running
                  ? '실행 중'
                  : `중지 · 종료 코드 ${observed.exit_code ?? '확인 불가'}`
                : '확인 불가'}
            </dd>
          </div>
          <div>
            <dt>판단 근거</dt>
            <dd>{ack?.valid ? 'ACK 파일 근거 확인됨' : 'ACK 파일 근거 확인 불가'}</dd>
          </div>
          <div>
            <dt>원래 발행 기록</dt>
            <dd>
              {action
                ? `${action.action} / ${action.phase} / 예약 ${action.issue_count}회`
                : '이 대상의 발행 기록 없음'}
            </dd>
          </div>
          <div>
            <dt>원래 boot</dt>
            <dd>
              <code>{action?.before_boot_id ?? '확인 불가'}</code>
            </dd>
          </div>
          <div>
            <dt>확인된 boot</dt>
            <dd>
              <code>{observed?.boot_id ?? '확인 불가'}</code>
            </dd>
          </div>
          <div>
            <dt>고정 대상</dt>
            <dd>
              <code>{target.target_id ?? '확인 불가'}</code>
            </dd>
          </div>
          <div>
            <dt>고정 image</dt>
            <dd>
              <code>{target.image_id ?? '확인 불가'}</code>
            </dd>
          </div>
        </dl>
      );
    })}
    <details>
      <summary>요청·계약·발행 상세</summary>
      <p>
        계약 <code>{value.contract_sha256}</code>
      </p>
      {value.actions.map((action) => (
        <p key={action.id}>
          action <code>{action.id}</code> · 발행 예약 시각 {action.issued_at ?? '없음'}
        </p>
      ))}
    </details>
  </div>
);
export const ControlRecoveryPanel = ({
  identity,
  unavailable,
}: {
  identity: string;
  unavailable: boolean;
}) => {
  const [status, setStatus] = useState<Status | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [unsupported, setUnsupported] = useState(false);
  const [readError, setReadError] = useState('');
  const [actionError, setActionError] = useState('');
  const [notice, setNotice] = useState('');
  const [stale, setStale] = useState(false);
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [choice, setChoice] = useState<Choice>('hold');
  const [reason, setReason] = useState('');
  const planRef = useRef<Plan | null>(null);
  const readSequence = useRef(0);
  const unsupportedRef = useRef(false);
  const intentRef = useRef<Intent | null>(null);
  const sendingRef = useRef(false);
  const endpoint = `/admin/agents/${encodeURIComponent(identity)}/recovery`;
  const load = useCallback(
    async (signal?: AbortSignal) => {
      const sequence = ++readSequence.current;
      try {
        const value = await request<Status>(endpoint, { signal });
        if (signal?.aborted || sequence !== readSequence.current) {
          return;
        }
        setStatus(value);
        setReadError('');
        const own =
          intentRef.current &&
          value.history.find((item) => item.id === intentRef.current?.decision_id);
        if (own) {
          setUncertain(false);
          setNotice(
            own.result
              ? (outcomes[own.result.outcome] ?? '판단 결과 확인 필요')
              : '접수됨 · 호스트 재검증 대기',
          );
          if (own.result) {
            intentRef.current = null;
            planRef.current = null;
            setPlan(null);
            setStale(own.result.outcome === 'rejected_stale');
          }
        }
        const expected = planRef.current?.context;
        if (
          expected &&
          !intentRef.current &&
          (value.request_id !== expected.request.request_id ||
            value.group_revision !== expected.group_revision ||
            value.review_revision !== expected.review_revision ||
            value.observation_revision !== expected.observation_revision)
        ) {
          setStale(true);
        }
      } catch (error) {
        if (signal?.aborted || sequence !== readSequence.current) {
          return;
        }
        if (error instanceof ApiError && error.status === 404) {
          unsupportedRef.current = true;
          setUnsupported(true);
        } else {
          setReadError('최신 판단 상태를 확인하지 못했습니다. 이전 값으로 제출할 수 없습니다.');
        }
      }
    },
    [endpoint],
  );
  const preview = async () => {
    if (sendingRef.current || intentRef.current || unavailable || status?.pending_decision) {
      return;
    }
    sendingRef.current = true;
    setBusy(true);
    setActionError('');
    try {
      const value = await request<Plan>(`${endpoint}/preview`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}',
      });
      if (
        !value.allowed.includes('hold') ||
        value.allowed.some((item) => !Object.hasOwn(choices, item))
      ) {
        throw new Error('invalid_plan');
      }
      planRef.current = value;
      setPlan(value);
      setChoice('hold');
      setStale(false);
      setNotice('최신 근거를 확인했습니다. 가능한 판단과 사유를 확인하세요.');
      await load();
    } catch {
      setStale(true);
      setActionError('근거를 확인할 수 없거나 다른 판단을 처리 중입니다. 상태를 새로 확인하세요.');
    } finally {
      sendingRef.current = false;
      setBusy(false);
    }
  };
  const submit = async () => {
    if (
      !plan ||
      stale ||
      busy ||
      unavailable ||
      readError ||
      !reason.trim() ||
      intentRef.current ||
      status?.pending_decision ||
      !plan.allowed.includes(choice) ||
      sendingRef.current
    ) {
      return;
    }
    const intent = {
      plan_id: plan.id,
      decision_id: crypto.randomUUID().replaceAll('-', ''),
      choice,
      reason,
    };
    intentRef.current = intent;
    sendingRef.current = true;
    setBusy(true);
    setActionError('');
    setNotice('판단 요청 전송 중');
    try {
      await request(`${endpoint}/decisions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(intent),
      });
      if (intentRef.current?.decision_id === intent.decision_id) {
        setNotice('접수됨 · 호스트 재검증 대기');
      }
      await load();
    } catch (error) {
      // A polling GET may already have observed the authoritative result while
      // this POST response was delayed/lost. Never downgrade that known result.
      if (intentRef.current?.decision_id !== intent.decision_id) {
        return;
      }
      if (error instanceof ApiError && [403, 409, 422].includes(error.status)) {
        intentRef.current = null;
        setStale(true);
        setActionError(
          error.status === 409
            ? '근거나 다른 판단이 변경됐습니다. 최신 근거를 다시 확인하세요.'
            : '권한과 판단 입력을 확인한 뒤 최신 근거를 다시 확인하세요.',
        );
        setNotice('');
      } else {
        setUncertain(true);
        setNotice('접수 결과 확인 불가 · 새 판단을 보내지 않고 이력을 조회합니다.');
      }
    } finally {
      sendingRef.current = false;
      setBusy(false);
    }
  };
  const disabled =
    busy || unavailable || !!readError || stale || uncertain || !!status?.pending_decision;
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      await load(controller.signal);
      if (!controller.signal.aborted && !unsupportedRef.current) {
        timer = setTimeout(poll, 1500);
      }
    };
    void poll();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [load]);
  useEffect(() => {
    if (!plan) {
      return;
    }
    const timer = setTimeout(() => setStale(true), 110000);
    return () => clearTimeout(timer);
  }, [plan]);
  if (unsupported) {
    return null;
  }
  return (
    <section className="control-recovery" role="region" aria-label="에이전트 복구 확인">
      <h3>복구 확인</h3>
      {readError && <p role="alert">{readError}</p>}
      {!status && !readError ? (
        <LoadingSkeleton layout="form" label="복구 상태 불러오는 중" />
      ) : (
        status && (
          <>
            <p>
              원 요청: <code>{status.request_id ?? '현재 미확정 요청 없음'}</code>
            </p>
            {status.quarantined && (
              <p role="status">실패 확인 · 격리 유지. 재기동하거나 작업을 재실행하지 않습니다.</p>
            )}
            <div className="page-actions">
              <Button
                type="button"
                variant="secondary"
                onClick={() => void preview()}
                disabled={
                  busy ||
                  unavailable ||
                  uncertain ||
                  !!status.pending_decision ||
                  !status.request_id
                }
              >
                최신 근거 확인
              </Button>
              <Button type="button" variant="quiet" onClick={() => void load()}>
                판단 상태 새로고침
              </Button>
            </div>
            {stale && (
              <p role="alert">이전 근거는 사용할 수 없습니다. 최신 근거를 다시 확인하세요.</p>
            )}
            {plan && (
              <>
                <p>
                  {stale || unavailable || readError
                    ? '이전 확인값 · 현재 판단에 사용 불가'
                    : '이번 판단의 확인 근거'}
                </p>
                <Facts value={plan.context} />
                <form
                  onSubmit={(event) => {
                    event.preventDefault();
                    void submit();
                  }}
                >
                  <label>
                    가능한 판단
                    <select
                      aria-label="가능한 판단"
                      value={choice}
                      disabled={disabled}
                      onChange={(event) => setChoice(event.target.value as Choice)}
                    >
                      {plan.allowed.map((item) => (
                        <option key={item} value={item}>
                          {choices[item]}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    판단 사유
                    <textarea
                      aria-label="복구 판단 사유"
                      value={reason}
                      maxLength={1000}
                      disabled={busy || uncertain || !!status.pending_decision}
                      placeholder="확인한 근거와 판단 사유 (비밀정보 제외)"
                      onChange={(event) => setReason(event.target.value)}
                    />
                  </label>
                  <Button type="submit" disabled={disabled || !reason.trim()}>
                    판단 접수
                  </Button>
                </form>
              </>
            )}
            {status.pending_decision && <p role="status">접수됨 · 호스트 재검증 대기</p>}
            <h4>최근 판단 이력</h4>
            {!status.history.length ? (
              <p>아직 판단 이력이 없습니다.</p>
            ) : (
              <ol>
                {status.history.map((item) => (
                  <li key={item.id} data-decision-id={item.id}>
                    <strong>
                      {item.result
                        ? (outcomes[item.result.outcome] ?? '결과 확인 필요')
                        : '접수됨 · 호스트 재검증 대기'}
                    </strong>
                    <p>
                      {choices[item.choice]} · {item.actor_name} ·{' '}
                      {new Date(item.created_at).toLocaleString()}
                    </p>
                    <p>{item.reason}</p>
                    <details>
                      <summary>판단 대상·결과 상세</summary>
                      <p>
                        판단 <code>{item.id}</code>
                      </p>
                      <p>
                        원 요청 <code>{item.request_id}</code>
                      </p>
                      {item.result?.evidence.current_context && (
                        <Facts value={item.result.evidence.current_context} />
                      )}
                    </details>
                  </li>
                ))}
              </ol>
            )}
          </>
        )
      )}
      {notice && <p role="status">{notice}</p>}
      {actionError && <p role="alert">{actionError}</p>}
    </section>
  );
};
