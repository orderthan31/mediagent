import { useEffect, useState } from 'react';
import { request } from './api';
import { PageTitle } from './PageTitle';
type Node = {
  id: string;
  name: string;
  cpu_percent: number | null;
  logical_processors: number;
  memory_total: number;
  memory_available: number;
  gpu?: string[];
};
type Disk = { name: string; total: number; free: number; source: string; status?: string };
type State = {
  status: string;
  observed_at?: string;
  notice?: string;
  nodes: Node[];
  storage: Disk[];
};
const gb = (n: number) => (Number.isFinite(n) ? (n / 1024 ** 3).toFixed(1) + ' GiB' : '미확인');
export const SystemResources = () => {
  const [data, setData] = useState<State | null>(null);
  const [error, setError] = useState('');
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
  return (
    <main className="settings-page">
      <PageTitle>시스템</PageTitle>
      <h2>컴퓨터·스토리지</h2>
      {error && <p role="alert">{error}</p>}
      <p role="status">
        {data?.status === 'connected' ? '자원 수집 연결됨' : data?.notice || '자원 상태 확인 중'}
      </p>
      {data?.observed_at && <p>최근 수집 {new Date(data.observed_at).toLocaleString('ko-KR')}</p>}
      {data?.nodes.map((n) => (
        <section key={n.id}>
          <h3>{n.name}</h3>
          <p>
            CPU {n.logical_processors}개 · 사용{' '}
            {n.cpu_percent === null ? '미확인' : n.cpu_percent + '%'}
            {n.cpu_percent === null ? '' : ' · 유휴 ' + Math.max(0, 100 - n.cpu_percent) + '%'}
          </p>
          <p>
            메모리 전체 {gb(n.memory_total)} · 사용 가능 {gb(n.memory_available)}
          </p>
          {n.gpu?.map((g, i) => (
            <p key={i}>
              GPU {g.split(',')[0]} · 사용 {g.split(',')[1]?.trim() || '미확인'}% · 메모리{' '}
              {g.split(',')[2]?.trim() || '미확인'} / {g.split(',')[3]?.trim() || '미확인'} MiB
            </p>
          ))}
        </section>
      ))}
      <h2>저장 공간</h2>
      {data?.storage.map((d) => (
        <section key={d.name}>
          <h3>{d.name}</h3>
          <p>
            {d.status === 'unavailable'
              ? '연결 미확인'
              : '전체 ' + gb(d.total) + ' · 사용 ' + gb(d.total - d.free) + ' · 여유 ' + gb(d.free)}
          </p>
          <p>{d.source}</p>
        </section>
      ))}
    </main>
  );
};
