import { mediaUrl } from './api';

export type GoalOutput = {
  name: string;
  run_id: string;
  node_id: string;
  port: string;
  type: string;
};
export const GoalResults = ({
  base,
  agents,
}: {
  base: string;
  agents: { id: string; label: string; outputs?: GoalOutput[] }[];
}) => {
  const available = agents.filter((agent) => agent.outputs?.length);
  return (
    <section className="shared-job-custody" aria-label="요청한 결과">
      <h3>요청한 결과</h3>
      {!available.length && <p>완료된 목표 결과가 아직 없습니다.</p>}
      {available.map((agent) => (
        <div key={agent.id}>
          <strong>{agent.label}</strong>
          <ul>
            {agent.outputs?.map((output) => {
              const url = mediaUrl(
                `${base}/artifacts/${encodeURIComponent(output.run_id)}/${encodeURIComponent(output.port)}`,
              );
              const label =
                (
                  {
                    subtitles: '자막 SRT',
                    sami: '자막 SAMI',
                    video: '결과 영상',
                    audio: '음성 (16kHz 모노 WAV)',
                    transcript: '전사문(JSON)',
                    report: '영상 검증 보고서(JSON)',
                  } as Record<string, string>
                )[output.name] || '결과 파일';
              return (
                <li key={output.name}>
                  <span>{label} </span>
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
        </div>
      ))}
    </section>
  );
};
