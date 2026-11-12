export type DecisionEvidence = {
  status: string;
  input_sha256?: string;
  report_sha256?: string;
  sha256?: string;
  selected_port?: string;
  conditions?: unknown;
  matches?: unknown;
  input?: unknown;
  adapter?: { id: string; revision: string; schema_version: number; paid: boolean };
  judgment?: { version: number; label: string; confidence: number; reason: string };
  code?: string;
  error_type?: string;
};

export const DecisionPanel = ({
  evidence,
  status,
}: {
  evidence?: DecisionEvidence;
  status: string;
  compact?: boolean;
}) => (
  <section className="decision-evidence" aria-label="판단 결과">
    <h4>판단 결과</h4>
    {!evidence ? (
      <p role={['failed', 'blocked', 'quarantined'].includes(status) ? 'alert' : undefined}>
        {status === 'skipped'
          ? '선택되지 않은 경로입니다. 판단은 호출되지 않았습니다.'
          : ['pending', 'queued', 'running', 'waiting'].includes(status)
            ? '판단 결과를 기다리고 있습니다.'
            : `판단 결과 기록이 없습니다. 현재 상태: ${status}. 작업 내역을 확인하세요.`}
      </p>
    ) : evidence.status === 'succeeded' ? (
      <>
        <p>
          <strong>선택 경로 {evidence.selected_port}</strong> · {evidence.judgment?.label} · 신뢰도{' '}
          {evidence.judgment?.confidence}
        </p>
        <p>{evidence.judgment?.reason}</p>
      </>
    ) : (
      <p role="alert">
        판단 {evidence.status} · {evidence.code} · {evidence.error_type}. 후속 작업이
        차단되었습니다. 다시 진행하려면 새 작업을 만드세요.
      </p>
    )}
  </section>
);
