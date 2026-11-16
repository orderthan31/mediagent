import { useEffect, useRef, useState } from 'react';
import { mediaUrl, request } from './api';
import { authenticatedFetch } from './auth-session';
import type { GoalOutput } from './GoalResults';
import { SrtCopyAction } from './SrtCopyEditor';
import { artifactSrtSource, trackSrtSource, type SrtCopySource } from './srt-copy';
import { FullVideoPreview } from './FullVideoPreview';
import './job-results.css';

type FileRef = { type: string; sha256?: string; bytes?: number };
type FileRun = {
  id: string;
  node_id: string;
  status: string;
  display_status?: string;
  started_at?: string | null;
  completed_at?: string | null;
  inputs?: Record<string, FileRef>;
  result?: { outputs: Record<string, FileRef> } | null;
};
type ResultFile = {
  run: FileRun;
  port: string;
  reference: FileRef;
  label: string;
  key: string;
  path?: string;
  downloadPath?: string;
  fullPreviewPath?: string | null;
  category?: 'original' | 'input' | 'result' | 'intermediate';
  filename?: string;
  copySource?: SrtCopySource | null;
};
type SubtitleOutput = {
  run_id: string;
  tracks: Record<
    string,
    {
      language: string;
      files: Record<
        string,
        { filename: string; reference: { type: string; sha256: string; bytes: number } }
      >;
    }
  >;
};
export const outputLabel = (port: string, type: string) =>
  ({
    video: '결과 영상',
    audio: '음성(WAV)',
    transcript: '전사문(JSON)',
    timeline: '시간 정보(JSON)',
    media_metadata: '영상 정보(JSON)',
    validation_report: '영상 확인 보고서(JSON)',
    audio_regions: '음성 구간(JSON)',
    artifact_manifest: '파일 목록(JSON)',
    metadata: '정보(JSON)',
  })[type] ||
  (type === 'subtitle' ? (port === 'sami' ? '자막 SAMI' : '자막 SRT') : `결과 파일 · ${port}`);

// Prefer the requested goal's canonical route when several tools exported the
// same bytes. Missing hashes never establish that two distinct files are equal.
const fileKey = (run: FileRun, port: string, _ref: FileRef) => `${run.id}:${port}`;
const contentKey = (ref: FileRef) =>
  typeof ref.sha256 === 'string' &&
  /^[a-f0-9]{64}$/.test(ref.sha256) &&
  Number.isSafeInteger(ref.bytes) &&
  ref.bytes! >= 0
    ? `${ref.type}:${ref.sha256}:${ref.bytes}`
    : null;
const fileContentKey = (file: Pick<ResultFile, 'reference' | 'port'>) => {
  const content = contentKey(file.reference);
  if (!content) {
    return null;
  }
  return file.reference.type === 'subtitle'
    ? `${content}:${['sami', 'smi'].includes(file.port) ? 'smi' : 'srt'}`
    : content;
};
const unique = (files: ResultFile[], seen = new Set<string>()) =>
  files.filter((file) => {
    if (seen.has(file.key)) {
      return false;
    }
    seen.add(file.key);
    return true;
  });
export const collectJobFiles = (runs: FileRun[], agents: { outputs?: GoalOutput[] }[] = []) => {
  const files = runs.flatMap((run) =>
    run.status === 'completed'
      ? Object.entries(run.result?.outputs || {}).map(([port, reference]) => ({
          run,
          port,
          reference,
          label: outputLabel(port, reference.type),
          key: fileKey(run, port, reference),
        }))
      : [],
  );
  const requested = agents
    .flatMap((agent) => agent.outputs || [])
    .flatMap((output) => {
      const file = files.find(
        (row) =>
          row.run.id === output.run_id &&
          row.run.node_id === output.node_id &&
          row.port === output.port,
      );
      return file ? [{ ...file, label: outputLabel(output.name, file.reference.type) }] : [];
    });
  const main = unique(
    agents.length
      ? requested
      : files.filter((file) =>
          ['video', 'audio', 'subtitle', 'transcript'].includes(file.reference.type),
        ),
  );
  const seenRoutes = new Set(main.map((file) => file.key));
  const seenContent = new Set(
    main.map((file) => fileContentKey(file)).filter((key) => key !== null),
  );
  const intermediate = files.filter((file) => {
    const content = fileContentKey(file);
    if (seenRoutes.has(file.key) || (content !== null && seenContent.has(content))) {
      return false;
    }
    seenRoutes.add(file.key);
    if (content !== null) {
      seenContent.add(content);
    }
    return true;
  });
  return { main, intermediate };
};
const artifactPath = (base: string, file: ResultFile) =>
  file.path ??
  `${base}/artifacts/${encodeURIComponent(file.run.id)}/${encodeURIComponent(file.port)}`;

