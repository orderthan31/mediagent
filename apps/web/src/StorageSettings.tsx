import { Progress } from './hangyeol/primitives/progress';
import { LoadingSkeleton } from './LoadingSkeleton';
import { Button } from './hangyeol/primitives/button';
import { Badge } from './hangyeol/primitives/badge';
import { useEffect, useState } from 'react';
import { HardDrive, RefreshCw, Trash2 } from 'lucide-react';
import { request } from './api';
import { statusLabels } from './video-api';
import { Pagination, usePagination } from './Pagination';

type StorageJob = {
  job_id: string;
  filename: string;
  status: string;
  input: number;
  work: number;
  output: number;
  total_bytes: number;
  temporary_bytes: number;
  deletable: boolean;
};
type Disk = { total_bytes: number; used_bytes: number; free_bytes: number };
type Snapshot = {
  checked_at: number;
  disk: Disk;
  host_disk: Disk | null;
  container: boolean;
  total_bytes: number;
  quota_bytes: number;
  categories: Record<string, number>;
  jobs: StorageJob[];
};
const bytes = (value: number) => {
  if (value < 1024) {
    return `${value} B`;
  }
  const index = Math.min(3, Math.floor(Math.log(value) / Math.log(1024)));
  return `${(value / 1024 ** index).toFixed(1)} ${['B', 'KiB', 'MiB', 'GiB'][index]}`;
};
const categories: Record<string, string> = {
  library: '보관함 원본 영상',
  input: '작업 입력 파일',
  work: '전사·번역·합성 중간 파일',
  output: '결과 영상·자막',
  uploads: '업로드 파일',
  faceswap: '얼굴 합성 설정·사진',
  other: '설정·작업 기록 등',
};

