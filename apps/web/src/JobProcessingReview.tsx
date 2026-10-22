import { useEffect, useRef, useState } from 'react';
import { mediaUrl, request } from './api';
import { jsonPost } from './video-api';
import { Button } from './hangyeol/primitives/button';
import {
  processingLabel,
  processingReasons,
  type ProcessingProjection,
} from './processing-review-state';
import './processing-review.css';

type Receipt = {
  message_sha256: string;
  verified: boolean;
  outputs: Record<string, { sha256: string; bytes: number }>;
  error_code: string | null;
};
type Evidence = {
  attempt: { id: string; generation: number; request_sha256: string; request: unknown };
  outbox: { id: string; published_at: string | null } | null;
  dispatch: {
    phase: string;
    worker_id: string | null;
    boot_id: string | null;
    release_decision_id?: string | null;
  } | null;
  worker_events: unknown[];
  inbox: unknown[];
  quarantined_results: Receipt[];
};
type Decision = {
  acknowledge_duplicate_risk: boolean;
  authority_snapshot: { id: string; role: string; active: boolean };
  plan_context: unknown;
  reviewed_revision: number;
  id: string;
  actor_id: string;
  choice: string;
  reason: string;
  child_id: string | null;
  created_at: string;
};
type Review = {
  case: Omit<ProcessingProjection, 'case_id'> & { id: string; revision: number; cause: string };
  original: {
    job_id: string;
    ticket_number: number;
    raw_status: string;
    generation: number;
    claim_id: string | null;
    attempt_id: string;
  };
  evidence: Evidence;
  can_create_child: boolean;
  hold_reasons: string[];
  history: Decision[];
  child: { id: string; owner_id: string; ticket_number: number; status: string } | null;
  plan_id?: string;
};

