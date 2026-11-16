import { continuePreparedRecovery } from './job-resume.mjs';
import { useEffect, useRef, useState } from 'react';
import { request } from './api';
import './unit-recovery.css';

type Row = { id?: string | number; start: number; end: number; text: string; speaker?: string };
type Decision = {
  unit_index: number;
  action: 'retry' | 'skip' | 'manual';
  candidate_index?: number;
  value?: Row[];
};
type Unit = {
  index: number;
  status: string;
  error_code?: string;
  source_ranges: { source_start: number; source_end: number }[];
  source_rows: Row[];
  manual_schema?: { duration_seconds?: number };
  allowed_actions: string[];
  attempts: { status: string; origin?: string; candidate_index?: number; error_code?: string }[];
  provenance: unknown;
};
type View = {
  version: number;
  supported: boolean;
  blocked_reason: string | null;
  job_id: string;
  run_id: string;
  role: string;
  job_revision: number;
  recovery_revision: number;
  context_sha256: string;
  access: { can_manage: boolean };
  counts: Record<string, number>;
  units: Unit[];
  decisions?: Decision[];
  recovery: null | {
    id: string;
    status: string;
    revision: number;
    request_id: string;
    additional_call_limit: number;
    executed_calls: number;
    can_continue: boolean;
  };
};
type Preview = Pick<View, 'job_revision' | 'recovery_revision' | 'context_sha256'> & {
  preview_sha256: string;
  ready: boolean;
  decisions: Decision[];
  additional_call_limit: number;
  models: unknown[];
  warnings: string[];
  blocked_reasons: string[];
  retained_units: unknown[];
  execution_units: unknown[];
};
type Draft = { action: string; rows: Row[] };
const hasPendingEvidence = (v: View) =>
  v.counts.unknown > 0 ||
  v.counts.active > 0 ||
  v.units.some(
    (u) =>
      ['unknown', 'active', 'sending'].includes(u.status) ||
      u.attempts.some((a) => ['unknown', 'active', 'sending'].includes(a.status)),
  );
const mayApprove = (p: Preview | null) =>
  !!p &&
  p.decisions.length > 0 &&
  p.blocked_reasons.every((reason) => reason.endsWith(':unresolved')) &&
  (p.ready || p.blocked_reasons.length > 0);
const labels: Record<string, string> = {
  succeeded: '성공 · 보존',
  failed: '실패',
  unattempted: '미시도',
  unknown: '결과 미확인 (실패 아님)',
  active: '처리 중',
  manual: '수동 입력',
  skipped: '제외',
};
const stamp = (v: View) =>
  JSON.stringify([
    v.job_revision,
    v.recovery_revision,
    v.context_sha256,
    v.recovery,
    v.counts,
    v.access,
    v.blocked_reason,
  ]);
const requestId = () =>
  Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) =>
    b.toString(16).padStart(2, '0'),
  ).join('');

const UnitEvidence = ({ unit }: { unit: Unit }) => (
  <details>
    <summary>원본 시간 매핑 · 출처 · 시도 기록</summary>
    <p>원본 source_ranges</p>
    <pre>{JSON.stringify(unit.source_ranges, null, 2)}</pre>
    <p>출처 (provenance)</p>
    <pre>{JSON.stringify(unit.provenance, null, 2)}</pre>
    <pre>{JSON.stringify(unit.attempts, null, 2)}</pre>
  </details>
);

