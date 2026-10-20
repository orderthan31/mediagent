import { useEffect, useState } from 'react';
import { request } from './api';
import { PageTitle } from './PageTitle';

type RecordRow = {
  namespace: string;
  record_id: string;
  internal: boolean;
  legacy_state: string | null;
  payload: Record<string, unknown>;
  artifact_references: { path: string; bytes: number; sha256?: string }[];
};
export const LegacyArchivePage = () => {
  const [kind, setKind] = useState('job');
  const [rows, setRows] = useState<RecordRow[]>([]),
    [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true),
    [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError('');
    setRows([]);
    request<{ records: RecordRow[]; total: number }>(
      '/legacy/history?kind=' + kind + '&limit=200',
      { signal: controller.signal },
    )
      .then((value) => {
        if (!controller.signal.aborted) {
          setRows(value.records);
          setTotal(value.total);
        }
      })
      .catch((reason) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : '이력 조회 실패');
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [kind]);
  return (
    <main className="ui02-catalog">
      <PageTitle>이관된 구버전 이력</PageTitle>
      <div className="ui02-page-heading">
        <span>legacy/unassigned · 관리자 전용 · 읽기 전용</span>
      </div>
      <label>
        기록 종류
        <select
          aria-label="구버전 기록 종류"
          value={kind}
          onChange={(event) => setKind(event.target.value)}
        >
          <option value="job">작업</option>
          <option value="asset">자산</option>
          <option value="workflow">워크플로우 원문</option>
          <option value="settings">비활성 설정</option>
          <option value="index">namespace별 원본 인덱스</option>
        </select>
      </label>
      {error && (
        <p role="alert" className="alert">
          {error}
        </p>
      )}
      {loading ? (
        <p role="status">불러오는 중</p>
      ) : (
        <>
          <p>{total}개</p>
          <div className="ui02-list">
            {rows.map((row) => (
              <article className="ui02-list-item" key={row.namespace + row.record_id}>
                <div className="ui02-list-copy">
                  <h2 className="ui02-list-title">
                    {String(row.payload.original_filename || row.payload.name || row.record_id)}
                  </h2>
                  <p className="ui02-list-meta">
                    {row.legacy_state || '보존'} · {row.internal ? '내부 기록' : '미배정 기록'} ·{' '}
                    {row.namespace}
                  </p>
                  <details>
                    <summary>보존 정보 · 참조 파일 {row.artifact_references.length}개</summary>
                    <pre
                      style={{
                        whiteSpace: 'pre-wrap',
                        overflowWrap: 'anywhere',
                        fontSize: 'var(--text-g-small)',
                      }}
                    >
                      {JSON.stringify(row.payload, null, 2)}
                    </pre>
                    {row.artifact_references.map((reference) => (
                      <p key={reference.path}>
                        {reference.path} · {reference.bytes} bytes
                        {reference.sha256 && (
                          <>
                            <br />
                            <code>{reference.sha256}</code>
                          </>
                        )}
                      </p>
                    ))}
                  </details>
                </div>
              </article>
            ))}
          </div>
        </>
      )}
      <a className="ui02-text-action" href="#/settings">
        시스템으로 돌아가기
      </a>
    </main>
  );
};
