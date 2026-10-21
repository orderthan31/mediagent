import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { ApiError, mediaUrl, request, type Job } from './api';
import { LoadingSkeleton } from './LoadingSkeleton';
import { WorkflowCanvas, type CanvasSpec } from './WorkflowCanvas';
import { GenericJobReview } from './GenericJobReview';
import { frontendOnly } from './preview';
import { Button } from './hangyeol/primitives/button';
import {
  executionGraph,
  legacyExecution,
  runLabels,
  type JobExecution,
  type JobPreview,
  type ExecutionArtifact,
} from './job-execution';
import './job-execution.css';

const safeArtifactUrl = (path?: string) => {
  if (!path || !path.startsWith('/') || path.startsWith('//') || path.includes('\\'))
    return undefined;
  const parsed = new URL(path, location.origin);
  if (parsed.origin !== location.origin || !/^\/(jobs|videos|artifacts)\//.test(parsed.pathname))
    return undefined;
  return mediaUrl(parsed.pathname + parsed.search);
};
const stamp = (seconds: number) =>
  new Date(Math.max(0, seconds) * 1000).toISOString().slice(11, 19);
const Artifact = ({
  artifact,
  onEdit,
  videoActions,
}: {
  artifact: ExecutionArtifact;
  onEdit?: (track: 'original' | 'translated') => void;
  videoActions?: ReactNode;
}) => {
  const [query, setQuery] = useState('');
  const [failed, setFailed] = useState(false);
  const url = safeArtifactUrl(artifact.url);
  const cues = artifact.cues?.filter((cue) =>
    cue.text.toLocaleLowerCase().includes(query.toLocaleLowerCase()),
  );
  return (
    <section className="execution-artifact" data-artifact-type={artifact.type}>
      <div className="execution-artifact-heading">
        <h4>{artifact.label}</h4>
        <span>
          {artifact.type}
          {artifact.partial ? ' · 일부 결과' : ''}
        </span>
      </div>
      {artifact.expired ? (
        <p>자료 보관 기간이 만료되었습니다.</p>
      ) : (
        <>
          {artifact.type === 'video' && url ? (
            <>
              <video
                controls
                playsInline
                preload="metadata"
                src={url}
                onError={() => setFailed(true)}
              />
              {artifact.final && videoActions}
            </>
          ) : artifact.type === 'audio' && url ? (
            <audio controls preload="none" src={url} onError={() => setFailed(true)} />
          ) : artifact.type === 'image' && url ? (
            <img src={url} alt={artifact.label} onError={() => setFailed(true)} />
          ) : artifact.cues ? (
            <>
              <input
                type="search"
                aria-label={`${artifact.label} 검색`}
                placeholder="결과에서 검색"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
              <ol className="execution-cues">
                {cues?.map((cue, index) => (
                  <li key={`${cue.start}-${index}`}>
                    <time>
                      {stamp(cue.start)}–{stamp(cue.end)}
                    </time>
                    <p>{cue.text}</p>
                  </li>
                ))}
              </ol>
              {!cues?.length && <p>{query ? '검색 결과 없음' : '저장된 구간 없음'}</p>}
            </>
          ) : artifact.text !== undefined ? (
            <pre>{artifact.text}</pre>
          ) : artifact.data !== undefined ? (
            <pre>{JSON.stringify(artifact.data, null, 2)}</pre>
          ) : (
            <p>미리보기 미지원 자료입니다.</p>
          )}
          {failed && (
            <p role="alert">자료를 표시하지 못했습니다. 연결 상태와 파일 형식을 확인해 주세요.</p>
          )}
          <div className="execution-artifact-actions">
            {url && (
              <a href={url} download={frontendOnly ? artifact.label : undefined}>
                자료 다운로드
              </a>
            )}
            {onEdit && artifact.track && (
              <Button variant="quiet" onClick={() => onEdit(artifact.track!)}>
                자막 수정
              </Button>
            )}
          </div>
        </>
      )}
    </section>
  );
};
export const JobExecutionCanvas = ({
  job,
  preview,
  onEdit,
  videoActions,
  renderNodeActions,
}: {
  job: Job;
  preview: JobPreview | null;
  onEdit: (track: 'original' | 'translated') => void;
  videoActions?: ReactNode;
  renderNodeActions?: (type: string) => ReactNode;
}) => {
  const [execution, setExecution] = useState<JobExecution | null>(null);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState('');
  const [runId, setRunId] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        let result: JobExecution;
        try {
          result = await request<JobExecution>(`/jobs/${job.job_id}/execution`, {
            signal: controller.signal,
          });
          if (result.version !== 1 || result.job_id !== job.job_id)
            throw new Error('작업 실행 기록 형식이 일치하지 않습니다.');
        } catch (reason) {
          if (frontendOnly || !(reason instanceof ApiError) || ![404, 501].includes(reason.status))
            throw reason;
          const catalog = await request<{ nodes: CanvasSpec[] }>('/settings/node-catalog', {
            signal: controller.signal,
          });
          result = legacyExecution(job, preview, catalog.nodes);
        }
        if (!controller.signal.aborted) {
          setExecution(result);
          setError('');
        }
      } catch (reason) {
        if (!controller.signal.aborted)
          setError(reason instanceof Error ? reason.message : '실행 기록 조회 실패');
      }
    })();
    return () => controller.abort();
  }, [job, preview]);
  const graph = useMemo(() => (execution ? executionGraph(execution) : null), [execution]);
  const node = execution?.definition.nodes.find((node) => node.id === selected);
  const runs = execution?.runs.filter((run) => run.node_id === selected) || [];
  const run = runs.find((run) => run.id === runId) || runs[runs.length - 1];
  const artifacts =
    selected === '$input'
      ? execution?.inputs || []
      : selected === '$output'
        ? execution?.outputs || []
        : run?.status === 'quarantined'
          ? []
          : run?.outputs || [];
  const terminal = selected === '$input' || selected === '$output';

  const currentRuns = new Map<string, typeof run>();
  execution?.runs.forEach((run) => currentRuns.set(run.node_id, run));
  const states = Object.fromEntries(
    [...currentRuns]
      .filter(([, run]) => !!run)
      .map(([id, run]) => [
        id,
        { label: runLabels[run!.status] || run!.status, state: run!.status },
      ]),
  );
  const details = (
    <div className="execution-node-body" data-selected-node={selected}>
      {!terminal && (
        <>
          {runs.length > 1 && (
            <label>
              실행 기록
              <select
                aria-label="노드 실행 기록"
                value={run?.id || ''}
                onChange={(event) => setRunId(event.target.value)}
              >
                {runs.map((row) => (
                  <option key={row.id} value={row.id}>
                    반복 {row.iteration} · 시도 {row.attempt} · 세대 {row.generation} ·{' '}
                    {runLabels[row.status] || row.status}
                  </option>
                ))}
              </select>
            </label>
          )}
          {run ? (
            <>
              <dl className="execution-facts">
                <div>
                  <dt>상태</dt>
                  <dd>{runLabels[run.status] || run.status}</dd>
                </div>
                <div>
                  <dt>실행</dt>
                  <dd>
                    반복 {run.iteration} · 시도 {run.attempt} · 세대 {run.generation}
                  </dd>
                </div>
                {run.started_at && (
                  <div>
                    <dt>시작</dt>
                    <dd>{new Date(run.started_at).toLocaleString('ko-KR')}</dd>
                  </div>
                )}
                {run.completed_at && (
                  <div>
                    <dt>완료</dt>
                    <dd>{new Date(run.completed_at).toLocaleString('ko-KR')}</dd>
                  </div>
                )}
                {run.duration_seconds !== undefined && (
                  <div>
                    <dt>처리 시간</dt>
                    <dd>{run.duration_seconds}초</dd>
                  </div>
                )}
                {run.progress !== undefined && (
                  <div>
                    <dt>진행률</dt>
                    <dd>{Math.round(run.progress * 100)}%</dd>
                  </div>
                )}
                {run.model && (
                  <div>
                    <dt>사용 모델</dt>
                    <dd>
                      {run.model.name} · {run.model.provider}/{run.model.model} · r
                      {run.model.revision}
                    </dd>
                  </div>
                )}
              </dl>
              {run.error && (
                <p className="alert" role="alert">
                  {run.error.code} · {run.error.message}
                </p>
              )}
              <details className="execution-settings">
                <summary>실제 적용 설정</summary>
                {run.settings === null ? (
                  <p>적용 설정 기록 미제공</p>
                ) : (
                  <pre>{JSON.stringify(run.settings, null, 2)}</pre>
                )}
              </details>
              <details>
                <summary>입력 자료 · {run.inputs.length}</summary>
                {run.inputs.map((item) => (
                  <Artifact key={item.id} artifact={item} />
                ))}
              </details>
              {!!run.events?.length && (
                <details>
                  <summary>실행 이력</summary>
                  <ol className="execution-events">
                    {run.events.map((event, index) => (
                      <li key={index}>
                        <time>{new Date(event.at).toLocaleTimeString('ko-KR')}</time>
                        {event.message}
                      </li>
                    ))}
                  </ol>
                </details>
              )}
            </>
          ) : (
            <p>이 노드의 개별 실행 기록은 아직 제공되지 않았습니다.</p>
          )}
          {node && renderNodeActions?.(node.type)}
        </>
      )}
      {run?.status === 'quarantined' && (
        <p role="status">격리된 결과입니다. 정상 완료 결과로 표시하지 않습니다.</p>
      )}
      {!!artifacts.length ? (
        <div className="execution-artifacts">
          {artifacts.map((item) => (
            <Artifact
              key={item.id}
              artifact={item}
              onEdit={job.status === 'COMPLETED' && !item.partial ? onEdit : undefined}
              videoActions={videoActions}
            />
          ))}
        </div>
      ) : (
        <p>
          {selected === '$output'
            ? '아직 생성된 최종 결과가 없습니다.'
            : selected === '$input'
              ? '입력 자료가 없습니다.'
              : '아직 생성된 출력 자료가 없습니다.'}
        </p>
      )}
      {frontendOnly && run?.status === 'review_required' && (
        <GenericJobReview key={selected} jobId={job.job_id} nodeId={selected} />
      )}
    </div>
  );
  return (
    <section className="job-execution" aria-label="요청된 처리 흐름">
      <div className="execution-heading">
        <h2>요청된 처리 흐름</h2>
        {execution && (
          <span>
            {execution.definition.name} · r{execution.definition.revision}
            {execution.source === 'fixture' ? ' · 목업' : ''}
          </span>
        )}
      </div>
      {error && (
        <p role="alert" className="alert">
          {error}
          {execution ? ' · 이전 조회값을 표시 중입니다.' : ''}
        </p>
      )}
      {execution?.notice && <p className="execution-notice">{execution.notice}</p>}
      {graph ? (
        <WorkflowCanvas
          key={job.job_id}
          definition={graph.definition}
          catalog={graph.catalog}
          onSelect={(id) => {
            setSelected(id);
            setRunId('');
          }}
          nodeStates={states}
          detailsLabel="노드 실행 상세"
          details={details}
        />
      ) : (
        !error && <LoadingSkeleton layout="canvas" label="처리 흐름 불러오는 중" />
      )}
    </section>
  );
};
