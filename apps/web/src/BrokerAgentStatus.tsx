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
          <dt>{runtime?.telemetry ? '상태 수집 경로' : '연결된 consumer'}</dt>
          <dd>
            {runtime?.telemetry
              ? runtime.collector?.healthy
                ? '상태 수신 중'
                : '관측 불가'
              : view.consumers}
          </dd>
        </div>
        <div>
          <dt>{runtime?.telemetry ? '등록 worker' : '큐 대기 메시지'}</dt>
          <dd>{runtime?.telemetry ? `${runtime.workers?.length ?? 0}개` : view.pending}</dd>
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
      {runtime?.telemetry && (
        <>
          <p>
            마지막 상태 수신 후 {runtime.ttl_seconds}초가 지나면 응답 끊김으로 표시합니다. 수집 경로
            자체가 끊기면 관측 불가입니다.
          </p>
          <div
            className="agent-instance-scroll"
            role="region"
            aria-label="실제 worker 상태"
            tabIndex={0}
          >
            <table>
              <thead>
                <tr>
                  <th>worker / 기능</th>
                  <th>상태</th>
                  <th>마지막 heartbeat 수신</th>
                  <th>현재 티켓 / 노드 / attempt</th>
                  <th>최근 상태 변화</th>
                </tr>
              </thead>
              <tbody>
                {runtime.workers?.map((worker) => (
                  <tr
                    key={worker.worker_id}
                    data-worker-id={worker.worker_id}
                    data-worker-state={worker.state}
                  >
                    <td>
                      <code title={worker.worker_id}>{worker.worker_id.slice(0, 8)}</code>
                      <br />
                      {worker.family} · {worker.role}
                      <br />
                      <small title={worker.boot_id}>boot {worker.boot_id.slice(-8)}</small>
                    </td>
                    <td>{brokerStatusView({ state: worker.state, telemetry: true }).title}</td>
                    <td title={worker.received_at}>
                      {new Date(worker.received_at).toLocaleString()}
                    </td>
                    <td>
                      {worker.ticket_id ? (
                        <>
                          <a href={`#/jobs/${worker.ticket_id}`}>
                            #{worker.ticket_number ?? worker.ticket_id.slice(0, 8)}
                          </a>
                          <br />
                          {worker.node_id ?? '노드 대조 미확인'}
                          <br />
                          <code title={worker.attempt_id ?? ''}>
                            {worker.attempt_id?.slice(0, 8)}
                          </code>
                        </>
                      ) : (
                        '대기 중 / 할당 없음'
                      )}
                    </td>
                    <td>
                      {[...worker.recent_events]
                        .reverse()
                        .map(
                          (event) =>
                            `${brokerStatusView({ state: event.state, telemetry: true }).title}${event.ticket_number ? ` (#${event.ticket_number}/${event.node_id ?? '?'})` : ''}`,
                        )
                        .join(' → ')}
                    </td>
                  </tr>
                ))}
                {!runtime.workers?.length && (
                  <tr>
                    <td colSpan={5}>아직 상태 보고를 수신한 worker가 없습니다.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
      <p>원격 제어가 연결되지 않아 활성화·중지·개수 변경 기능은 제공하지 않습니다.</p>
    </section>
  );
};
