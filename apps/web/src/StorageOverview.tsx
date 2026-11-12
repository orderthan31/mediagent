import { useEffect, useState } from 'react';
import { request } from './api';
import { formatStorageGB } from './capacity-format';
export { formatStorageGB } from './capacity-format';
import { Button } from './hangyeol/primitives/button';
import './storage-overview.css';

type Totals = { originals: { count: string; bytes: string }; observed_at: string };
type Disk = { label: string; total: number | null; free: number | null };
type Observation = {
  status: 'connected' | 'stale' | 'unavailable';
  observed_at?: string;
  storage: Disk[];
};
type ReadState<T> = { data: T | null; loading: boolean; error: boolean };

const record = (value: unknown): Record<string, unknown> =>
  value !== null && typeof value === 'object' ? (value as Record<string, unknown>) : {};
const timestamp = (value: unknown): value is string =>
  typeof value === 'string' && Number.isFinite(Date.parse(value));
const totals = (value: unknown): Totals => {
  const data = record(value);
  const originals = record(data.originals);
  if (
    !timestamp(data.observed_at) ||
    ![originals.count, originals.bytes].every(
      (n) => typeof n === 'string' && /^(0|[1-9][0-9]*)$/.test(n),
    )
  ) {
    throw new Error('Invalid totals');
  }
  return { originals: originals as Totals['originals'], observed_at: data.observed_at };
};
const observation = (value: unknown): Observation => {
  const data = record(value);
  if (data.status !== 'connected' && data.status !== 'stale' && data.status !== 'unavailable') {
    throw new Error('Invalid observation');
  }
  return {
    status: data.status,
    observed_at: timestamp(data.observed_at) ? data.observed_at : undefined,
    storage:
      data.status === 'connected' && Array.isArray(data.storage)
        ? data.storage.map((value, index) => {
            const disk = record(value);
            const valid =
              disk.status === 'connected' &&
              typeof disk.total === 'number' &&
              Number.isSafeInteger(disk.total) &&
              disk.total >= 0 &&
              typeof disk.free === 'number' &&
              Number.isSafeInteger(disk.free) &&
              disk.free >= 0 &&
              disk.free <= disk.total;
            return {
              // Collector names/sources may contain private host paths. Only public categories are displayed.
              label:
                disk.source === 'Host physical disk'
                  ? `호스트 디스크 ${index + 1}`
                  : disk.source === 'Connected object volume' || disk.source === 'Object volume'
                    ? '오브젝트 저장 공간'
                    : `저장 공간 ${index + 1}`,
              total: valid ? (disk.total as number) : null,
              free: valid ? (disk.free as number) : null,
            };
          })
        : [],
  };
};
const useRead = <T,>(path: string, parse: (value: unknown) => T) => {
  const [state, setState] = useState<ReadState<T>>({ data: null, loading: true, error: false });
  const [attempt, setAttempt] = useState(0);
  const reload = () => setAttempt((n) => n + 1);
  useEffect(() => {
    const controller = new AbortController();
    setState((previous) => ({ ...previous, loading: true, error: false }));
    void request<unknown>(path, { signal: controller.signal })
      .then(parse)
      .then((data) => {
        if (!controller.signal.aborted) {
          setState({ data, loading: false, error: false });
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setState((previous) => ({ ...previous, loading: false, error: true }));
        }
      });
    return () => controller.abort();
  }, [path, parse, attempt]);
  return { ...state, reload };
};
const exact = (value: string) => BigInt(value).toLocaleString('ko-KR');
const ObservedAt = ({ value, label }: { value?: string; label: string }) =>
  value ? (
    <p className="storage-observed-at">
      {label} <time dateTime={value}>{new Date(value).toLocaleString('ko-KR')}</time>
    </p>
  ) : (
    <p className="storage-observed-at">{label} 미확인</p>
  );

export const StorageOverview = () => {
  const registered = useRead('/renewal/storage-overview', totals);
  const measured = useRead('/system/resources', observation);
  const currentMeasurement = measured.data?.status === 'connected';
  return (
    <div className="storage-overview">
      <a href="#/settings">시스템 설정으로</a>
      <section aria-labelledby="storage-originals-title" aria-busy={registered.loading}>
        <div className="storage-overview-heading">
          <h2 id="storage-originals-title">등록된 원본</h2>
          <Button variant="secondary" disabled={registered.loading} onClick={registered.reload}>
            다시 확인
          </Button>
        </div>
        <p className="storage-read-status" role={registered.error ? 'alert' : 'status'}>
          {registered.loading
            ? '확인 중'
            : registered.error
              ? '조회 실패 · 현재 합계 미확인'
              : '확인됨'}
        </p>
        {registered.data && (
          <>
            {(registered.error || registered.loading) && <p>이전 확인값</p>}
            <dl className="storage-totals">
              <div>
                <dt>원본 수</dt>
                <dd>{exact(registered.data.originals.count)}개</dd>
              </div>
              <div>
                <dt>등록 논리 용량</dt>
                <dd>{formatStorageGB(registered.data.originals.bytes)}</dd>
              </div>
            </dl>
            <ObservedAt label="확인 시각" value={registered.data.observed_at} />
          </>
        )}
        <p>
          현재 원본 목록의 공유 등록 기록 합계입니다. 같은 파일의 중복 등록도 포함하며 실제 디스크
          사용량과 다릅니다.
        </p>
      </section>
      <section aria-labelledby="storage-measurement-title" aria-busy={measured.loading}>
        <div className="storage-overview-heading">
          <h2 id="storage-measurement-title">저장 공간 관측</h2>
          <Button variant="secondary" disabled={measured.loading} onClick={measured.reload}>
            다시 확인
          </Button>
        </div>
        <p className="storage-read-status" role={measured.error ? 'alert' : 'status'}>
          {measured.loading
            ? '확인 중'
            : measured.error
              ? '조회 실패 · 현재 용량 미확인'
              : measured.data?.status === 'stale'
                ? '관측이 오래됨 · 현재 용량 미확인'
                : measured.data?.status === 'unavailable'
                  ? '관측 없음 · 현재 용량 미확인'
                  : '수집된 저장 공간 관측'}
        </p>
        {measured.data && (
          <>
            {(measured.error || measured.loading) && <p>이전 관측값</p>}
            <ObservedAt label="관측 시각" value={measured.data.observed_at} />
            {currentMeasurement && measured.data.storage.length === 0 && (
              <p>수집된 저장 공간 없음 · 현재 용량 미확인</p>
            )}
            {measured.data.storage.map((disk, index) => (
              <div className="storage-measurement" key={index}>
                <h3>{disk.label}</h3>
                {disk.total !== null && disk.free !== null ? (
                  <dl>
                    <div>
                      <dt>전체</dt>
                      <dd>{formatStorageGB(disk.total)}</dd>
                    </div>
                    <div>
                      <dt>사용</dt>
                      <dd>{formatStorageGB(disk.total - disk.free)}</dd>
                    </div>
                    <div>
                      <dt>여유</dt>
                      <dd>{formatStorageGB(disk.free)}</dd>
                    </div>
                  </dl>
                ) : (
                  <p>용량 미확인</p>
                )}
              </div>
            ))}
          </>
        )}
        <p>
          수집된 호스트·오브젝트 볼륨 기준이며 원본 외의 데이터도 포함합니다. GB는 10억
          바이트입니다.
        </p>
      </section>
    </div>
  );
};
