import { useEffect, useRef, useState } from 'react';
import { request } from './api';
import './job-log-explorer.css';

export type JobLogRecord = {
  id: string;
  at: string | null;
  level: 'INFO' | 'WARNING' | 'ERROR' | 'UNKNOWN';
  message: string;
  run_id: string;
  node_id: string;
  tool_id?: string;
  unit_index?: number;
  candidate_index?: number;
  error_code?: string;
  error_type?: string;
  elapsed_ms?: number;
  source: 'diagnostic' | 'console' | 'stored_failure';
  provenance: 'captured' | 'recorded_state';
  raw?: string;
};
type LogResponse = {
  job_id: string;
  records: JobLogRecord[];
  has_more: boolean;
  truncated: boolean;
  total_records: number;
  sources: {
    run_id: string;
    node_id: string;
    available: boolean;
    raw_available: boolean;
    policy?: string;
    truncated: boolean;
  }[];
};
export type JobLogRun = { id: string; node_id: string; label: string; agentLabel?: string };
const provenanceLabel = (record: JobLogRecord) =>
  record.provenance === 'recorded_state'
    ? '저장된 실패 정보'
    : record.source === 'diagnostic'
      ? '수집 진단'
      : '터미널 출력';
const timeLabel = (at: string | null) => {
  if (!at || !Number.isFinite(Date.parse(at))) {
    return '시각 미기록';
  }
  return new Intl.DateTimeFormat('ko-KR', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(new Date(at));
};
const levelLabel = (level: JobLogRecord['level']) => (level === 'UNKNOWN' ? '등급 없음' : level);

export const JobLogExplorer = ({
  jobId,
  enabled = true,
  runs,
  runId = '',
  onRunChange,
  focusRequest = 0,
  focusErrors = false,
  onOpenData,
  onOpenStage,
}: {
  jobId: string;
  enabled?: boolean;
  runs: JobLogRun[];
  runId?: string;
  onRunChange: (runId: string) => void;
  focusRequest?: number;
  focusErrors?: boolean;
  onOpenData?: (runId: string) => void;
  onOpenStage?: (runId: string) => void;
}) => {
  const [value, setValue] = useState<LogResponse | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [level, setLevel] = useState('ALL');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(0);
  const sequence = useRef(0);
  const owned = value?.job_id === jobId ? value : null;
  const runMap = new Map(runs.map((run) => [run.id, run]));
  for (const source of owned?.sources || []) {
    if (!runMap.has(source.run_id)) {
      const stage = runs.find((run) => run.node_id === source.node_id);
      runMap.set(source.run_id, {
        id: source.run_id,
        node_id: source.node_id,
        label: `${stage?.label || source.node_id} · 이전/추가 실행 ${source.run_id.slice(0, 8)}`,
        agentLabel: stage?.agentLabel,
      });
    }
  }
  const records = (owned?.records || []).filter((record) => runMap.has(record.run_id));
  const query = search.trim().toLocaleLowerCase();
  const filtered = records.filter((record) => {
    const run = runMap.get(record.run_id);
    return (
      (!runId || record.run_id === runId) &&
      (level === 'ALL' || record.level === level) &&
      (!query ||
        [
          record.message,
          record.error_code,
          record.error_type,
          record.tool_id,
          run?.label,
          run?.agentLabel,
        ].some((field) => field?.toLocaleLowerCase().includes(query)))
    );
  });
  const scoped = records.filter((record) => !runId || record.run_id === runId);
  const errors = scoped.filter((record) => record.level === 'ERROR').length;
  const warnings = scoped.filter((record) => record.level === 'WARNING').length;
  const lastPage = Math.max(0, Math.ceil(filtered.length / 100) - 1);
  const currentPage = Math.min(page, lastPage);
  const shown = filtered.slice(currentPage * 100, (currentPage + 1) * 100);
  const privateSources = owned?.sources.some(
    (source) => (!runId || source.run_id === runId) && source.policy === 'private_diagnostics_v1',
  );
  const selectLevel = (next: string) => {
    setLevel(next);
    setPage(0);
  };

  useEffect(() => {
    if (focusRequest) {
      setLevel(focusErrors ? 'ERROR' : 'ALL');
      setPage(0);
    }
  }, [focusRequest, focusErrors]);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    if (!enabled) {
      return () => controller.abort();
    }
    const load = async () => {
      const turn = ++sequence.current;
      setLoading(true);
      try {
        const result = await request<LogResponse>(`/renewal/jobs/${jobId}/logs`, {
          signal: controller.signal,
        });
        if (
          result.job_id !== jobId ||
          !Array.isArray(result.records) ||
          !Array.isArray(result.sources)
        ) {
          throw new Error('Log scope mismatch');
        }
        if (!controller.signal.aborted && turn === sequence.current) {
          setValue(result);
          setError('');
        }
      } catch {
        if (!controller.signal.aborted && turn === sequence.current) {
          setError('로그를 갱신하지 못했습니다. 마지막으로 확인한 기록을 표시합니다.');
        }
      } finally {
        if (!controller.signal.aborted && turn === sequence.current) {
          setLoading(false);
          timer = setTimeout(() => void load(), 4000);
        }
      }
    };
    void load();
    return () => {
      controller.abort();
      clearTimeout(timer);
      sequence.current++;
    };
  }, [jobId, enabled]);

  return (
    <section className="job-log-explorer" aria-label="작업 로그">
      <div className="job-log-explorer__filters">
        <label>
          단계
          <select
            aria-label="로그 단계"
            value={runId}
            onChange={(event) => {
              onRunChange(event.target.value);
              setPage(0);
            }}
          >
            <option value="">전체 단계</option>
            {[...runMap.values()].map((run) => (
              <option key={run.id} value={run.id}>
                {run.agentLabel ? `${run.agentLabel} · ` : ''}
                {run.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          등급
          <select
            aria-label="로그 등급"
            value={level}
            onChange={(event) => selectLevel(event.target.value)}
          >
            <option value="ALL">전체 등급</option>
            <option value="INFO">INFO</option>
            <option value="WARNING">WARNING</option>
            <option value="ERROR">ERROR</option>
            <option value="UNKNOWN">등급 없음</option>
          </select>
        </label>
        <label className="job-log-explorer__search">
          로그 검색
          <input
            type="search"
            value={search}
            onChange={(event) => {
              setSearch(event.target.value);
              setPage(0);
            }}
            placeholder="메시지·오류 코드·툴"
          />
        </label>
      </div>
      <div className="job-log-explorer__summary">
        <span>{filtered.length}개 기록</span>
        <button type="button" disabled={!errors} onClick={() => selectLevel('ERROR')}>
          ERROR {errors}
        </button>
        <button type="button" disabled={!warnings} onClick={() => selectLevel('WARNING')}>
          WARNING {warnings}
        </button>
        <span role="status">{loading ? '갱신 중' : owned ? '기록 갱신됨' : '로그 확인 중'}</span>
      </div>
      {error && <p role="alert">{error}</p>}
      {(owned?.truncated || owned?.has_more) && (
        <p className="job-log-explorer__notice">
          조회 또는 보존 상한으로 일부 기록이 생략되었습니다. 표시 건수는 확인한 기록 범위입니다.
        </p>
      )}
      {privateSources && (
        <p className="job-log-explorer__notice">
          보호된 태스크의 원본 stdout/stderr는 보존되지 않거나 공개되지 않습니다. 아래 수집 진단과
          저장된 실패 정보는 원본 터미널 출력과 구분됩니다.
        </p>
      )}
      {!owned && !error && <p role="status">작업 로그를 불러오는 중입니다.</p>}
      {owned && !filtered.length && (
        <p className="job-log-explorer__empty">
          {records.length
            ? '조건에 맞는 기록이 없습니다.'
            : '보존된 로그가 없습니다. 수집되지 않은 과거 원문은 복원할 수 없습니다.'}
        </p>
      )}
      {!!shown.length && (
        <div
          className="job-log-explorer__terminal"
          role="log"
          aria-live="off"
          aria-label="시간·등급·단계별 로그"
        >
          <div className="job-log-explorer__columns" aria-hidden="true">
            <span>시간</span>
            <span>등급</span>
            <span>발생 위치</span>
            <span>메시지</span>
          </div>
          {shown.map((record) => {
            const run = runMap.get(record.run_id);
            const unit =
              Number.isSafeInteger(record.unit_index) && record.unit_index! >= 0
                ? `구간 ${record.unit_index! + 1}`
                : '';
            return (
              <article
                className="job-log-explorer__record"
                data-log-record={record.id}
                data-log-level={record.level}
                key={record.id}
              >
                <time dateTime={record.at || undefined} title={record.at || undefined}>
                  {timeLabel(record.at)}
                </time>
                <span className={`job-log-explorer__level is-${record.level.toLowerCase()}`}>
                  {levelLabel(record.level)}
                </span>
                <div className="job-log-explorer__location">
                  <strong>{run?.agentLabel || run?.label}</strong>
                  {run?.agentLabel && <span>{run.label}</span>}
                  {record.tool_id && <code>{record.tool_id}</code>}
                  {unit && (
                    <span>
                      {unit}
                      {Number.isSafeInteger(record.candidate_index)
                        ? ` · 후보 ${record.candidate_index! + 1}`
                        : ''}
                    </span>
                  )}
                </div>
                <div className="job-log-explorer__message">
                  <p>{record.message}</p>
                  <small>
                    {provenanceLabel(record)}
                    {record.elapsed_ms != null && Number.isFinite(record.elapsed_ms)
                      ? ` · ${record.elapsed_ms}ms`
                      : ''}
                  </small>
                  {(record.raw || record.error_code || record.error_type) && (
                    <details>
                      <summary>
                        {record.source === 'console' ? '원문·오류 상세' : '진단·오류 상세'}
                      </summary>
                      {record.error_code && (
                        <p>
                          오류 코드: <code>{record.error_code}</code>
                        </p>
                      )}
                      {record.error_type && (
                        <p>
                          예외: <code>{record.error_type}</code>
                        </p>
                      )}
                      {record.raw && <pre>{record.raw}</pre>}
                    </details>
                  )}
                  {record.level !== 'INFO' && runs.some((item) => item.id === record.run_id) && (
                    <div className="job-log-explorer__links">
                      {onOpenStage && (
                        <button type="button" onClick={() => onOpenStage(record.run_id)}>
                          해당 단계
                        </button>
                      )}
                      {onOpenData && (
                        <button type="button" onClick={() => onOpenData(record.run_id)}>
                          관련 데이터
                        </button>
                      )}
                    </div>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      )}
      {lastPage > 0 && (
        <nav className="job-log-explorer__pages" aria-label="로그 페이지">
          <button type="button" disabled={!currentPage} onClick={() => setPage(currentPage - 1)}>
            이전
          </button>
          <span>
            {currentPage + 1} / {lastPage + 1}
          </span>
          <button
            type="button"
            disabled={currentPage >= lastPage}
            onClick={() => setPage(currentPage + 1)}
          >
            다음
          </button>
        </nav>
      )}
    </section>
  );
};
