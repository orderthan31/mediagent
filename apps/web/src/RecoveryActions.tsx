import { useRef, useState } from 'react';
import { request } from './api';
import { jsonPost } from './video-api';
import { Button } from './hangyeol/primitives/button';

type RecoveryView = {
  id: string;
  revision: number;
  control_revision?: number;
  status: string;
  active_generation?: string;
  execution_generation?: string;
  recovery_unknown_nodes?: string[];
  recovery_parent?: { ticket_id: string; attempt_id: string };
  recovery_risk?: { acknowledged: boolean; unknown_nodes: string[] };
  reuse_origins?: Record<string, { ticket_id: string; receipt_sha256: string }>;
};
export const RecoveryActions = ({
  ticket,
  onOpen,
}: {
  ticket: RecoveryView;
  onOpen: (id: string) => Promise<void>;
}) => {
  const [busy, setBusy] = useState(false);
  const [risk, setRisk] = useState(false);
  const [error, setError] = useState('');
  const recoveryRequest = useRef(crypto.randomUUID());
  const cancelRequest = useRef(crypto.randomUUID());
  const base = '/settings/recovery-tickets/' + ticket.id;
  const cancel = async () => {
    setBusy(true);
    setError('');
    try {
      await jsonPost(base + '/cancel', {
        request_id: cancelRequest.current,
        control_revision: ticket.control_revision ?? 0,
      });
      await onOpen(ticket.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : '취소 접수 충돌. 서버값을 다시 확인하세요.');
    } finally {
      setBusy(false);
    }
  };
  const recover = async () => {
    setBusy(true);
    setError('');
    try {
      const child = await jsonPost<{ id: string }>(base + '/recover', {
        request_id: recoveryRequest.current,
        revision: ticket.revision,
        risk_confirmed: risk,
      });
      await onOpen(child.id);
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : '복구 출처/receipt/실행 상태를 확인하세요. 자동 재실행하지 않습니다.',
      );
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="recovery-actions ticket-panel">
      <h3>복구</h3>
      <p>
        <strong>
          {ticket.status === 'held'
            ? '생성 보류 · 새 계획 확인 필요'
            : ticket.status === 'cancelled'
              ? '취소됨 · 결과 보존'
              : ticket.status === 'cancelling'
                ? '취소 접수 · 진행 호출 정리 중'
                : ticket.status === 'failed'
                  ? '실패 · 완료/부분 결과 보존'
                  : ticket.status === 'completed'
                    ? '완료 · 검증된 결과 보존'
                    : '계획 확인/실행 상태는 아래 티켓에 표시'}
        </strong>
      </p>
      {ticket.recovery_parent && (
        <p>
          원 티켓 {ticket.recovery_parent.ticket_id.slice(0, 12)}… · attempt{' '}
          {ticket.recovery_parent.attempt_id.slice(0, 8)}…
        </p>
      )}
      <p>활성 실행 세대: {ticket.active_generation?.slice(0, 12) || '없음 · 자동 실행하지 않음'}</p>
      {Object.entries(ticket.reuse_origins || {}).map(([node, origin]) => (
        <p key={node}>
          재사용 {node} · 출처 {origin.ticket_id.slice(0, 8)}… · receipt{' '}
          {origin.receipt_sha256.slice(0, 12)}
        </p>
      ))}
      <details>
        <summary>전체 출처·실행 세대</summary>
        <pre>
          {JSON.stringify(
            {
              parent: ticket.recovery_parent,
              generation: ticket.execution_generation,
              reuse: ticket.reuse_origins,
            },
            null,
            2,
          )}
        </pre>
      </details>
      {ticket.recovery_risk?.unknown_nodes.length ? (
        <p>
          결과 불명 출처: {ticket.recovery_risk.unknown_nodes.join(', ')} · 위험 별도확인{' '}
          {ticket.recovery_risk.acknowledged ? '기록됨' : '필요'}
        </p>
      ) : null}
      {error && (
        <p role="alert" className="alert">
          {error}
        </p>
      )}
      {!['completed', 'failed', 'cancelled'].includes(ticket.status) && (
        <>
          <p>
            취소 접수 뒤 새 dispatch를 막습니다. 이미 시작한 외부 호출의 즉시 중단·환불을 보장하지
            않으며 결과를 보존합니다.
          </p>
          <Button
            variant="secondary"
            disabled={busy || ticket.status === 'cancelling'}
            onClick={() => void cancel()}
          >
            취소 요청 접수
          </Button>
        </>
      )}
      {['failed', 'cancelled', 'running'].includes(ticket.status) && (
        <>
          {!!ticket.recovery_unknown_nodes?.length && (
            <label className="serving-check">
              <input
                type="checkbox"
                aria-label="결과 불명 중복호출 위험 별도확인"
                checked={risk}
                disabled={busy}
                onChange={(e) => {
                  setRisk(e.target.checked);
                  recoveryRequest.current = crypto.randomUUID();
                }}
              />
              결과 불명 호출을 다시 요청하면 중복 호출·과금이 생길 수 있음을 별도 확인
            </label>
          )}
          <Button disabled={busy} onClick={() => void recover()}>
            검증하고 새 복구 티켓 만들기
          </Button>
        </>
      )}
    </section>
  );
};

export const TicketSnapshotRestore = ({
  definitionId,
  ticketId,
  namespace,
}: {
  definitionId: string;
  ticketId: string;
  namespace: string;
}) => {
  const [busy, setBusy] = useState(false),
    [status, setStatus] = useState(''),
    [error, setError] = useState('');
  const restore = async () => {
    setBusy(true);
    setError('');
    try {
      const head = await request<{ revision: number }>(
        '/settings/workflow-definitions/' + definitionId,
      );
      const next = await jsonPost<{ revision: number }>(
        '/settings/workflow-definitions/' + definitionId + '/restore',
        {
          revision: head.revision,
          source: { kind: 'ticket_snapshot', namespace, ticket_id: ticketId },
        },
      );
      setStatus('버전 ' + next.revision + '으로 복원했습니다.');
    } catch (e) {
      setError(e instanceof Error ? e.message : '복원 실패. 기존 정의·티켓을 유지합니다.');
    } finally {
      setBusy(false);
    }
  };
  return (
    <details className="ticket-panel">
      <summary>워크플로우 복원</summary>
      <Button variant="secondary" disabled={busy} onClick={() => void restore()}>
        새 버전으로 복원
      </Button>
      {status && <p role="status">{status}</p>}
      {error && <p role="alert">{error}</p>}
    </details>
  );
};