const TextFilePreview = ({ path, bytes }: { path: string; bytes?: number }) => {
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setText(null);
    setError('');
    const load = async () => {
      const limit = 2 * 1024 * 1024;
      if (typeof bytes === 'number' && bytes > limit) {
        setError('큰 파일은 다운로드해서 확인하세요.');
        return;
      }
      try {
        const response = await authenticatedFetch(mediaUrl(path), { signal: controller.signal });
        if (!response.ok || !response.body) {
          throw new Error('파일을 불러오지 못했습니다.');
        }
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        const chunks: string[] = [];
        let size = 0;
        try {
          for (;;) {
            const { done, value } = await reader.read();
            if (done) {
              break;
            }
            size += value.byteLength;
            if (size > limit) {
              await reader.cancel();
              throw new Error('큰 파일은 다운로드해서 확인하세요.');
            }
            chunks.push(decoder.decode(value, { stream: true }));
          }
          chunks.push(decoder.decode());
        } finally {
          reader.releaseLock();
        }
        if (active) {
          setText(chunks.join(''));
        }
      } catch (reason) {
        if (active && !controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : '파일을 불러오지 못했습니다.');
        }
      }
    };
    void load();
    return () => {
      active = false;
      controller.abort();
    };
  }, [path, bytes]);
  return error ? (
    <p role="alert">{error}</p>
  ) : text === null ? (
    <p role="status">파일 불러오는 중</p>
  ) : (
    <pre className="job-result-text">{text}</pre>
  );
};

export type JobOriginalSource = {
  asset_id: string;
  original_filename: string;
  type?: 'video' | 'audio' | 'subtitle';
  bytes?: number;
  sha256?: string;
};
const categoryLabel = {
  original: '원본',
  input: '단계 입력',
  result: '결과',
  intermediate: '중간 파일',
};
const statusLabel = (status: string) =>
  ({
    completed: '완료',
    failed: '실패',
    running: '처리 중',
    waiting: '대기',
    queued: '대기',
    held: '보류',
    cancelled: '취소',
    available: '등록됨',
  })[status] || status;
const actualDuration = (run: FileRun) => {
  if (!run.started_at || !run.completed_at) {
    return '—';
  }
  const duration = Date.parse(run.completed_at) - Date.parse(run.started_at);
  return Number.isFinite(duration) && duration >= 0 ? `${(duration / 1000).toFixed(1)}초` : '—';
};
const fileSize = (bytes?: number) => {
  if (typeof bytes !== 'number' || !Number.isSafeInteger(bytes) || bytes < 0) {
    return '—';
  }
  if (bytes < 1000) {
    return `${bytes} B`;
  }
  if (bytes < 1e6) {
    return `${(bytes / 1000).toFixed(2)} KB`;
  }
  if (bytes < 1e9) {
    return `${(bytes / 1e6).toFixed(2)} MB`;
  }
  return `${(bytes / 1e9).toFixed(2)} GB`;
};
const runState = (run: FileRun) => run.display_status || run.status;
const previewIdentity = (base: string, file: ResultFile) =>
  `${base}:${file.key}:${file.reference.sha256 ?? ''}:${file.reference.bytes ?? ''}`;

