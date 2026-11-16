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
  terminal_text?: string;
  stream?: 'stdout' | 'stderr';
};
type LogResponse = {
  job_id: string;
  records: JobLogRecord[];
  terminal_records?: JobLogRecord[];
  terminal_truncated?: boolean;
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
const capturedText = (row: JobLogRecord) =>
  row.provenance === 'captured' && row.source !== 'stored_failure'
    ? typeof row.terminal_text === 'string'
      ? row.terminal_text
      : row.source === 'console'
        ? row.raw
        : undefined
    : undefined;

export const JobLogExplorer = ({
  jobId,
  enabled = true,
  runs,
  runId = '',
  onRunChange,
  focusRequest = 0,
  onOpenData,
  onOpenStage,
}: {
  jobId: string;
  enabled?: boolean;
  runs: JobLogRun[];
  runId?: string;
  onRunChange: (id: string) => void;
  focusRequest?: number;
  focusErrors?: boolean;
  onOpenData?: (id: string) => void;
  onOpenStage?: (id: string) => void;
}) => {
  const [value, setValue] = useState<LogResponse | null>(null);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [follow, setFollow] = useState(true);
  const [loading, setLoading] = useState(false);
  const sequence = useRef(0);
  const viewport = useRef<HTMLPreElement>(null);
  const owned = value?.job_id === jobId ? value : null;
  const runMap = new Map(runs.map((run) => [run.id, run]));
  for (const source of owned?.sources || []) {
    if (!runMap.has(source.run_id)) {
      const known = runs.find((run) => run.node_id === source.node_id);
      runMap.set(source.run_id, {
        id: source.run_id,
        node_id: source.node_id,
        label: known?.label || source.node_id,
        agentLabel: known?.agentLabel,
      });
    }
  }
  const query = search.toLocaleLowerCase();
  const lines = (owned?.terminal_records || owned?.records || []).filter((row) => {
    const text = capturedText(row);
    return (
      runMap.has(row.run_id) &&
      typeof text === 'string' &&
      (!runId || runId === row.run_id) &&
      (!query || text.toLocaleLowerCase().includes(query))
    );
  });
  useEffect(() => {
    if (focusRequest) {
      setSearch('');
    }
  }, [focusRequest]);
  useEffect(() => {
    if (follow && viewport.current) {
      viewport.current.scrollTop = viewport.current.scrollHeight;
    }
  }, [value, runId, search, follow]);
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
        const next = await request<LogResponse>(`/renewal/jobs/${jobId}/logs`, {
          signal: controller.signal,
        });
        if (next.job_id !== jobId || !Array.isArray(next.records) || !Array.isArray(next.sources)) {
          throw Error('scope');
        }
        if (!controller.signal.aborted && turn === sequence.current) {
          setValue(next);
          setError('');
        }
      } catch {
        if (!controller.signal.aborted && turn === sequence.current) {
          setError('로그 갱신 실패');
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
          태스크
          <select
            aria-label="로그 단계"
            value={runId}
            onChange={(event) => {
              onRunChange(event.target.value);
              setFollow(true);
            }}
          >
            <option value="">전체 태스크</option>
            {[...runMap.values()].map((run) => (
              <option key={run.id} value={run.id}>
                {run.agentLabel ? `${run.agentLabel} · ` : ''}
                {run.label}
              </option>
            ))}
          </select>
        </label>
        <label className="job-log-explorer__search">
          검색
          <input
            type="search"
            aria-label="로그 검색"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="로그 검색"
          />
        </label>
        <button type="button" onClick={() => setFollow(true)} aria-pressed={follow}>
          맨 아래
        </button>
        {runId && onOpenStage && (
          <button type="button" onClick={() => onOpenStage(runId)}>
            태스크 보기
          </button>
        )}
        {runId && onOpenData && (
          <button type="button" onClick={() => onOpenData(runId)}>
            결과 보기
          </button>
        )}
      </div>
      {error && <p role="alert">{error}</p>}
      {owned?.terminal_truncated && <small>이전 로그 일부 생략됨</small>}
      <pre
        ref={viewport}
        className="job-log-explorer__terminal"
        role="log"
        aria-live="off"
        aria-label="터미널 출력"
        tabIndex={0}
        onScroll={() => {
          const node = viewport.current;
          if (node && node.scrollHeight - node.scrollTop - node.clientHeight > 40) {
            setFollow(false);
          }
        }}
      >
        {lines.length
          ? lines.map((row, index) => (
              <span key={row.id} data-log-record={row.id} data-log-stream={row.stream}>
                {capturedText(row)}
                {index < lines.length - 1 ? '\n' : ''}
              </span>
            ))
          : owned
            ? '로그 없음'
            : loading
              ? '불러오는 중…'
              : ''}
      </pre>
    </section>
  );
};