export const JobProcessingReview = ({
  jobId,
  onChanged,
}: {
  jobId: string;
  onChanged?: () => void;
}) => {
  const [state, setState] = useState<Review | null>(null),
    [plan, setPlan] = useState<Review | null>(null);
  const [reason, setReason] = useState(''),
    [risk, setRisk] = useState(false),
    [busy, setBusy] = useState(false),
    [pending, setPending] = useState<string | null>(null);
  const [user, setUser] = useState<{ id: string; role: string } | null>(null),
    [error, setError] = useState(''),
    [notice, setNotice] = useState('');
  const sequence = useRef(0),
    intent = useRef<{ key: string; id: string } | null>(null),
    pendingRef = useRef<string | null>(null);
  const base = '/admin/jobs/' + jobId + '/processing-review';
  const load = async () => {
    const seq = ++sequence.current;
    try {
      const auth = await request<{ user: { id: string; role: string } }>('/auth/session');
      if (seq !== sequence.current) {
        return null;
      }
      setUser(auth.user);
      if (auth.user.role !== 'admin') {
        setState(null);
        return null;
      }
      const next = await request<Review>(base);
      if (seq !== sequence.current) {
        return null;
      }
      setState(next);
      setPlan((old) =>
        old?.case.revision === next.case.revision &&
        old.can_create_child === next.can_create_child &&
        JSON.stringify(old.hold_reasons) === JSON.stringify(next.hold_reasons)
          ? old
          : null,
      );
      if (pendingRef.current && next.history.some((d) => d.id === pendingRef.current)) {
        pendingRef.current = null;
        setPending(null);
        setNotice('판단 저장을 원장 조회로 확인했습니다.');
      }
      return next;
    } catch (error) {
      if (seq === sequence.current) {
        throw error;
      }
      return null;
    }
  };

  const refresh = async () => {
    setError('');
    try {
      await load();
    } catch (e) {
      setError(String(e));
    }
  };
  const preview = async () => {
    setBusy(true);
    setError('');
    setNotice('');
    const seq = ++sequence.current;
    try {
      const next = await jsonPost<Review>(base + '/preview', {});
      if (seq === sequence.current) {
        setState(next);
        setPlan(next);
        setRisk(false);
        intent.current = null;
      }
    } catch (e) {
      if (seq === sequence.current) {
        setError(String(e));
        setPlan(null);
      }
    } finally {
      if (seq === sequence.current) {
        setBusy(false);
      }
    }
  };
  const decide = async (choice: 'hold' | 'create_child') => {
    if (!plan?.plan_id || busy || pendingRef.current || !reason.trim()) {
      return;
    }
    const data = {
      plan_id: plan.plan_id,
      choice,
      reason,
      acknowledge_duplicate_risk: choice === 'create_child' && risk,
    };
    const key = JSON.stringify(data);
    if (intent.current?.key !== key) {
      intent.current = { key, id: crypto.randomUUID().replaceAll('-', '') };
    }
    const id = intent.current.id;
    pendingRef.current = id;
    setPending(id);
    setBusy(true);
    setError('');
    setNotice('');
    ++sequence.current;
    try {
      await jsonPost(base + '/decisions', { ...data, decision_id: id });
      await load();
      setPlan(null);
      onChanged?.();
    } catch (e) {
      try {
        const fresh = await load();
        if (!fresh?.history.some((d) => d.id === id)) {
          setError(String(e));
          setPlan(null);
          pendingRef.current = null;
          setPending(null);
        }
      } catch {
        setError(
          '판단 응답을 확인하지 못했습니다. 자동 재요청하지 않습니다. 판단 원장을 새로 조회하세요.',
        );
      }
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => {
    void load().catch((e) => setError(String(e)));
    return () => {
      sequence.current++;
    };
  }, [base]);
  return (
    <section className="processing-review ticket-panel" aria-label="작업 처리 확인">
      <h2>작업 처리 확인</h2>
      <p>
        원 작업의 상태·실행·전송 기록은 보존합니다. 아래 판단은 별도 원장에 남고, 새 작업 생성만으로
        실행되지는 않습니다.
      </p>
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      {user?.role !== 'admin' && user && <p>관리자 확인이 필요합니다.</p>}
      {user?.role === 'admin' && (
        <>
          <div className="processing-actions">
            <Button variant="secondary" disabled={busy || !!pending} onClick={() => void preview()}>
              현재 근거 확인
            </Button>
            <Button variant="quiet" disabled={busy} onClick={() => void refresh()}>
              판단 원장 새로고침
            </Button>
          </div>
          {pending && (
            <p role="status">판단 접수 결과를 확인 중입니다. 자동으로 새 판단을 보내지 않습니다.</p>
          )}
          {state && (
            <>
              <strong role="status">
                {processingLabel({ ...state.case, case_id: state.case.id })}
              </strong>
              <dl>
                <div>
                  <dt>원 작업</dt>
                  <dd>
                    #{state.original.ticket_number} · <code>{state.original.job_id}</code>
                  </dd>
                </div>
                <div>
                  <dt>기록상 상태</dt>
                  <dd>{state.original.raw_status} · 처리 중이라고 확정한 표시가 아닙니다.</dd>
                </div>
                <div>
                  <dt>원 실행 회차</dt>
                  <dd>
                    <code>{state.original.attempt_id}</code> · 세대 {state.original.generation}
                  </dd>
                </div>
                <div>
                  <dt>원 요청 해시</dt>
                  <dd>
                    <code>{state.evidence.attempt.request_sha256}</code>
                  </dd>
                </div>
                <div>
                  <dt>전송 근거</dt>
                  <dd>
                    {state.evidence.dispatch?.phase || '이전 전송 기록'} ·{' '}
                    {state.evidence.outbox?.published_at || '발행 확인 시각 없음'}
                  </dd>
                </div>
                <div>
                  <dt>수신·관측 근거</dt>
                  <dd>
                    결과 수신 {state.evidence.inbox.length} · 연결 관측{' '}
                    {state.evidence.worker_events.length} · 격리 결과{' '}
                    {state.evidence.quarantined_results.length}
                  </dd>
                </div>
                <div>
                  <dt>확인 기록</dt>
                  <dd>
                    <code>{state.case.id}</code> · 개정 {state.case.revision}
                  </dd>
                </div>
              </dl>
              <details>
                <summary>원 요청·전송·수신 근거 상세</summary>
                <pre>{JSON.stringify(state.evidence, null, 2)}</pre>
              </details>
              {state.hold_reasons.map((r) => (
                <p key={r} role="status">
                  {processingReasons[r] || r}
                </p>
              ))}
              {state.evidence.quarantined_results
                .filter((r) => r.verified)
                .map((r) => (
                  <div key={r.message_sha256}>
                    {Object.keys(r.outputs).map((port) => (
                      <a
                        key={port}
                        href={mediaUrl(
                          base + '/quarantine/' + r.message_sha256 + '/' + encodeURIComponent(port),
                        )}
                      >
                        격리 자료 {port} 받기
                      </a>
                    ))}
                  </div>
                ))}
              {!state.child && (
                <>
                  <label>
                    판단 사유
                    <textarea
                      aria-label="판단 사유"
                      maxLength={1000}
                      value={reason}
                      disabled={busy || !!pending}
                      onChange={(e) => setReason(e.target.value)}
                    />
                  </label>
                  <label className="processing-risk">
                    <input
                      type="checkbox"
                      checked={risk}
                      disabled={busy || !!pending}
                      onChange={(e) => setRisk(e.target.checked)}
                    />
                    새 작업의 중복 처리 위험을 확인했고 별도 계획·승인을 진행하겠습니다.
                  </label>
                  <div className="processing-actions">
                    <Button
                      disabled={busy || !!pending || !plan || !reason.trim()}
                      onClick={() => void decide('hold')}
                    >
                      보류 판단 저장
                    </Button>
                    <Button
                      disabled={
                        busy || !!pending || !plan?.can_create_child || !risk || !reason.trim()
                      }
                      onClick={() => void decide('create_child')}
                    >
                      새 복구 작업 준비
                    </Button>
                  </div>
                </>
              )}
              {state.child && (
                <p role="status">
                  새 복구 작업 #{state.child.ticket_number} · <code>{state.child.id}</code> ·{' '}
                  {state.child.status}.{' '}
                  {state.child.owner_id === user.id ? (
                    <a href={'#/jobs/' + state.child.id}>새 작업 열기</a>
                  ) : (
                    '원 작업 소유자의 작업 목록에서 별도 승인이 필요합니다.'
                  )}
                </p>
              )}
              <h3>판단 이력</h3>
              {!state.history.length ? (
                <p>아직 판단 이력이 없습니다.</p>
              ) : (
                <ol>
                  {state.history.map((d) => (
                    <li key={d.id}>
                      <strong>{d.choice === 'hold' ? '보류' : '새 작업 연결'}</strong> · {d.reason}
                      <p>
                        판단 ID <code>{d.id}</code> · 관리자 <code>{d.actor_id}</code> ·{' '}
                        {d.created_at}
                      </p>
                      <details>
                        <summary>판단 시점의 고정 근거</summary>
                        <pre>
                          {JSON.stringify(
                            {
                              reviewed_revision: d.reviewed_revision,
                              authority_snapshot: d.authority_snapshot,
                              acknowledge_duplicate_risk: d.acknowledge_duplicate_risk,
                              context: d.plan_context,
                            },
                            null,
                            2,
                          )}
                        </pre>
                      </details>
                    </li>
                  ))}
                </ol>
              )}
            </>
          )}
        </>
      )}
    </section>
  );
};

export const ProcessingReviewInbox = () => {
  const sequence = useRef(0);
  const [isAdmin, setIsAdmin] = useState<boolean | null>(null);
  const [rows, setRows] = useState<Array<
      ProcessingProjection & { job_id: string; ticket_number: number }
    > | null>(null),
    [error, setError] = useState(''),
    [selected, setSelected] = useState('');
  const refresh = async () => {
    const seq = ++sequence.current;
    try {
      const session = await request<{ user: { role: string } }>('/auth/session');
      if (seq !== sequence.current) {
        return;
      }
      setIsAdmin(session.user.role === 'admin');
      if (session.user.role !== 'admin') {
        setRows(null);
        setSelected('');
        setError('');
        return;
      }
      const data = await request<{ cases: NonNullable<typeof rows> }>('/admin/processing-reviews');
      if (seq !== sequence.current) {
        return;
      }
      setRows(data.cases);
      setError('');
    } catch (e) {
      if (seq === sequence.current) {
        setError(String(e));
      }
    }
  };
  useEffect(() => {
    void refresh();
    return () => {
      sequence.current++;
    };
  }, []);
  if (isAdmin === false) {
    return null;
  }
  return (
    <section className="processing-review" aria-label="관리자 처리 확인 작업">
      <h2>처리 확인이 필요한 작업</h2>
      <Button variant="quiet" onClick={() => void refresh()}>
        확인 작업 새로고침
      </Button>
      {error && <p role="alert">{error}</p>}
      {error && rows && <p>이전 목록입니다. 최신 조회는 확인하지 못했습니다.</p>}
      {rows && !rows.length && !error && <p>확인할 작업이 없습니다.</p>}
      <ul>
        {rows?.map((r) => (
          <li key={r.case_id}>
            <Button variant="quiet" onClick={() => setSelected(r.job_id)}>
              작업 #{r.ticket_number} · {processingLabel(r)}
            </Button>
          </li>
        ))}
      </ul>
      {selected && (
        <JobProcessingReview jobId={selected} key={selected} onChanged={() => void refresh()} />
      )}
    </section>
  );
};
