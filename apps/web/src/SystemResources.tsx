import { useEffect, useState } from 'react';
import { request } from './api';
import { PageTitle } from './PageTitle';
import './system-settings.css';
type Node = {
  id: string;
  name: string;
  cpu_percent?: number | null;
  logical_processors?: number | null;
  memory_total?: number | null;
  memory_available?: number | null;
  gpu?: string[];
};
type Disk = {
  name: string;
  total?: number | null;
  free?: number | null;
  source: string;
  status?: string;
};
type State = {
  status: string;
  observed_at?: string;
  nodes?: Node[];
  storage?: Disk[];
};
const gb = (n: number | null | undefined) =>
  typeof n === 'number' && Number.isFinite(n) && n >= 0
    ? (n / 1024 ** 3).toFixed(1) + ' GiB'
    : '미확인';
const percent = (n: number | null | undefined) =>
  typeof n === 'number' && Number.isFinite(n) && n >= 0 && n <= 100 ? n + '%' : '미확인';
export const SystemResources = ({ embedded = false }: { embedded?: boolean }) => {
  const [data, setData] = useState<State | null>(null);
  const [error, setError] = useState('');
  const current = !error && data?.status === 'connected';
  const content = (
    <section className="system-resources" aria-labelledby="system-resources-title">
      <h2 id="system-resources-title">컴퓨터 자원</h2>
      <p role={error ? 'alert' : 'status'}>
        {error ||
          (current
            ? '수집 연결됨'
            : data?.status === 'stale'
              ? '관측이 오래됨 · 현재 상태 미확인'
              : data
                ? '관측 없음 · 현재 상태 미확인'
                : '자원 상태 확인 중')}
      </p>
      {data?.observed_at && Number.isFinite(Date.parse(data.observed_at)) && (
        <p className="system-observed-at">
          최근 수집{' '}
          <time dateTime={data.observed_at}>
            {new Date(data.observed_at).toLocaleString('ko-KR')}
          </time>
        </p>
      )}
      {current && !data?.nodes?.length && <p>수집된 컴퓨터 없음 · 현재 상태 미확인</p>}
      {current &&
        data?.nodes?.map((n) => (
          <section className="system-resource-node" key={n.id}>
            <h3>{n.name}</h3>
            <dl>
              <div>
                <dt>CPU</dt>
                <dd>
                  {typeof n.logical_processors === 'number' &&
                  Number.isInteger(n.logical_processors) &&
                  n.logical_processors > 0
                    ? `${n.logical_processors}개`
                    : '미확인'}
                </dd>
              </div>
              <div>
                <dt>CPU 사용률</dt>
                <dd>{percent(n.cpu_percent)}</dd>
              </div>
              <div>
                <dt>전체 메모리</dt>
                <dd>{gb(n.memory_total)}</dd>
              </div>
              <div>
                <dt>사용 가능 메모리</dt>
                <dd>{gb(n.memory_available)}</dd>
              </div>
              {!n.gpu?.length && (
                <div>
                  <dt>GPU</dt>
                  <dd>미확인</dd>
                </div>
              )}
              {n.gpu?.map((g, i) => {
                const [name, usage, used, total] = g.split(',').map((v) => v.trim());
                const mib = (v?: string) =>
                  v && Number.isFinite(Number(v)) && Number(v) >= 0 ? `${v} MiB` : '미확인';
                return (
                  <div key={i}>
                    <dt>GPU {i + 1}</dt>
                    <dd>
                      {name || '미확인'}
                      <br />
                      사용률 {usage ? percent(Number(usage)) : '미확인'}
                      <br />
                      메모리 {mib(used)} / {mib(total)}
                    </dd>
                  </div>
                );
              })}
            </dl>
          </section>
        ))}
      {!embedded &&
        current &&
        data?.storage?.map((d, i) => (
          <section className="system-resource-node" key={i}>
            <h3>저장 공간 {i + 1}</h3>
            {d.status === 'connected' ? (
              <dl>
                <div>
                  <dt>전체</dt>
                  <dd>{gb(d.total)}</dd>
                </div>
                <div>
                  <dt>여유</dt>
                  <dd>{gb(d.free)}</dd>
                </div>
              </dl>
            ) : (
              <p>용량 미확인</p>
            )}
          </section>
        ))}
    </section>
  );
  useEffect(() => {
    let live = true;
    const load = async () => {
      try {
        const d = await request<State>('/system/resources');
        if (live) {
          setData(d);
          setError('');
        }
      } catch {
        if (live) {
          setError('현재 자원 상태를 확인하지 못했습니다.');
        }
      }
    };
    void load();
    const timer = setInterval(() => void load(), 15000);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, []);
  return embedded ? (
    content
  ) : (
    <main className="settings-page system-settings">
      <PageTitle>시스템</PageTitle>
      {content}
    </main>
  );
};
