import type { AgentRuntime } from './AgentOperations';
import { brokerStatusView } from './broker-agent-status';

export const BrokerAgentStatus = ({
  runtime,
  error,
}: {
  runtime: AgentRuntime | null;
  error: string;
}) => {
  const view = brokerStatusView(runtime ?? { state: 'unknown' });
  return (
    <section className="agent-operations" role="region" aria-label="독립 에이전트 관측">
      <h2>운영 관리</h2>
      {error && (
        <p className="alert" role="alert">
          {error}
        </p>
      )}
      <p role="status">{view.title}</p>
      <dl className="agent-operation-facts">
        <div>
          <dt>실행 경로</dt>
          <dd>
            {runtime?.runtime === 'application_controller'
              ? '애플리케이션 제어'
              : '독립 AMQP consumer'}
          </dd>
        </div>
        <div>
          <dt>연결된 consumer</dt>
          <dd>{view.consumers}</dd>
        </div>
        <div>
          <dt>큐 대기 메시지</dt>
          <dd>{view.pending}</dd>
        </div>
        <div>
          <dt>등록된 실행 기록</dt>
          <dd>
            유효 lease 처리 중 {runtime?.activity?.running ?? '확인 불가'}개 · 만료 lease{' '}
            {runtime?.activity?.expired ?? '확인 불가'}개 · 누적 완료{' '}
            {runtime?.activity?.completed ?? '확인 불가'}개
          </dd>
        </div>
        <div>
          <dt>관측 시각</dt>
          <dd>
            {runtime?.observed_at ? new Date(runtime.observed_at).toLocaleString() : '확인 불가'}
          </dd>
        </div>
      </dl>
      <p>{view.notice}</p>
      <p>
        실행 기록은 DB의 해당 종류 전체 집계이며, 특정 worker가 지금 처리 중이라는 증거는 아닙니다.
      </p>
      {runtime?.observations && runtime.observations.length > 0 && (
        <ul aria-label="전송 경로별 관측">
          {runtime.observations.map((observation) => (
            <li key={observation.family}>
              {observation.family === 'cpu' ? 'CPU 경로' : '모델·GPU 경로'}:{' '}
              {observation.status === 'observed'
                ? `consumer ${observation.consumers}개 · 대기 ${observation.messages_ready}개`
                : observation.error_code === 'broker_observation_forbidden'
                  ? '관측 권한 부족 · 실제 연결 상태 확인 불가'
                  : '조회 실패 · 실제 연결 상태 확인 불가'}
            </li>
          ))}
        </ul>
      )}
      {runtime?.unavailable_reason && <p>{runtime.unavailable_reason}</p>}
      <p>원격 제어가 연결되지 않아 활성화·중지·개수 변경 기능은 제공하지 않습니다.</p>
    </section>
  );
};
