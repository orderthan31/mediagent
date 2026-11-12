import { mediaUrl } from './api';
import { GoalResults, type GoalOutput } from './GoalResults';

type FileRun = {
  id: string;
  node_id: string;
  status: string;
  result?: { outputs: Record<string, { type: string }> } | null;
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

export const JobFiles = ({
  base,
  runs,
  agents = [],
  manifest,
  stale = false,
}: {
  base: string;
  runs: FileRun[];
  agents?: { id: string; label: string; outputs?: GoalOutput[] }[];
  manifest?: { entry_count: number };
  stale?: boolean;
}) => {
  const requested = agents.flatMap((agent) => agent.outputs || []);
  const files = runs.flatMap((run) =>
    run.status === 'completed'
      ? Object.entries(run.result?.outputs || {}).map(([port, reference]) => ({
          run,
          port,
          reference,
        }))
      : [],
  );
  const other = files.filter(
    ({ run, port }) =>
      !requested.some((output) => output.run_id === run.id && output.port === port),
  );
  const hasFiles = files.length > 0 || requested.length > 0;
  return (
    <section className="shared-job-custody job-files" aria-label="결과 파일">
      <h3>결과 파일</h3>
      {stale && <p role="alert">파일 목록을 다시 확인하지 못했습니다. 마지막 확인 결과입니다.</p>}
      {!stale && !hasFiles && !manifest?.entry_count && <p>아직 출력 결과가 없습니다.</p>}
      {!!manifest?.entry_count && (
        <a href={mediaUrl(base + '/manifest?download=true')} download>
          파일 목록(JSON) 받기
        </a>
      )}
      {!!requested.length && <GoalResults base={base} agents={agents} />}
      {!!other.length && (
        <ul>
          {other.map(({ run, port, reference }) => {
            const label = outputLabel(port, reference.type);
            const url = mediaUrl(
              `${base}/artifacts/${encodeURIComponent(run.id)}/${encodeURIComponent(port)}`,
            );
            return (
              <li key={`${run.id}:${port}`}>
                <span>{label}</span>
                {' · '}
                <a href={url} target="_blank" rel="noreferrer">
                  보기
                </a>
                {' · '}
                <a href={url + '?download=true'} download>
                  {label} 받기
                </a>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
};
