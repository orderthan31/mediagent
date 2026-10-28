import { useCallback, useEffect, useRef, useState } from 'react';
import { request } from './api';
import { jsonPost } from './video-api';
import { Button } from './hangyeol/primitives/button';

type RoleTask = {
  task_id: string;
  role?: string;
  state: string;
  reason: string | null;
  reserved_calls: number;
  reported_model_calls: number | null;
  max_calls: number;
  call_issues: { chunk_index: number; status: string; error_code: string | null }[];
  cancel_delivery: string | null;
  delivery_revision: number | null;
  delivery_attempts: number | null;
  delivery_attempt_limit: number;
  recovery_choices: string[];
  pending_recovery?: { request_id: string; revision: number | null } | null;
  recovery_block_reason?: string | null;
};
type Observation = {
  enrolled: boolean;
  tasks: RoleTask[];
  available_roles?: string[];
  enrolled_roles?: string[];
};
const roleNames: Record<string, string> = {
  transcription: '전사',
  translation: '번역',
  vocalization: '보컬',
};
const states: Record<string, string> = {
  receiving: '결과 전달 확인 중',
  ready: '전달 준비',
  sending: '전달 확인 중',
  sent: '명령 전달 확인 · 결과 도착 대기',
  unknown: '전달 결과 확인 필요',
  held: '보류 · 기록 보존',
  adopting: '결과 확인 중',
  accepted: '결과 채택 완료',
  cancelled: '취소 확인',
};
const reasons: Record<string, string> = {
  legacy_pending_recovery_identity_unavailable:
    '이전 복구 요청의 원래 revision을 확인할 수 없습니다. 기록을 보존하며 새 요청 ID로 우회하지 않습니다. 원 요청 신원 확인이 필요합니다.',
  result_artifact_integrity:
    '결과 파일 무결성 검증이 실패했습니다. 파일이나 모델을 자동으로 다시 실행하지 않습니다.',
  result_delivery_interrupted:
    '결과 전달 처리가 중단되어 반영 여부를 확인해야 합니다. 같은 결과만 명시적으로 확인합니다.',
  result_delivery_budget_exhausted:
    '결과 전달 재시도 예산이 소진됐습니다. 기존 기록과 모델 호출 예산을 초기화하지 않습니다.',
  result_dispatch_reconcile_held:
    '기존 채택은 확인했지만 다음 배정이 보류됐습니다. 모델을 다시 호출하지 않습니다.',
  model_reply_unknown: '모델 응답이 불명확해 중단했습니다. 자동으로 다시 호출하지 않습니다.',
  result_transport_unavailable:
    '완료 결과를 가져오지 못했습니다. 모델을 다시 실행하지 않고 결과 전달만 확인할 수 있습니다.',
  result_adoption_commit_unknown:
    '결과 반영 여부를 확인하지 못했습니다. 같은 결과의 반영 상태만 다시 확인합니다.',
  result_adoption_or_dispatch_held:
    '결과 반영 또는 다음 배정이 보류됐습니다. 기존 결과와 호출 기록을 보존합니다.',
  command_publication_unknown: '명령 전달 여부가 불명확합니다. 자동 재발행하지 않습니다.',
  call_budget_below_required_chunks:
    '고정된 호출 상한으로 입력 전체를 처리할 수 없어 호출 전에 보류했습니다.',
  invalid_timed_transcription: '전사 응답의 시각 형식이 맞지 않아 결과를 보존하고 보류했습니다.',
  role_checkpoint_held: '전사 체크포인트가 보류 상태입니다. 자동 재실행하지 않습니다.',
};

