import type { AgentRuntime } from './AgentOperations';
import { brokerStatusView } from './broker-agent-status';
import { InstanceIdentity } from './InstanceIdentity';

export const BrokerAgentStatus = ({
  runtime,
  error,
}: {
  runtime: AgentRuntime | null;
  error: string;
}) => {
  const current = error ? null : runtime;
  const state = current?.state ?? 'unknown';
  const view = brokerStatusView(current ?? { state: 'unknown' });
  const agents = (runtime?.workers ?? []).map((agent) =>
    error || !current?.collector?.healthy
      ? { ...agent, state: 'unknown', ticket_id: null, ticket_number: null }
      : agent,
  );
  const known = Boolean(
    current?.telemetry &&
    current.collector?.healthy &&
    agents.length &&
    agents.every((agent) => !['unknown', 'heartbeat_lost'].includes(agent.state)),
  );
  const active = agents.filter((agent) =>
    ['connected', 'ready', 'busy', 'stopping'].includes(agent.state),
  );
  const working = current?.collector?.healthy
    ? agents.filter((agent) => agent.state === 'busy' && agent.ticket_id)
    : [];
  const responses = agents.map((agent) => Date.parse(agent.received_at)).filter(Number.isFinite);
  const latestResponse = responses.length ? Math.max(...responses) : null;
  return (
    <section className="agent-operations" role="region" aria-label="에이전트 현황">
      <h2>실행 현황</h2>
      <span className="agent-status-badge" data-state={state} role="status">
        {view.title}
      </span>
      <dl className="agent-operation-facts">
        <div>
          <dt>실행 중</dt>
          <dd>{known ? `${active.length}개` : '확인 불가'}</dd>
        </div>
        <div>
          <dt>현재 작업</dt>
          <dd>
            {working.length
              ? working.map((agent, index) => (
                  <span key={agent.worker_id}>
                    {index > 0 && ' · '}
                    <a href={`#/jobs/${agent.ticket_id}`}>
                      #{agent.ticket_number ?? agent.ticket_id?.slice(0, 8)}
                    </a>
                  </span>
                ))
              : known
                ? '없음'
                : '확인 불가'}
          </dd>
        </div>
        <div>
          <dt>최근 응답</dt>
          <dd>
            {latestResponse !== null ? new Date(latestResponse).toLocaleString() : '확인 불가'}
          </dd>
        </div>
      </dl>
      {agents.length > 0 && (
        <div
          className="agent-instance-scroll"
          role="region"
          aria-label="에이전트별 현황"
          tabIndex={0}
        >
          <table>
            <thead>
              <tr>
                <th>실행 ID</th>
                <th>상태</th>
                <th>현재 작업</th>
                <th>최근 응답</th>
              </tr>
            </thead>
            <tbody>
              {agents.map((agent) => (
                <tr
                  key={agent.worker_id}
                  data-worker-id={agent.worker_id}
                  data-worker-state={agent.state}
                >
                  <td>
                    <InstanceIdentity id={agent.worker_id} />
                  </td>
                  <td>
                    <span className="agent-status-badge" data-state={agent.state}>
                      {brokerStatusView({ state: agent.state, telemetry: true }).title}
                    </span>
                  </td>
                  <td>
                    {agent.state === 'busy' && agent.ticket_id ? (
                      <a href={`#/jobs/${agent.ticket_id}`}>
                        #{agent.ticket_number ?? agent.ticket_id.slice(0, 8)}
                      </a>
                    ) : ['unknown', 'heartbeat_lost'].includes(agent.state) ? (
                      '확인 불가'
                    ) : (
                      '없음'
                    )}
                  </td>
                  <td>{new Date(agent.received_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
};
