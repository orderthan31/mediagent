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
  result?: { outputs: Record<string, FileRef> } | null;
};
type ResultFile = {
  run: FileRun;
  port: string;
  reference: FileRef;
  label: string;
  key: string;
  path?: string;
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
    main.map((file) => contentKey(file.reference)).filter((key) => key !== null),
  );
  const intermediate = files.filter((file) => {
    const content = contentKey(file.reference);
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

export const JobFiles = ({
  base,
  runs,
  agents = [],
  stale = false,
  subtitleOutputsEnabled = false,
  revision = 0,
}: {
  base: string;
  runs: FileRun[];
  agents?: { id: string; label: string; outputs?: GoalOutput[] }[];
  manifest?: { entry_count: number };
  stale?: boolean;
  subtitleOutputsEnabled?: boolean;
  revision?: number;
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
          status: 'completed',
          result: null,
        };
        return {
          run,
          port: extension,
          reference: file.reference,
          label: `${track.language} · ${extension.toUpperCase()}`,
          key: fileKey(run, `${name}:${extension}`, file.reference),
          path: `${base}/subtitle-outputs/${encodeURIComponent(output.run_id)}/${encodeURIComponent(name)}/${encodeURIComponent(extension)}`,
          copySource: jobId ? trackSrtSource(jobId, output.run_id, name, extension, file) : null,
        };
      }),
    ),
  );
  const subtitleContent = new Set(
    subtitleFiles.map((file) => contentKey(file.reference)).filter((key) => key !== null),
  );
  // A named language/format is a distinct requested result even if its bytes
  // happen to match another track. Only canonical-route aliases are collapsed.
  const main = unique([...collected.main, ...subtitleFiles]);
  const intermediate = unique(
    collected.intermediate.filter((file) => {
      const content = contentKey(file.reference);
      return content === null || !subtitleContent.has(content);
    }),
    new Set(main.map((file) => file.key)),
  );
  const [preview, setPreview] = useState<{ base: string; key: string } | null>(null);
  const [videoFallback, setVideoFallback] = useState('');
  const pane = useRef<HTMLElement>(null);
  const selected =
    preview?.base === base
      ? [...main, ...intermediate].find((file) => file.key === preview.key)
      : undefined;
  const rows = (files: ResultFile[]) => (
    <ul className="job-result-list">
      {files.map((file) => (
        <li key={file.key} data-result-key={file.key}>
          <span>{file.label}</span>
          <div>
            <button
              type="button"
              aria-label={`${file.label} 보기`}
              onClick={() => {
                setPreview({ base, key: file.key });
                setVideoFallback('');
                requestAnimationFrame(() => pane.current?.scrollIntoView({ block: 'nearest' }));
              }}
            >
              보기
            </button>
            <a
              href={mediaUrl(artifactPath(base, file) + '?download=true')}
              download
              aria-label={`${file.label} 다운로드`}
            >
              다운로드
            </a>
            <SrtCopyAction
              source={
                file.copySource === undefined
                  ? artifactSrtSource(base, file.run, file.port)
                  : file.copySource
              }
            />
          </div>
        </li>
      ))}
    </ul>
  );
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
      {!stale && !main.length && <p>아직 출력 결과가 없습니다.</p>}
      {subtitleError && <p role="alert">{subtitleError}</p>}
      {rows(main)}
      {!!intermediate.length && (
        <details className="job-intermediate-files">
          <summary>중간 파일 {intermediate.length}개</summary>
          {rows(intermediate)}
        </details>
      )}
      {selected && (
        <section className="job-result-preview" ref={pane} aria-label="선택한 결과 보기">
          <div className="job-result-preview-heading">
            <h4>{selected.label}</h4>
            <button type="button" onClick={() => setPreview(null)}>
              미리보기 닫기
            </button>
          </div>
          {selected.reference.type === 'video' ? (
            videoFallback === selected.key ? (
              <FullVideoPreview
                resource={artifactPath(base, selected) + '/preview/full'}
                showDownload={false}
              />
            ) : (
              <video
                key={selected.key}
                src={mediaUrl(artifactPath(base, selected))}
                controls
                playsInline
                preload="metadata"
                onError={() => setVideoFallback(selected.key)}
              />
            )
          ) : selected.reference.type === 'audio' ? (
            <audio
              key={selected.key}
              src={mediaUrl(artifactPath(base, selected))}
              controls
              preload="metadata"
            />
          ) : (
            <TextFilePreview
              key={selected.key}
              path={artifactPath(base, selected)}
              bytes={selected.reference.bytes}
            />
          )}
        </section>
      )}
    </section>
  );
};