export const StorageSettings = () => {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const page = usePagination(snapshot?.jobs || [], 'storage-jobs');
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [mode, setMode] = useState<'temporary' | 'jobs' | null>(null);
  const chosen = snapshot?.jobs.filter((job) => selected.includes(job.job_id)) || [];
  const reclaim = chosen.reduce(
    (sum, job) => sum + (mode === 'jobs' ? job.total_bytes : job.temporary_bytes),
    0,
  );
  const disk = snapshot?.host_disk || snapshot?.disk;
  const load = async () => {
    setBusy(true);
    setError('');
    try {
      setSnapshot(await request<Snapshot>('/settings/storage'));
      setSelected([]);
      setMode(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : '저장 공간 조회 실패');
    } finally {
      setBusy(false);
    }
  };
  const clean = async () => {
    if (!mode || busy) {
      return;
    }
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const result = await request<{ removed_bytes: number; results: { status: string }[] }>(
        '/settings/storage/cleanup',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ mode, job_ids: selected }),
        },
      );
      const skipped = result.results.filter((r) => r.status !== 'cleaned').length;
      setNotice(
        `${bytes(result.removed_bytes)}의 파일을 정리했습니다.${skipped ? ` 사용 중이거나 삭제할 수 없는 작업 ${skipped}개는 제외했습니다.` : ''}`,
      );
      setSelected([]);
      setMode(null);
      setSnapshot(await request<Snapshot>('/settings/storage'));
    } catch (e) {
      setError(e instanceof Error ? e.message : '정리 실패');
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => {
    void load();
  }, []);
  return (
    <section className="storage-settings" aria-labelledby="storage-title">
      <div className="settings-heading">
        <h2 id="storage-title">
          <HardDrive size={20} /> 저장 공간
        </h2>
        <Button variant="secondary" type="button" disabled={busy} onClick={() => void load()}>
          <RefreshCw size={16} /> {busy ? '확인 중…' : '용량 새로고침'}
        </Button>
      </div>
      <p className="feature-intro">
        서비스 전체 사용량을 확인하고, 내 작업 파일만 선택해 정리하세요.
      </p>
      <Badge>{snapshot ? (error ? '이전 조회 · 최신 아님' : '조회 완료') : '사용량 미확인'}</Badge>
      {error && (
        <p role="alert" className="alert">
          {error}
        </p>
      )}
      {notice && <p role="status">{notice}</p>}
      {!snapshot && !error && <LoadingSkeleton layout="table" label="저장 공간 불러오는 중" />}
      {snapshot && disk && (
        <>
          <div className="storage-summary">
            <div>
              <span>
                {snapshot.container && !snapshot.host_disk
                  ? 'Docker 저장 디스크 잔여 용량'
                  : '컴퓨터 디스크 잔여 용량'}
              </span>
              <strong>{bytes(disk.free_bytes)}</strong>
              <small>전체 {bytes(disk.total_bytes)}</small>
              <Progress label="디스크 사용 비율" max={disk.total_bytes} value={disk.used_bytes} />
            </div>
            <div>
              <span>서비스 파일 사용량</span>
              <strong>{bytes(snapshot.total_bytes)}</strong>
              <small>서비스 한도 {bytes(snapshot.quota_bytes)}</small>
            </div>
          </div>
          {snapshot.container && (
            <p className="key-status">
              {snapshot.host_disk
                ? '호스트에서 연결한 폴더가 있는 디스크 기준입니다.'
                : 'Docker 내부 파일시스템 기준입니다. Windows 실제 디스크 잔여 용량과 다를 수 있습니다.'}{' '}
              Docker 볼륨 정리 후 Windows 디스크 반환에는 가상 디스크 압축이 필요할 수 있습니다.
            </p>
          )}
          <dl className="storage-breakdown">
            {Object.entries(categories).map(([key, label]) => (
              <div key={key}>
                <dt>{label}</dt>
                <dd>{bytes(snapshot.categories[key] || 0)}</dd>
              </div>
            ))}
          </dl>
          <p className="key-status">
            전체 사용자의 서비스 파일 크기 합계이며, 모델·Docker 이미지와 프로젝트 외부 파일은
            포함하지 않습니다. 마지막 확인:{' '}
            {new Date(snapshot.checked_at * 1000).toLocaleTimeString()}
          </p>
          <h3>내 작업 파일 정리</h3>
          <p>
            중간 파일 정리는 완료된 작업의 임시 영상·오디오·로그를 비웁니다. 결과물과 자막 편집
            데이터는 보존합니다. 전체 삭제는 선택한 작업의 입력·중간·결과 파일과 기록을 삭제합니다.
          </p>
          <p className="key-status">
            보관함 원본 영상은 보관함에서 별도로 삭제할 수 있습니다. 진행 중·검토 대기·다운로드 중인
            작업은 보호합니다. 한 번에 최대 100개를 선택할 수 있습니다.
          </p>
          <div className="storage-table-wrap">
            <table className="storage-table">
              <thead>
                <tr>
                  <th>선택</th>
                  <th>작업</th>
                  <th>입력</th>
                  <th>중간</th>
                  <th>결과</th>
                </tr>
              </thead>
              <tbody>
                {page.items.map((job) => (
                  <tr key={job.job_id}>
                    <td>
                      <input
                        type="checkbox"
                        aria-label={`${job.filename} 정리 선택`}
                        disabled={
                          busy ||
                          !!mode ||
                          !job.deletable ||
                          (selected.length >= 100 && !selected.includes(job.job_id))
                        }
                        checked={selected.includes(job.job_id)}
                        onChange={(e) =>
                          setSelected(
                            e.target.checked
                              ? [...selected, job.job_id]
                              : selected.filter((id) => id !== job.job_id),
                          )
                        }
                      />
                    </td>
                    <td>
                      <span>{job.filename}</span>
                      <small>
                        {statusLabels[job.status] || job.status}
                        {!job.deletable ? ' · 보호 중' : ''}
                      </small>
                    </td>
                    <td data-label="입력">{bytes(job.input)}</td>
                    <td data-label="중간">{bytes(job.work)}</td>
                    <td data-label="결과">{bytes(job.output)}</td>
                  </tr>
                ))}
                {!snapshot.jobs.length && (
                  <tr>
                    <td colSpan={5}>저장된 작업이 없습니다.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <Pagination {...page} disabled={busy || !!mode} />
          <div className="storage-actions">
            <Button
              variant="secondary"
              type="button"
              disabled={busy || !!mode}
              onClick={() =>
                setSelected(
                  snapshot.jobs
                    .filter((j) => j.deletable)
                    .slice(0, 100)
                    .map((j) => j.job_id),
                )
              }
            >
              종료된 작업 선택
            </Button>
            <Button
              variant="secondary"
              type="button"
              disabled={busy || !!mode || !chosen.some((j) => j.temporary_bytes > 0)}
              onClick={() => setMode('temporary')}
            >
              중간 파일 비우기
            </Button>
            <Button
              variant="secondary"
              type="button"
              disabled={busy || !!mode || !selected.length}
              onClick={() => setMode('jobs')}
            >
              <Trash2 size={16} /> 선택 작업 전체 삭제
            </Button>
          </div>
          {mode && (
            <div className="storage-confirm" role="group" aria-label="파일 삭제 확인">
              <strong>
                {selected.length}개 작업 · 약 {bytes(reclaim)} 정리
              </strong>
              <p>
                {mode === 'jobs'
                  ? '결과 영상·자막과 작업 기록까지 삭제하며 복구할 수 없습니다. 필요한 결과물을 다운로드했는지 확인하세요.'
                  : '완료된 작업의 중간 파일만 삭제합니다. 실패·취소 작업은 재시도에 필요하므로 제외합니다.'}
              </p>
              <div className="storage-actions">
                <Button
                  variant="secondary"
                  type="button"
                  disabled={busy}
                  onClick={() => setMode(null)}
                >
                  취소
                </Button>
                <Button
                  variant="secondary"
                  type="button"
                  className="primary"
                  disabled={busy}
                  onClick={() => void clean()}
                >
                  {busy ? '정리 중…' : '확인하고 비우기'}
                </Button>
              </div>
            </div>
          )}
        </>
      )}
    </section>
  );
};
