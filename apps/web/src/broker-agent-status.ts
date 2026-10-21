export type BrokerObservation = {
  family: string;
  status: string;
  consumers: number | null;
  messages_ready: number | null;
  error_code?: string;
};

export type BrokerStatus = {
  state: string;
  consumers?: number | null;
  messages_ready?: number | null;
};

export const brokerStatusView = (status: BrokerStatus) => {
  const titles: Record<string, string> = {
    connected: 'consumer 연결됨',
    disconnected: '연결된 consumer 없음',
    unknown: '실제 연결 상태 확인 불가',
    controller: '애플리케이션 제어 노드',
    unsupported: '실행 경로 미지원',
  };
  const count = (value: number | null | undefined) =>
    typeof value === 'number' && Number.isInteger(value) && value >= 0 ? `${value}개` : '확인 불가';
  const observed = status.state === 'connected' || status.state === 'disconnected';
  return {
    title: titles[status.state] || titles.unknown,
    consumers: observed ? count(status.consumers) : '확인 불가',
    pending: observed ? count(status.messages_ready) : '확인 불가',
    canControl: false,
    notice:
      'broker가 관측한 consumer 연결 수입니다. 프로세스별 생존·추론 준비·처리 성공은 별도 확인이 필요합니다.',
  };
};