// Keyed inner scope prevents stale drafts, approvals and responses crossing runs.
export const UnitRecoveryPanel = (props: {
  jobId: string;
  runId: string;
  canManage: boolean;
  onChanged?: () => void | Promise<void>;
  focusOnOpen?: boolean;
}) => {
  return <RecoveryScope key={`${props.jobId}:${props.runId}`} {...props} />;
};
const RecoveryScope = ({
  jobId,
  runId,
  canManage,
  onChanged,
  focusOnOpen = false,
}: {
  jobId: string;
  runId: string;
  canManage: boolean;
  onChanged?: () => void | Promise<void>;
  focusOnOpen?: boolean;
}) => {
  const base = `/renewal/jobs/${encodeURIComponent(jobId)}/runs/${encodeURIComponent(runId)}/unit-recovery`;
  const [view, setView] = useState<View | null>(null);
  const latest = useRef<View | null>(null);
  const panelRoot = useRef<HTMLElement>(null);
  const initialFocusDone = useRef(false);
  const [drafts, setDrafts] = useState<Record<number, Draft>>({});
  const [preview, setPreview] = useState<Preview | null>(null);
  const [approved, setApproved] = useState(false);
  const [dirty, setDirty] = useState(false);
  const dirtyRef = useRef(false);
  const editRevision = useRef(0);
  const renderedRevision = editRevision.current;
  const nextActionButton = useRef<HTMLButtonElement>(null);
  const previewRevision = useRef<number | null>(null);
  const confirmApproval = (revision: number | undefined) => {
    if (revision === editRevision.current) {
      dirtyRef.current = false;
      setDirty(false);
    }
  };
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [uncertain, setUncertain] = useState(false);
  const unresolved = useRef<{
    id: string;
    operation: 'save' | 'execute' | 'continue';
    editRevision?: number;
  } | null>(null);
  const [stale, setStale] = useState(true);
  const alive = useRef(false);
  const fence = useRef(false);
  const reading = useRef(false);
  const controller = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const manageable = useRef(canManage);
  manageable.current = canManage;
  const notifyChanged = async () => {
    try {
      await onChanged?.();
    } catch {
      if (alive.current) {
        setError('복구 상태는 확정됐지만 작업 상세 새로고침에 실패했습니다.');
      }
    }
  };
  const accept = (v: View) => {
    if (v.version !== 1 || v.job_id !== jobId || v.run_id !== runId) {
      throw Error('상태 식별자가 일치하지 않습니다.');
    }
    if (latest.current && stamp(latest.current) !== stamp(v)) {
      previewRevision.current = null;
      setPreview(null);
      setApproved(false);
    }
    latest.current = v;
    setView(v);
    // Restore accepted manual/omit choices after reload, but never reselect a
    // now-retained model success or replace an unsaved local edit on polling.
    setDrafts((old) =>
      Object.fromEntries(
        v.units.flatMap((u) => {
          if (!['failed', 'unattempted'].includes(u.status) || !u.allowed_actions.length) {
            return [];
          }
          const saved = v.decisions?.find((d) => d.unit_index === u.index);
          const prior = old[u.index];
          const draft =
            prior ??
            (saved && {
              action: saved.action,
              rows:
                saved.value?.map((r) => ({ ...r })) ??
                (v.role === 'translation'
                  ? u.source_rows.map((r) => ({ ...r }))
                  : [{ start: 0, end: u.manual_schema?.duration_seconds ?? 0, text: '' }]),
            });
          return draft && (!draft.action || u.allowed_actions.includes(draft.action))
            ? [[u.index, draft]]
            : [];
        }),
      ),
    );
    setStale(false);
  };
  const refresh = async () => {
    if (!alive.current || reading.current || fence.current) {
      return;
    }
    reading.current = true;
    const turn = generation.current;
    try {
      const v = await request<View>(base, { signal: controller.current?.signal });
      if (alive.current && turn === generation.current) {
        accept(v);
        const pending = unresolved.current;
        if (
          pending &&
          v.recovery?.request_id === pending.id &&
          !hasPendingEvidence(v) &&
          (!v.blocked_reason ||
            (pending.operation === 'continue' && v.recovery.status === 'applied')) &&
          ['approved', 'completed', 'applied'].includes(v.recovery.status) &&
          (pending.operation !== 'continue' || v.recovery.status === 'applied')
        ) {
          if (pending.operation === 'save') {
            confirmApproval(pending.editRevision);
          }
          unresolved.current = null;
          setUncertain(false);
          setError(
            v.recovery.status === 'applied'
              ? 'GET으로 복구 결과 채택을 확인했습니다. 후속 단계 상태는 작업 상세에서 확인해 주세요.'
              : 'GET으로 저장된 요청 상태를 확인했습니다. 다음 동작은 직접 선택해 주세요.',
          );
          if (v.recovery.status === 'applied') {
            void notifyChanged();
          }
        } else if (pending) {
          setError(
            '결과 미확인: 확정 증거가 없거나 요청이 진행 중입니다. 재전송 없이 GET으로만 확인합니다.',
          );
        }
      }
    } catch {
      if (alive.current && turn === generation.current) {
        setStale(true);
        setError('복구 상태를 확인하지 못했습니다. 새로고침해 주세요.');
      }
    } finally {
      reading.current = false;
    }
  };
  const pendingEvidence =
    !!view &&
    (view.counts.unknown > 0 ||
      view.counts.active > 0 ||
      view.units.some(
        (u) =>
          ['unknown', 'active', 'sending'].includes(u.status) ||
          u.attempts.some((a) => ['unknown', 'active', 'sending'].includes(a.status)),
      ));
  const blocked =
    !view ||
    !view.supported ||
    !['transcription', 'translation'].includes(view.role) ||
    !canManage ||
    !view.access.can_manage ||
    stale ||
    !!view.blocked_reason ||
    pendingEvidence ||
    view.recovery?.status === 'applied';
  const locked = blocked || busy || uncertain;
  const resumable =
    view?.recovery?.status === 'approved' &&
    Number.isSafeInteger(view.recovery.additional_call_limit) &&
    Number.isSafeInteger(view.recovery.executed_calls) &&
    view.recovery.executed_calls >= 0 &&
    view.recovery.executed_calls < view.recovery.additional_call_limit;
  const update = (u: Unit, patch: Partial<Draft>) => {
    dirtyRef.current = true;
    editRevision.current++;
    previewRevision.current = null;
    setDirty(true);
    setDrafts((old) => ({
      ...old,
      [u.index]: {
        ...(old[u.index] ?? {
          action: '',
          rows:
            view?.role === 'translation'
              ? u.source_rows.map((r) => ({ ...r }))
              : [{ start: 0, end: u.manual_schema?.duration_seconds ?? 0, text: '' }],
        }),
        ...patch,
      },
    }));
    setPreview(null);
    setApproved(false);
    setError('');
    if (patch.action === 'skip' || patch.action === 'retry') {
      requestAnimationFrame(() => {
        if (alive.current) {
          nextActionButton.current?.scrollIntoView({ block: 'nearest' });
        }
      });
    }
  };
  const pendingUnits =
    view?.units.filter((u) => ['failed', 'unattempted'].includes(u.status)) || [];
  const quickReady =
    !view?.recovery?.can_continue &&
    view?.recovery?.status !== 'applied' &&
    pendingUnits.length > 0 &&
    pendingUnits.every((u) => ['skip', 'manual'].includes(drafts[u.index]?.action || ''));
  const post = <T,>(suffix: string, body: unknown) =>
    request<T>(`${base}/${suffix}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: controller.current?.signal,
    });
  const mutate = async (kind: 'preview' | 'approve' | 'execute' | 'continue' | 'quick') => {
    if (fence.current || blocked || !manageable.current || uncertain) {
      return;
    }
    // A captured pre-edit handler must not preview the previous render's drafts.
    if ((kind === 'preview' || kind === 'quick') && renderedRevision !== editRevision.current) {
      return;
    }
    if (
      kind === 'approve' &&
      (!mayApprove(preview) ||
        (preview!.additional_call_limit > 0 && !approved) ||
        previewRevision.current !== editRevision.current)
    ) {
      return;
    }
    if ((kind === 'execute' || kind === 'continue') && dirtyRef.current) {
      return;
    }
    if (kind === 'execute' && !resumable) {
      return;
    }
    if (kind === 'continue' && !view?.recovery?.can_continue) {
      return;
    }
    fence.current = true;
    generation.current++;
    setBusy(true);
    setError('');
    let submitted = false;
    const submittedRevision = editRevision.current;
    let prepared: Preview | null = null;
    try {
      if (kind === 'preview' || kind === 'quick') {
        const decisions: Decision[] = [];
        for (const u of view!.units) {
          const draft = drafts[u.index];
          if (!draft?.action) {
            continue;
          }
          if (
            !['failed', 'unattempted'].includes(u.status) ||
            !u.allowed_actions.includes(draft.action)
          ) {
            throw Error('허용되지 않은 구간 결정입니다.');
          }
          const d: Decision = { unit_index: u.index, action: draft.action as Decision['action'] };
          if (d.action === 'retry') {
            d.candidate_index = 0;
          }
          if (d.action === 'manual') {
            d.value = draft.rows;
            if (
              !Array.isArray(d.value) ||
              !d.value.length ||
              d.value.length > 10000 ||
              d.value.some(
                (r) =>
                  !r ||
                  typeof r.text !== 'string' ||
                  !r.text.trim() ||
                  !Number.isFinite(r.start) ||
                  !Number.isFinite(r.end) ||
                  r.start < 0 ||
                  r.end <= r.start ||
                  (view!.role === 'transcription' &&
                    u.manual_schema?.duration_seconds != null &&
                    r.end > u.manual_schema.duration_seconds),
              )
            ) {
              throw Error('수동 입력의 텍스트·시간 범위를 확인해 주세요.');
            }
          }
          decisions.push(d);
        }
        const result = await post<Preview>('preview', {
          job_revision: view!.job_revision,
          recovery_revision: view!.recovery_revision,
          context_sha256: view!.context_sha256,
          decisions,
        });
        if (!alive.current) {
          return;
        }
        if (
          result.context_sha256 !== view!.context_sha256 ||
          result.job_revision !== view!.job_revision ||
          result.recovery_revision !== view!.recovery_revision ||
          !Number.isSafeInteger(result.additional_call_limit) ||
          result.additional_call_limit < 0
        ) {
          throw Error('미리보기 상태가 변경되었습니다.');
        }
        if (submittedRevision !== editRevision.current) {
          return;
        }
        previewRevision.current = submittedRevision;
        if (kind === 'preview') {
          setPreview(result);
          setApproved(false);
          return;
        }
        if (
          !result.ready ||
          result.additional_call_limit !== 0 ||
          result.decisions.some((d) => d.action === 'retry')
        ) {
          throw Error('남은 구간의 처리 방식을 선택해 주세요.');
        }
        prepared = result;
      }
      if (kind === 'approve' || kind === 'quick') {
        const p = prepared || preview!;
        const id = requestId();
        submitted = true;
        unresolved.current = { id, operation: 'save', editRevision: submittedRevision };
        const saved = await post<View>('decisions', {
          job_revision: p.job_revision,
          recovery_revision: p.recovery_revision,
          context_sha256: p.context_sha256,
          decisions: p.decisions,
          request_id: id,
          preview_sha256: p.preview_sha256,
          approve_calls: kind === 'quick' ? false : approved,
        });
        if (!alive.current) {
          return;
        }
        accept(saved);
        setPreview(null);
        setApproved(false);
        if (
          saved.recovery?.request_id !== id ||
          !saved.recovery.id ||
          saved.recovery.status !== 'approved' ||
          !saved.access.can_manage ||
          !manageable.current ||
          saved.blocked_reason ||
          hasPendingEvidence(saved)
        ) {
          throw Error('저장 결과 확인 필요');
        }
        confirmApproval(submittedRevision);
        if (dirtyRef.current) {
          unresolved.current = null;
          return;
        }
        unresolved.current = { id, operation: 'execute' };
        const executed = await post<View>('execute', { request_id: id });
        if (!alive.current) {
          return;
        }
        accept(executed);
        unresolved.current = null;
        if (kind === 'quick') {
          if (!executed.recovery?.can_continue || dirtyRef.current) {
            throw Error('복구 결과를 확인해 주세요.');
          }
          unresolved.current = { id, operation: 'continue' };
          const result = await continuePreparedRecovery(
            executed,
            request,
            () =>
              alive.current &&
              !dirtyRef.current &&
              manageable.current &&
              latest.current?.recovery?.id === executed.recovery?.id &&
              latest.current?.context_sha256 === executed.context_sha256,
          );
          if (!alive.current) {
            return;
          }
          if (result.state !== 'sent') {
            throw Error('실행 요청 결과를 확인해 주세요.');
          }
          unresolved.current = null;
          setStale(true);
          await notifyChanged();
        }
        if (kind !== 'quick' && executed.recovery?.can_continue && !dirtyRef.current) {
          requestAnimationFrame(() => {
            if (!alive.current) {
              return;
            }
            const next = panelRoot.current?.querySelector<HTMLButtonElement>(
              '[data-recovery-continue]',
            );
            next?.scrollIntoView({ block: 'nearest' });
            next?.focus({ preventScroll: true });
          });
        }
      } else if (kind === 'execute') {
        submitted = true;
        const id = view!.recovery!.request_id;
        unresolved.current = { id, operation: 'execute' };
        const executed = await post<View>('execute', { request_id: id });
        if (!alive.current) {
          return;
        }
        accept(executed);
        unresolved.current = null;
      } else {
        const result = await continuePreparedRecovery(
          view!,
          request,
          () =>
            alive.current &&
            !dirtyRef.current &&
            manageable.current &&
            latest.current?.context_sha256 === view!.context_sha256 &&
            latest.current?.recovery_revision === view!.recovery_revision &&
            latest.current?.recovery?.id === view!.recovery!.id,
        );
        if (!alive.current) {
          return;
        }
        if (result.state !== 'sent') {
          if (result.state === 'uncertain' || result.state === 'blocked') {
            submitted = true;
            unresolved.current = { id: view!.recovery!.request_id, operation: 'continue' };
          }
          throw Error(
            result.state === 'stale'
              ? '작업 상태가 바뀌었습니다. 상태를 새로고침해 주세요.'
              : '실행 결과를 확인해야 합니다. 자동으로 다시 보내지 않습니다.',
          );
        }
        unresolved.current = null;
        setStale(true);
        await notifyChanged();
      }
    } catch (e) {
      if (alive.current) {
        setPreview(null);
        setApproved(false);
        if (submitted) {
          setUncertain(true);
          setStale(true);
          setError('결과 미확인: 요청을 재전송하지 않습니다. GET 상태 새로고침으로만 확인합니다.');
        } else {
          setError(e instanceof Error ? e.message : '복구 요청을 확인해 주세요.');
        }
      }
    } finally {
      fence.current = false;
      if (alive.current) {
        setBusy(false);
        if (submitted) {
          void refresh();
        }
      }
    }
  };
  useEffect(() => {
    if (!focusOnOpen || !view || initialFocusDone.current) {
      return;
    }
    const target = panelRoot.current?.querySelector<HTMLElement>(
      '[data-unit] .unit-recovery-actions button',
    );
    if (target) {
      initialFocusDone.current = true;
      requestAnimationFrame(() =>
        requestAnimationFrame(() => {
          if (alive.current) {
            target.scrollIntoView({ block: 'center' });
          }
        }),
      );
    }
  }, [focusOnOpen, view]);
  useEffect(() => {
    alive.current = true;
    controller.current = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let polls = 0;
    const poll = async () => {
      await refresh();
      if (alive.current && ++polls < 6) {
        timer = setTimeout(() => void poll(), 4000);
      }
    };
    void poll();
    return () => {
      alive.current = false;
      generation.current++;
      controller.current?.abort();
      clearTimeout(timer);
    };
    // The keyed scope is immutable; polling never initiates a POST.
  }, []);
  if (view && (!view.supported || !['transcription', 'translation'].includes(view.role))) {
    return null;
  }
  return (
    <section className="unit-recovery" aria-label="구간 복구" ref={panelRoot}>
      <h3>구간 복구</h3>

      {error && <p role="alert">{error}</p>}
      {!view && <p>복구 상태 확인 중</p>}
      <button type="button" disabled={busy} onClick={() => void refresh()}>
        상태 새로고침
      </button>
      {view && (
        <>
          {(!canManage || !view.access.can_manage) && (
            <p>공용 읽기 전용 · 작업 소유자만 변경할 수 있습니다.</p>
          )}
          {view.blocked_reason && <p>변경 차단: {view.blocked_reason}</p>}
          {!view.recovery && <p role="status">복구 요청 전 · 처리할 구간과 방법을 선택하세요.</p>}
          {dirty && (
            <p className="unit-recovery-next" role="status">
              방법을 선택했지만 아직 적용 전입니다. 아래 ‘선택 내용 확인’을 눌러 주세요.
            </p>
          )}
          {pendingEvidence && (
            <p>미확인 또는 진행 중인 요청이 있습니다. 실패로 간주하거나 재시도하지 않습니다.</p>
          )}
          <p>
            {Object.entries(view.counts)
              .filter(([key, value]) => value > 0 || key === 'succeeded')
              .map(([k, v]) => `${labels[k] || k}: ${v}`)
              .join(' · ')}
          </p>
          {view.units
            .filter((u) => u.status !== 'succeeded')
            .map((u) => (
              <article key={u.index} data-unit={u.index}>
                <h4>
                  구간 {u.index + 1} · {labels[u.status] || u.status}
                </h4>
                <p>
                  원본 시간:{' '}
                  {u.source_ranges.map((r) => `${r.source_start}–${r.source_end}초`).join(', ') ||
                    '매핑 없음'}
                </p>
                {u.error_code && <p>오류: {u.error_code}</p>}
                <UnitEvidence unit={u} />
                {['failed', 'unattempted'].includes(u.status) && (
                  <fieldset disabled={locked}>
                    <div
                      className="unit-recovery-actions"
                      aria-label={`구간 ${u.index + 1} 동작 선택`}
                    >
                      {(
                        [
                          ['retry', '재시도'],
                          ['skip', '무시'],
                          ['manual', '직접 입력'],
                        ] as const
                      )
                        .filter(([action]) => u.allowed_actions.includes(action))
                        .map(([action, label]) => (
                          <button
                            type="button"
                            key={action}
                            aria-label={`구간 ${u.index + 1} ${label}`}
                            aria-pressed={drafts[u.index]?.action === action}
                            onClick={() => update(u, { action })}
                          >
                            {label}
                          </button>
                        ))}
                    </div>
                    <p>
                      {drafts[u.index]?.action === 'skip'
                        ? '이 구간을 제외하도록 선택했습니다. 아직 적용 전입니다.'
                        : '방법을 고른 뒤 아래에서 선택 내용을 확인해 주세요.'}
                    </p>
                    <label>
                      구간 {u.index + 1} 처리
                      <select
                        aria-label={`구간 ${u.index + 1} 처리`}
                        value={drafts[u.index]?.action || ''}
                        onChange={(e) => update(u, { action: e.target.value })}
                      >
                        <option value="">명시적으로 선택</option>
                        {u.allowed_actions.includes('retry') && (
                          <option value="retry">재시도 · 원래 고정 후보 1</option>
                        )}
                        {u.allowed_actions.includes('skip') && (
                          <option value="skip">제외 · 출력에서 생략</option>
                        )}
                        {u.allowed_actions.includes('manual') && (
                          <option value="manual">수동 입력</option>
                        )}
                      </select>
                    </label>
                    {drafts[u.index]?.action === 'skip' && (
                      <p>
                        이 구간은 ASR·MT 모두 출력에서 생략됩니다. 빈 번역이나 원문으로 대체하지
                        않습니다.
                      </p>
                    )}
                    {drafts[u.index]?.action === 'manual' &&
                      (view.role === 'translation' ? (
                        <>
                          <p>ID·순서·시간·화자는 고정되어 있습니다. 번역 텍스트만 수정합니다.</p>
                          {drafts[u.index].rows.map((r, i) => (
                            <label key={i}>
                              행 {r.id} · {r.start}–{r.end} · {r.speaker || ''}
                              <textarea
                                aria-label={`구간 ${u.index + 1} 행 ${r.id} 번역`}
                                value={r.text}
                                onChange={(e) =>
                                  update(u, {
                                    rows: drafts[u.index].rows.map((row, j) =>
                                      j === i ? { ...row, text: e.target.value } : row,
                                    ),
                                  })
                                }
                              />
                            </label>
                          ))}
                        </>
                      ) : (
                        <>
                          <p>
                            청크 로컬 시계 (0초부터, 최대{' '}
                            {u.manual_schema?.duration_seconds ?? '서버 검증'}초). 원본 시간 매핑은
                            위에 표시됩니다.
                          </p>
                          {drafts[u.index].rows.map((r, i) => (
                            <div className="unit-recovery-row" key={i}>
                              <p>행 {i + 1}</p>
                              {(['start', 'end'] as const).map((field) => (
                                <label key={field}>
                                  {field === 'start' ? '시작' : '종료'} (청크 기준 초)
                                  <input
                                    type="number"
                                    min="0"
                                    max={u.manual_schema?.duration_seconds}
                                    step="any"
                                    aria-label={`구간 ${u.index + 1} 행 ${i + 1} ${field === 'start' ? '시작' : '종료'}`}
                                    value={Number.isFinite(r[field]) ? r[field] : ''}
                                    onChange={(e) =>
                                      update(u, {
                                        rows: drafts[u.index].rows.map((row, j) =>
                                          i === j
                                            ? { ...row, [field]: e.target.valueAsNumber }
                                            : row,
                                        ),
                                      })
                                    }
                                  />
                                </label>
                              ))}
                              <label>
                                자막 텍스트
                                <textarea
                                  aria-label={`구간 ${u.index + 1} 행 ${i + 1} 텍스트`}
                                  value={r.text}
                                  onChange={(e) =>
                                    update(u, {
                                      rows: drafts[u.index].rows.map((row, j) =>
                                        i === j ? { ...row, text: e.target.value } : row,
                                      ),
                                    })
                                  }
                                />
                              </label>
                              <button
                                type="button"
                                aria-label={`구간 ${u.index + 1} 행 ${i + 1} 삭제`}
                                onClick={() =>
                                  update(u, {
                                    rows: drafts[u.index].rows.filter((_, j) => i !== j),
                                  })
                                }
                              >
                                행 삭제
                              </button>
                            </div>
                          ))}
                          <button
                            type="button"
                            onClick={() =>
                              update(u, {
                                rows: [
                                  ...drafts[u.index].rows,
                                  {
                                    start: 0,
                                    end: u.manual_schema?.duration_seconds ?? 0,
                                    text: '',
                                  },
                                ],
                              })
                            }
                          >
                            행 추가
                          </button>
                        </>
                      ))}
                  </fieldset>
                )}
              </article>
            ))}
          {canManage && view.access.can_manage && (
            <>
              {quickReady && (
                <div className="unit-recovery-quick">
                  <button
                    className="unit-recovery-primary"
                    type="button"
                    disabled={locked}
                    onClick={() => void mutate('quick')}
                  >
                    {pendingUnits.some((u) => drafts[u.index]?.action === 'manual')
                      ? '입력 반영하고 계속'
                      : '제외하고 계속'}
                  </button>
                </div>
              )}
              <button
                type="button"
                ref={nextActionButton}
                disabled={locked || !Object.values(drafts).some((d) => d.action)}
                onClick={() => void mutate('preview')}
              >
                선택 내용 확인
              </button>
            </>
          )}
          {canManage && view.access.can_manage && (
            <>
              {preview && (
                <div className="unit-recovery-preview">
                  <h4>선택 내용을 확인하고 적용하세요</h4>
                  <p>
                    {preview.additional_call_limit === 0
                      ? '이 단계의 추가 모델 호출 없음 · 성공 구간은 다시 처리하지 않습니다.'
                      : `추가 모델 호출 상한: ${preview.additional_call_limit}회`}
                  </p>
                  <p>
                    보존 구간 {preview.retained_units.length} · 실행 구간{' '}
                    {preview.execution_units.length}
                  </p>
                  {preview.additional_call_limit > 0 && (
                    <details>
                      <summary>재시도에 사용할 고정 모델</summary>
                      <pre>{JSON.stringify(preview.models, null, 2)}</pre>
                    </details>
                  )}
                  {preview.warnings.map((w, i) => (
                    <p key={i}>{w}</p>
                  ))}
                  {preview.blocked_reasons.map((w, i) => (
                    <p key={i}>
                      {w.endsWith(':unresolved') ? '후속 단계 전 해결 필요' : '차단'}: {w}
                    </p>
                  ))}
                  {preview.additional_call_limit > 0 && (
                    <label>
                      <input
                        type="checkbox"
                        checked={approved}
                        disabled={locked || !mayApprove(preview)}
                        onChange={(e) => setApproved(e.target.checked)}
                      />
                      표시된 모델과 상한 안에서 추가 호출을 승인합니다
                    </label>
                  )}
                  <button
                    type="button"
                    disabled={
                      locked ||
                      (preview.additional_call_limit > 0 && !approved) ||
                      !mayApprove(preview)
                    }
                    onClick={() => void mutate('approve')}
                  >
                    {preview.additional_call_limit === 0
                      ? preview.ready
                        ? '선택 확정'
                        : '선택한 구간만 저장'
                      : '추가 호출 승인 후 재시도'}
                  </button>
                </div>
              )}
              {view.recovery && (
                <div>
                  <p>
                    이 구간 복구의 추가 모델 호출: {view.recovery.executed_calls}회 / 승인 상한{' '}
                    {view.recovery.additional_call_limit}회
                  </p>
                  <p className="unit-recovery-next" role="status">
                    {view.recovery.status === 'applied'
                      ? '복구 결과 적용 완료. 워크플로우 위의 ‘이어서 실행’ 버튼에서 남은 태스크를 진행하세요.'
                      : view.recovery.can_continue
                        ? '선택을 저장하고 복구 결과를 준비했습니다. 아직 작업에 적용하거나 다음 태스크를 시작하지 않았습니다.'
                        : '아직 처리하지 않은 구간을 확인해 주세요. 후속 단계는 자동 실행하지 않습니다.'}
                  </p>
                  {resumable && (
                    <button
                      type="button"
                      disabled={locked || dirty}
                      onClick={() => void mutate('execute')}
                    >
                      승인한 구간 실행
                    </button>
                  )}
                  {view.recovery.status !== 'applied' && (
                    <button
                      type="button"
                      data-recovery-continue
                      disabled={locked || dirty || !view.recovery.can_continue}
                      onClick={() => void mutate('continue')}
                    >
                      복구 적용·이어서 실행
                    </button>
                  )}
                </div>
              )}
            </>
          )}
          {view.units.some((u) => u.status === 'succeeded') && (
            <details className="unit-recovery-preserved">
              <summary>
                성공·보존 {view.units.filter((u) => u.status === 'succeeded').length}개 구간 보기
              </summary>
              {view.units
                .filter((u) => u.status === 'succeeded')
                .map((u) => (
                  <article key={u.index} data-unit={u.index}>
                    <h4>
                      구간 {u.index + 1} · {labels[u.status]}
                    </h4>
                    <p>
                      원본 시간:{' '}
                      {u.source_ranges
                        .map((r) => `${r.source_start}–${r.source_end}초`)
                        .join(', ') || '매핑 없음'}
                    </p>
                    <UnitEvidence unit={u} />
                  </article>
                ))}
            </details>
          )}
        </>
      )}
    </section>
  );
};