export const JobFiles = ({
  base,
  runs,
  agents = [],
  stale = false,
  subtitleOutputsEnabled = false,
  revision = 0,
  stageLabels = {},
  selectedRunId,
  selectionRequest = 0,
  onOpenLogs,
  originalSource,
}: {
  base: string;
  runs: FileRun[];
  agents?: { id: string; label: string; outputs?: GoalOutput[] }[];
  manifest?: { entry_count: number };
  stale?: boolean;
  subtitleOutputsEnabled?: boolean;
  revision?: number;
  stageLabels?: Record<string, string>;
  selectedRunId?: string;
  selectionRequest?: number;
  onOpenLogs?: (runId: string) => void;
  originalSource?: JobOriginalSource | null;
}) => {
  const [subtitleData, setSubtitleData] = useState<{ base: string; rows: SubtitleOutput[] } | null>(
    null,
  );
  const [subtitleError, setSubtitleError] = useState('');
  const collected = collectJobFiles(runs, agents);
  const jobId = base.match(/^\/renewal\/jobs\/([a-f0-9]{32})$/)?.[1];
  const subtitleFiles: ResultFile[] = (
    subtitleOutputsEnabled && subtitleData?.base === base ? subtitleData.rows : []
  ).flatMap((output) =>
    Object.entries(output.tracks).flatMap(([name, track]) =>
      Object.entries(track.files).map(([extension, file]) => {
        const run = runs.find((row) => row.id === output.run_id) ?? {
          id: output.run_id,
          node_id: '',
          status: 'unknown',
          result: null,
        };
        return {
          run,
          port: extension,
          reference: file.reference,
          label: `${track.language} · ${extension.toUpperCase()}`,
          filename: file.filename,
          key: fileKey(run, `${name}:${extension}`, file.reference),
          path: `${base}/subtitle-outputs/${encodeURIComponent(output.run_id)}/${encodeURIComponent(name)}/${encodeURIComponent(extension)}`,
          copySource: jobId ? trackSrtSource(jobId, output.run_id, name, extension, file) : null,
        };
      }),
    ),
  );
  const subtitleContent = new Set(
    subtitleFiles.map((file) => fileContentKey(file)).filter((key) => key !== null),
  );
  // A named language/format is a distinct requested result even if its bytes
  // happen to match another track. Only canonical-route aliases are collapsed.
  const main = unique([...collected.main, ...subtitleFiles]);
  const intermediate = unique(
    collected.intermediate.filter((file) => {
      const content = fileContentKey(file);
      return content === null || !subtitleContent.has(content);
    }),
    new Set(main.map((file) => file.key)),
  );
  const outputFiles: ResultFile[] = [
    ...main.map((file) => ({ ...file, category: 'result' as const })),
    ...intermediate.map((file) => ({ ...file, category: 'intermediate' as const })),
  ];
  const original: ResultFile[] =
    originalSource && /^[a-f0-9]{32}$/.test(originalSource.asset_id)
      ? [
          {
            key: `original:${originalSource.asset_id}`,
            port: 'original',
            run: { id: '', node_id: '', status: 'available' },
            reference: {
              type: originalSource.type ?? 'video',
              bytes: originalSource.bytes,
              sha256: originalSource.sha256,
            },
            label: originalSource.original_filename,
            category: 'original',
            path: `/videos/${originalSource.asset_id}/download`,
            downloadPath: `/videos/${originalSource.asset_id}/download`,
            fullPreviewPath: `/videos/${originalSource.asset_id}/preview/full`,
            copySource: null,
          },
        ]
      : [];
  const seenInputs = new Set(
    [...outputFiles, ...original].map((file) => fileContentKey(file)).filter((key) => key !== null),
  );
  const inputFiles: ResultFile[] = runs.flatMap((run) =>
    Object.entries(run.inputs || {}).flatMap(([port, reference]) => {
      if (!reference || typeof reference.type !== 'string') {
        return [];
      }
      const content = fileContentKey({ reference, port });
      if (content && seenInputs.has(content)) {
        return [];
      }
      if (content) {
        seenInputs.add(content);
      }
      const path = `${base}/inputs/${encodeURIComponent(run.id)}/${encodeURIComponent(port)}`;
      return [
        {
          run,
          port,
          reference,
          key: `input:${run.id}:${port}`,
          label: `입력 · ${port}`,
          category: 'input' as const,
          path,
          downloadPath: path,
          fullPreviewPath: null,
          copySource: null,
        },
      ];
    }),
  );
  const files = [...original, ...inputFiles, ...outputFiles];
  // A run without a published file still has an honest status/log destination.
  const stageOnly = runs.filter(
    (run) => run.status !== 'completed' || !Object.keys(run.result?.outputs || {}).length,
  );
  const [query, setQuery] = useState('');
  const [kind, setKind] = useState('all');
  const [stage, setStage] = useState('all');
  const [status, setStatus] = useState('all');

  const [preview, setPreview] = useState<{ base: string; key: string; identity: string } | null>(
    null,
  );
  const [videoFallback, setVideoFallback] = useState('');
  const pane = useRef<HTMLElement>(null);
  const selected =
    preview?.base === base
      ? files.find(
          (file) => file.key === preview.key && preview.identity === previewIdentity(base, file),
        )
      : undefined;
  const stageLabel = (run: FileRun) => stageLabels[run.node_id] || run.node_id || '원본';
  const matches = (run: FileRun, text: string) =>
    (stage === 'all' || run.id === (stage === 'selected' ? selectedRunId : stage)) &&
    (status === 'all' || runState(run) === status) &&
    text.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase());
  const visible = files.filter(
    (file) =>
      (kind === 'all' || kind === file.category || kind === file.reference.type) &&
      matches(
        file.run,
        `${file.label} ${file.filename || ''} ${file.port} ${file.reference.type} ${stageLabel(file.run)}`,
      ),
  );
  const visibleStages =
    kind === 'all' || kind === 'stage'
      ? stageOnly.filter((run) => matches(run, stageLabel(run)))
      : [];
  const rows = () => (
    <table className="job-data-table">
      <caption>작업 전체 파일과 단계 상태</caption>
      <thead>
        <tr>
          <th scope="col">단계</th>
          <th scope="col">파일 · 유형</th>
          <th scope="col">크기</th>
          <th scope="col">상태</th>
          <th scope="col">단계 소요 시간</th>
          <th scope="col">작업</th>
        </tr>
      </thead>
      <tbody>
        {visible.map((file) => (
          <tr
            key={file.key}
            data-result-key={file.key}
            data-selected-run={file.run.id === selectedRunId || undefined}
          >
            <td data-label="단계">{stageLabel(file.run)}</td>
            <td data-label="파일 · 유형">
              <strong>{file.label}</strong>
              <small>
                {file.filename || file.port} · {file.reference.type} ·{' '}
                {categoryLabel[file.category || 'result']}
              </small>
            </td>
            <td
              data-label="크기"
              title={
                file.reference.bytes === undefined ? undefined : `${file.reference.bytes} bytes`
              }
            >
              {fileSize(file.reference.bytes)}
            </td>
            <td data-label="상태">{statusLabel(runState(file.run))}</td>
            <td data-label="단계 소요 시간">{actualDuration(file.run)}</td>
            <td data-label="작업">
              <div className="job-data-actions">
                <button
                  type="button"
                  aria-label={`${file.label} 보기`}
                  onClick={() => {
                    setPreview({ base, key: file.key, identity: previewIdentity(base, file) });
                    setVideoFallback('');
                    requestAnimationFrame(() => pane.current?.scrollIntoView({ block: 'nearest' }));
                  }}
                >
                  보기
                </button>
                <a
                  href={mediaUrl(file.downloadPath ?? artifactPath(base, file) + '?download=true')}
                  download
                  aria-label={`${file.label} 다운로드`}
                >
                  다운로드
                </a>
                <SrtCopyAction
                  key={previewIdentity(base, file)}
                  source={
                    file.copySource === undefined
                      ? artifactSrtSource(base, file.run, file.port)
                      : file.copySource
                  }
                />
                {onOpenLogs && file.run.id && (
                  <button type="button" onClick={() => onOpenLogs(file.run.id)}>
                    로그
                  </button>
                )}
              </div>
            </td>
          </tr>
        ))}
        {visibleStages.map((run) => (
          <tr
            key={`stage:${run.id}`}
            data-stage-run={run.id}
            data-selected-run={run.id === selectedRunId || undefined}
          >
            <td data-label="단계">{stageLabel(run)}</td>
            <td data-label="파일 · 유형">생성된 파일 없음</td>
            <td data-label="크기">—</td>
            <td data-label="상태">{statusLabel(runState(run))}</td>
            <td data-label="단계 소요 시간">{actualDuration(run)}</td>
            <td data-label="작업">
              {onOpenLogs ? (
                <button type="button" onClick={() => onOpenLogs(run.id)}>
                  로그
                </button>
              ) : (
                '—'
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
  useEffect(() => {
    if (selectionRequest) {
      setStage(selectedRunId ? 'selected' : 'all');
      setQuery('');
      setKind('all');
      setStatus('all');
    }
  }, [selectionRequest, selectedRunId]);
  useEffect(() => {
    const controller = new AbortController();
    if (!subtitleOutputsEnabled) {
      setSubtitleData(null);
      setSubtitleError('');
      return () => controller.abort();
    }
    void request<{ outputs: SubtitleOutput[] }>(base + '/subtitle-outputs', {
      signal: controller.signal,
    })
      .then((value) => {
        if (!controller.signal.aborted) {
          setSubtitleData({ base, rows: value.outputs });
          setSubtitleError('');
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setSubtitleError('언어별 자막 파일을 불러오지 못했습니다.');
        }
      });
    return () => controller.abort();
  }, [base, revision, subtitleOutputsEnabled]);
  return (
    <section className="job-files job-results" aria-label="결과 파일">
      <h3>결과 파일</h3>
      {stale && <p role="alert">파일 목록을 다시 확인하지 못했습니다. 마지막 확인 결과입니다.</p>}
      {!stale && !outputFiles.length && (
        <p>
          {files.length
            ? '아직 생성된 출력은 없습니다. 원본·단계 입력은 아래에서 확인할 수 있습니다.'
            : '아직 출력 결과가 없습니다.'}
        </p>
      )}
      {subtitleError && <p role="alert">{subtitleError}</p>}
      <div className="job-data-filters">
        <label>
          파일 검색
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="파일·언어·단계 검색"
          />
        </label>
        <label>
          유형
          <select value={kind} onChange={(event) => setKind(event.target.value)}>
            <option value="all">전체 유형</option>
            {Object.entries(categoryLabel).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
            {[...new Set(files.map((file) => file.reference.type))].map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
            <option value="stage">파일 없는 단계</option>
          </select>
        </label>
        <label>
          단계
          <select value={stage} onChange={(event) => setStage(event.target.value)}>
            <option value="all">전체 단계</option>
            {selectedRunId && <option value="selected">선택한 실행</option>}
            {runs.map((run) => (
              <option key={run.id} value={run.id}>
                {stageLabel(run)} · {run.id.slice(0, 8)}
              </option>
            ))}
          </select>
        </label>
        <label>
          상태
          <select value={status} onChange={(event) => setStatus(event.target.value)}>
            <option value="all">전체 상태</option>
            {[
              ...new Set([
                ...runs.map((run) => runState(run)),
                ...files.map((file) => runState(file.run)),
              ]),
            ].map((value) => (
              <option key={value} value={value}>
                {statusLabel(value)}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          onClick={() => {
            setQuery('');
            setKind('all');
            setStage('all');
            setStatus('all');
          }}
        >
          필터 초기화
        </button>
      </div>
      <p className="job-data-count" role="status">
        파일 {visible.length} / {files.length}개 · 중간 파일 {intermediate.length}개 · 파일 없는
        단계 {visibleStages.length}개
      </p>
      {rows()}
      {!visible.length && !visibleStages.length && <p>조건에 맞는 파일·단계가 없습니다.</p>}
      {selected && (
        <section className="job-result-preview" ref={pane} aria-label="선택한 결과 보기">
          <div className="job-result-preview-heading">
            <h4>{selected.label}</h4>
            <button type="button" onClick={() => setPreview(null)}>
              미리보기 닫기
            </button>
          </div>
          {videoFallback === selected.key && selected.fullPreviewPath === null && (
            <p role="status">
              브라우저에서 이 입력 영상을 재생할 수 없습니다. 원본 파일을 다운로드해 확인하세요.
            </p>
          )}
          {selected.reference.type === 'video' ? (
            videoFallback === selected.key && selected.fullPreviewPath !== null ? (
              <FullVideoPreview
                resource={
                  selected.fullPreviewPath ?? artifactPath(base, selected) + '/preview/full'
                }
                showDownload={false}
              />
            ) : (
              <video
                key={previewIdentity(base, selected)}
                src={mediaUrl(artifactPath(base, selected))}
                controls
                playsInline
                preload="metadata"
                onError={() => setVideoFallback(selected.key)}
              />
            )
          ) : selected.reference.type === 'audio' ? (
            <audio
              key={previewIdentity(base, selected)}
              src={mediaUrl(artifactPath(base, selected))}
              controls
              preload="metadata"
            />
          ) : (
            <TextFilePreview
              key={previewIdentity(base, selected)}
              path={artifactPath(base, selected)}
              bytes={selected.reference.bytes}
            />
          )}
        </section>
      )}
    </section>
  );
};
