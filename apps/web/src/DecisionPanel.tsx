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
}) => (
  <section className="decision-evidence" aria-label="서버 고정 AI 판단 근거">
    <h4>서버 고정 AI 판단 근거</h4>
    {!evidence ? (
      <p>
        {status === 'skipped'
          ? '상위 경로 미선택 · 판단 호출 없음'
          : '판단 전 미확정 · 미선택 skipped/비용0이 아닙니다.'}
      </p>
    ) : evidence.status === 'succeeded' ? (
      <>
        <p>
          <strong>선택 경로 {evidence.selected_port}</strong> · {evidence.judgment?.label} ·
          confidence {evidence.judgment?.confidence}
        </p>
        <p>{evidence.judgment?.reason}</p>
        <p>
          adapter {evidence.adapter?.id} / revision {evidence.adapter?.revision} · schema{' '}
          {evidence.adapter?.schema_version}
        </p>
        <p>입력 SHA {evidence.input_sha256}</p>
        <p>판단 결과 SHA {evidence.report_sha256}</p>
        <p>조건/선택 고정 SHA {evidence.sha256}</p>
        <p>
          성공 판단은 재열기·검수 뒤에도 재호출하지 않습니다. 라벨은 실행 명령이 아닙니다. 경로는
          재선택하지 않고 새 계획/비용 확인 후 별도 이어실행합니다.
        </p>
        <details>
          <summary>적용 조건 · 일치 결과 · 입력 참조</summary>
          <pre>
            {JSON.stringify(
              { conditions: evidence.conditions, matches: evidence.matches, input: evidence.input },
              null,
              2,
            )}
          </pre>
        </details>
      </>
    ) : (
      <p role="alert">
        판단 {evidence.status} · {evidence.code} · {evidence.error_type}. 정상 미선택이 아닙니다.
        영향 후행은 차단하며 독립 결과를 보존합니다. 재판정/복구는 새 티켓으로 분리하세요.
      </p>
    )}
  </section>
);