export const ModelRolePanel = ({
  jobId,
  revision,
  canManage,
  onChanged,
}: {
  observationOnly?: boolean;
  jobId: string;
  revision: number;
  status: string;
  canManage: boolean;
  hasRuns: boolean;
  onChanged: () => Promise<unknown>;
}) => {
  const base = '/renewal/jobs/' + jobId + '/model-role';
  const [observation, setObservation] = useState<Observation | null>(null);
  const [readError, setReadError] = useState('');
  const [actionError, setActionError] = useState('');
  const [current, setCurrent] = useState(false);
  const [busy, setBusy] = useState(false);
  const sequence = useRef(0);
  const recovery = useRef(new Map<string, string>());
  const load = useCallback(
    async (signal?: AbortSignal) => {
      const turn = ++sequence.current;
      try {
        const next = await request<Observation>(base, { signal });
        if (turn === sequence.current && !signal?.aborted) {
          setObservation(next);
          setReadError('');
          setCurrent(true);
        }
      } catch (error) {
        if (turn === sequence.current && !signal?.aborted) {
          setCurrent(false);
          setReadError(error instanceof Error ? error.message : '전사 상태를 확인하지 못했습니다.');
        }
      }
    },
    [base],
  );
  const act = async (operation: () => Promise<unknown>) => {
    if (busy || !current) {
      return;
    }
    setBusy(true);
    setActionError('');
    try {
      await operation();
      await load();
      await onChanged();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : '요청을 확인하지 못했습니다.');
      await load();
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    const timer = setInterval(() => void load(controller.signal), 4000);
    return () => {
      controller.abort();
      clearInterval(timer);
      sequence.current++;
    };
  }, [load, revision]);
  return (
    <section className="shared-job-custody" aria-label="처리 상태">
      <h3>처리 상태</h3>
      {readError && (
        <p role="alert">
          {readError}
          {observation ? ' · 아래는 이전 조회 기록입니다.' : ''}
        </p>
      )}
      {actionError && <p role="alert">{actionError}</p>}
      {!observation && !readError && <p role="status">전사 상태 확인 중</p>}
      {observation && (
        <>
          {observation.tasks.map((task) => (
            <div key={task.task_id} data-role-task={task.task_id}>
              <h4>{roleNames[task.role || 'transcription'] || task.role}</h4>
              <strong role="status">{states[task.state] || task.state}</strong>
              {task.reason && <p>{reasons[task.reason] || task.reason}</p>}
              {task.cancel_delivery && (
                <p>
                  취소:{' '}
                  {task.cancel_delivery === 'acknowledged' ? '응답 확인' : '전달·응답 확인 중'}
                </p>
              )}
              {task.recovery_block_reason && (
                <p role="alert">
                  {reasons[task.recovery_block_reason] || task.recovery_block_reason}
                </p>
              )}
              {canManage &&
                task.recovery_choices.some((choice) =>
                  ['retry_result_delivery', 'settle_recovery_response'].includes(choice),
                ) && (
                  <>
                    <p>
                      {task.recovery_choices.includes('settle_recovery_response')
                        ? '결과 상태를 다시 확인합니다.'
                        : '결과를 다시 확인합니다. 추가 모델 호출은 하지 않습니다.'}
                    </p>
                    <Button
                      disabled={busy || !current || task.delivery_revision === null}
                      onClick={() =>
                        void act(() => {
                          const operation = task.recovery_choices.includes(
                            'settle_recovery_response',
                          )
                            ? 'settle_recovery_response'
                            : 'retry_result_delivery';
                          if (
                            operation === 'settle_recovery_response' &&
                            (!task.pending_recovery || task.pending_recovery.revision === null)
                          ) {
                            throw new Error(
                              '기존 복구 요청의 원 신원 확인이 필요합니다. 새 요청으로 대체하지 않습니다.',
                            );
                          }
                          const key = task.task_id + ':' + task.delivery_revision;
                          if (!task.pending_recovery && !recovery.current.has(key)) {
                            recovery.current.set(key, crypto.randomUUID());
                          }
                          return jsonPost(base + '/result-delivery', {
                            task_id: task.task_id,
                            operation: operation,
                            revision: task.pending_recovery?.revision ?? task.delivery_revision,
                            request_id:
                              task.pending_recovery?.request_id ?? recovery.current.get(key),
                          });
                        })
                      }
                    >
                      {task.recovery_choices.includes('settle_recovery_response')
                        ? '기존 복구 응답 정산'
                        : '결과 전달만 다시 확인'}
                    </Button>
                  </>
                )}
            </div>
          ))}
        </>
      )}
    </section>
  );
};
