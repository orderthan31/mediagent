import { useEffect, useState } from 'react';
import { request } from './api';
import { PageTitle } from './PageTitle';
import { Button } from './hangyeol/primitives/button';
import {
  forgetPendingStart,
  isStartRequestPending,
  isKnownStartRequestState,
  parseStartReceipt,
  readPendingStart,
  rememberPendingStart,
  startRequestLabel,
  type StartReceipt,
} from './start-receipts.mjs';

export const StartRequestProgress = ({
  receiptId,
  requestId,
}: {
  receiptId?: string;
  requestId?: string;
}) => {
  const [receipt, setReceipt] = useState<StartReceipt | null>(null);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let failures = 0;
    const intakeError = (event: Event) => {
      const detail = (event as CustomEvent<{ request_id: string; message: string }>).detail;
      if (detail.request_id === requestId) {
        setError(detail.message);
      }
    };
    window.addEventListener('start-intake-error', intakeError);
    const load = async () => {
      try {
        const value = parseStartReceipt(
          await request<unknown>(
            receiptId
              ? '/work-entry/start-requests/' + receiptId
              : '/work-entry/start-requests/by-request?request_id=' +
                  encodeURIComponent(requestId || ''),
            { signal: controller.signal },
          ),
        );
        if (receiptId && value.id !== receiptId) {
          throw new Error('시작 요청이 일치하지 않습니다.');
        }
        if (controller.signal.aborted) {
          return;
        }
        setReceipt(value);
        setError('');
        failures = 0;
        const pending = readPendingStart();
        if (requestId && pending?.request_id === requestId) {
          rememberPendingStart('create', { request_id: requestId, receipt_id: value.id });
        }
        if (value.job_id && isKnownStartRequestState(value.state) && value.state !== 'uncertain') {
          if (pending?.request_id === requestId || pending?.receipt_id === value.id) {
            forgetPendingStart('create');
          }
          location.hash = '/jobs/' + value.job_id;
          return;
        }
        if (['blocked', 'failed', 'expired', 'cancelled'].includes(value.state)) {
          if (pending?.request_id === requestId || pending?.receipt_id === value.id) {
            forgetPendingStart('create');
          }
        }
        if (isStartRequestPending(value.state)) {
          timer = setTimeout(load, 2000);
        }
      } catch (reason) {
        if (controller.signal.aborted) {
          return;
        }
        // A missing receipt while intake is in flight is not an acknowledged failure.
        setError(reason instanceof Error ? reason.message : '접수 확인 불가');
        failures++;
        if (failures < 6) {
          timer = setTimeout(load, 2000);
        }
      }
    };
    setReceipt(null);
    setError('');
    void load();
    return () => {
      controller.abort();
      clearTimeout(timer);
      window.removeEventListener('start-intake-error', intakeError);
    };
  }, [receiptId, requestId, attempt]);
  return (
    <main className="video-main start-request-progress">
      <PageTitle>시작 요청</PageTitle>
      <p role="status" data-request-state={receipt?.state || 'uncertain'}>
        {receipt ? startRequestLabel(receipt.state) : error ? '접수 확인 불가' : '접수 확인 중…'}
      </p>
      {receipt?.code && <p role="alert">{receipt.code}</p>}
      {error && <p role="alert">접수 확인 불가 · {error}</p>}
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        <Button variant="quiet" onClick={() => setAttempt((value) => value + 1)}>
          새로고침
        </Button>
        <a href="#/jobs">작업 목록</a>
      </div>
    </main>
  );
};

export const StartRequestsSummary = () => {
  const [rows, setRows] = useState<StartReceipt[]>([]);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      try {
        const result = await request<{ requests: unknown[] }>('/work-entry/start-requests', {
          signal: controller.signal,
        });
        if (!Array.isArray(result.requests)) {
          throw new Error('시작 요청 목록 확인 불가');
        }
        const next = result.requests.map(parseStartReceipt).filter((row) => !row.job_id);
        if (!controller.signal.aborted) {
          setRows(next);
          setError('');
        }
      } catch (reason) {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : '시작 요청 목록 확인 불가');
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
  }, []);
  return (
    <section aria-label="시작 요청">
      {error && <p role="alert">{error}</p>}
      {!!rows.length && <h2>시작 요청</h2>}
      {rows.map((row) => (
        <p key={row.id}>
          <a href={'#/start-requests/' + row.id}>{startRequestLabel(row.state)}</a>
          {row.code && <> · {row.code}</>}
        </p>
      ))}
    </section>
  );
};
