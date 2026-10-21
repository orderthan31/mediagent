export type BrokerObservation = {
  family: string;
  status: string;
  consumers: number | null;
  messages_ready: number | null;
  error_code?: string;
};

export type BrokerStatus = {
  state: string;
  telemetry?: boolean;
  consumers?: number | null;
  messages_ready?: number | null;
};

export const brokerStatusView = (status: BrokerStatus) => {
  const titles: Record<string, string> = {
    connected: '연결됨',
    disconnected: '연결 끊김',
    unknown: '확인 불가',
    controller: '확인 불가',
    unsupported: '확인 불가',
    failed: '오류',
    error: '오류',
  };
  const count = (value: number | null | undefined) =>
    typeof value === 'number' && Number.isInteger(value) && value >= 0 ? `${value}개` : '확인 불가';
  const observed = status.state === 'connected' || status.state === 'disconnected';
  return {
    title: status.telemetry
      ? (
          {
            connected: '정상',
            ready: '정상',
            busy: '처리 중',
            stopping: '중지 중',
            stopped: '중지',
            heartbeat_lost: '연결 끊김',
            unknown: '확인 불가',
            failed: '오류',
            error: '오류',
          } as Record<string, string>
        )[status.state] || '확인 불가'
      : titles[status.state] || titles.unknown,
    consumers: observed ? count(status.consumers) : '확인 불가',
    pending: observed ? count(status.messages_ready) : '확인 불가',
    canControl: false,
  };
};
