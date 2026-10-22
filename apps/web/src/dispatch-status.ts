export const dispatchLabel = (status: string, phase?: string): string | null => {
  if (!['waiting', 'running'].includes(status)) {
    return null;
  }
  const labels: Record<string, string> = {
    pending: '에이전트 시작 대기',
    sending: '전송 중',
    sent: '전송됨 · 수신 확인 대기',
    received: '처리 중',
    unknown: '전송 결과 확인 필요',
  };
  return phase ? (labels[phase] ?? null) : null;
};
