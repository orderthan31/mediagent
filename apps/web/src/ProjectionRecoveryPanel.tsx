import { useCallback, useEffect, useRef, useState } from 'react';
import { request, mediaUrl } from './api';
import { jsonPost } from './video-api';
import { Button } from './hangyeol/primitives/button';
import './projection-recovery.css';

type Ref = { sha256: string; bytes: number; type: string };
type Binding = {
  source_run_id: string;
  policy: string;
  packed_transcript: Ref;
  clock: Ref;
  audio: Ref;
  projector_sha256: string;
  accepted_result_sha256: string;
  source_result_sha256: string;
  segment_count?: number;
  expected_outputs?: Record<string, { sha256: string; bytes: number }>;
};
type Operation = {
  id: string;
  status: 'prepared' | 'running' | 'completed' | 'held';
  context_sha256: string;
  binding: Binding;
  outputs?: Record<string, Ref>;
};
type Listing = {
  can_manage: boolean;
  candidates: { source_run_id: string; eligible: boolean; binding?: Binding; reason?: string }[];
  operations: Operation[];
};
const labels = {
  prepared: '확인 준비됨',
  running: '결과 확인 필요 · 재실행 금지',
  completed: '복구 파일 생성 완료',
  held: '확인 보류 · 재실행 금지',
};
const terminal = (row: Operation) => ['completed', 'held'].includes(row.status);
const keepTerminal = (old: Operation | null, next: Operation) =>
  old?.id === next.id && terminal(old) ? old : next;

export const ProjectionRecoveryPanel = ({ jobId }: { jobId: string }) => {
  const [data, setData] = useState<Listing | null>(null);
  const [sourceId, setSourceId] = useState('');
  const [policy, setPolicy] = useState('');
  const [preview, setPreview] = useState<Operation | null>(null);
  const [ack, setAck] = useState(false);
  const [busy, setBusy] = useState(false);
  const [fresh, setFresh] = useState(false);
  const [error, setError] = useState('');
  const sequence = useRef(0);
  const base = '/renewal/jobs/' + jobId + '/projection-recoveries';
  const load = useCallback(async () => {
    const token = ++sequence.current;
    try {
      const next = await request<Listing>(base);
      if (token !== sequence.current) {
        return;
      }
      setData((old) => ({
        ...next,
        operations: next.operations.map((row) =>
          keepTerminal(old?.operations.find((item) => item.id === row.id) || null, row),
        ),
      }));
      setPreview((old) =>
        old ? keepTerminal(old, next.operations.find((row) => row.id === old.id) || old) : null,
      );
      setFresh(true);
      setError('');
    } catch (reason) {
      if (token !== sequence.current) {
        return;
      }
      setFresh(false);
      setError(reason instanceof Error ? reason.message : '복구 기록 조회 실패');
    }
  }, [base]);
  const candidate = data?.candidates.find((row) => row.source_run_id === sourceId);
  const binding = preview?.binding || candidate?.binding;
  useEffect(() => {
    void load();
    return () => {
      sequence.current++;
    };
  }, [load]);
  if (data && data.candidates.length === 0 && data.operations.length === 0) {
    return null;
  }
  return (
    <section className="ticket-panel projection-recovery" aria-label="보존된 전사 재투영">
      <h2>보존된 전사 복구 · 재투영</h2>
      <p>
        새 모델 호출 없이 저장된 전사와 원래 clock으로 별도 복구 파일을 만듭니다. 원 작업은 실패
        상태와 기록을 그대로 유지하고 번역·영상 처리는 시작하지 않습니다.
      </p>
      {error && (
        <p role="alert">{error} 이전 기록은 최신 확인값이 아닙니다. 상태를 다시 조회하세요.</p>
      )}
      <Button variant="secondary" disabled={busy} onClick={() => void load()}>
        복구 기록 새로고침
      </Button>
      {data && (
        <>
          <label>
            보존된 전사 실행
            <select
              value={sourceId}
              disabled={busy}
              onChange={(event) => {
                setSourceId(event.target.value);
                setPolicy('');
                setPreview(null);
                setAck(false);
              }}
            >
              <option value="">실행 선택</option>
              {data.candidates.map((row) => (
                <option key={row.source_run_id} value={row.source_run_id} disabled={!row.eligible}>
                  {row.source_run_id}
                  {row.eligible ? '' : ' · 확인 보류'}
                </option>
              ))}
            </select>
          </label>
          {data.candidates
            .filter((row) => !row.eligible)
            .map((row) => (
              <p key={row.source_run_id}>{row.reason}</p>
            ))}
          {candidate?.binding && (
            <label>
              원래 재투영 정책
              <select
                value={policy}
                disabled={busy}
                onChange={(event) => {
                  setPolicy(event.target.value);
                  setPreview(null);
                  setAck(false);
                }}
              >
                <option value="">원래 정책 확인 후 선택</option>
                <option value={candidate.binding.policy}>{candidate.binding.policy}</option>
              </select>
            </label>
          )}
          {binding && (
            <>
              <p>
                {preview
                  ? '실제 자료와 SHA를 검증한 미리보기'
                  : '저장된 참조 · 아직 실제 자료 검증 전'}
              </p>
              <dl>
                {(['packed_transcript', 'clock', 'audio'] as const).map((key) => (
                  <div key={key}>
                    <dt>
                      {
                        {
                          packed_transcript: '보존된 packed 전사',
                          clock: '원래 clock',
                          audio: '전사에 사용한 packed 오디오',
                        }[key]
                      }
                    </dt>
                    <dd>
                      <code>{binding[key].sha256}</code> · {binding[key].bytes.toLocaleString()}{' '}
                      bytes ·{' '}
                      <a href={mediaUrl(base + '/sources/' + binding.source_run_id + '/' + key)}>
                        자료 다운로드
                      </a>
                    </dd>
                  </div>
                ))}
                <div>
                  <dt>원래 실패 기록 SHA</dt>
                  <dd>
                    <code>{binding.source_result_sha256}</code>
                  </dd>
                </div>
                <div>
                  <dt>확정된 원래 결과 수신 SHA</dt>
                  <dd>
                    <code>{binding.accepted_result_sha256}</code>
                  </dd>
                </div>
                <div>
                  <dt>현재 서버 재투영 코드 SHA</dt>
                  <dd>
                    <code>{binding.projector_sha256}</code>
                  </dd>
                </div>
              </dl>
              <p>
                정책을 자동 승격하거나 문장별 단어 시각을 추정하지 않습니다. 제거 구간별로 문장
                전체가 반복될 수 있습니다.
              </p>
            </>
          )}
          {data.can_manage ? (
            <>
              <Button
                disabled={
                  busy || !fresh || !candidate?.eligible || policy !== candidate.binding?.policy
                }
                onClick={() =>
                  void (async () => {
                    ++sequence.current;
                    setBusy(true);
                    setError('');
                    setAck(false);
                    setPreview(null);
                    try {
                      const row = await jsonPost<Operation>(base + '/preview', {
                        source_run_id: sourceId,
                        policy,
                      });
                      setPreview((old) => keepTerminal(old, row));
                      await load();
                    } catch (reason) {
                      setError(reason instanceof Error ? reason.message : '미리보기 실패');
                    } finally {
                      setBusy(false);
                    }
                  })()
                }
              >
                자료·SHA 검증 및 재투영 미리보기
              </Button>
              {preview && (
                <section aria-label="재투영 확인">
                  <h3>{labels[preview.status]}</h3>
                  <p>
                    정책 {preview.binding.policy} · 복구 자막 {preview.binding.segment_count}구간 ·
                    모델 추가 호출 0회
                  </p>
                  {preview.binding.expected_outputs && (
                    <dl>
                      {Object.entries(preview.binding.expected_outputs).map(([key, ref]) => (
                        <div key={key}>
                          <dt>예상 {key} SHA</dt>
                          <dd>
                            <code>{ref.sha256}</code> · {ref.bytes.toLocaleString()} bytes
                          </dd>
                        </div>
                      ))}
                    </dl>
                  )}
                  {preview.status === 'prepared' && (
                    <>
                      <label className="projection-ack">
                        <input
                          type="checkbox"
                          checked={ack}
                          disabled={busy}
                          onChange={(event) => setAck(event.target.checked)}
                        />
                        원 작업의 실패 기록을 보존하고, 새 모델 호출·후속 실행 없이 위 자료·정책으로
                        재투영할 것을 확인했습니다.
                      </label>
                      <Button
                        disabled={busy || !ack || !fresh}
                        onClick={() =>
                          void (async () => {
                            ++sequence.current;
                            setBusy(true);
                            setError('');
                            try {
                              const row = await jsonPost<Operation>(
                                base + '/' + preview.id + '/confirm',
                                { context_sha256: preview.context_sha256, acknowledge: true },
                              );
                              setPreview((old) => keepTerminal(old, row));
                              await load();
                            } catch (reason) {
                              setError(
                                reason instanceof Error
                                  ? reason.message
                                  : '결과 확인 실패. 자동 재실행하지 않습니다.',
                              );
                            } finally {
                              setBusy(false);
                            }
                          })()
                        }
                      >
                        모델 호출 없이 재투영 확정
                      </Button>
                    </>
                  )}
                </section>
              )}
            </>
          ) : (
            <p>공유 읽기 전용입니다. 실행자만 별도 재투영을 확인할 수 있습니다.</p>
          )}
          <h3>별도 복구 기록</h3>
          {data.operations.length === 0 && <p>아직 생성한 복구 파일이 없습니다.</p>}
          {data.operations.map((row) => (
            <article key={row.id}>
              <strong>{labels[row.status]}</strong>
              <p>
                <code>{row.id}</code> · 원 작업 상태는 변경하지 않았습니다.
              </p>
              {row.status === 'completed' &&
                Object.keys(row.outputs || {}).map((part) => (
                  <a key={part} href={mediaUrl(base + '/' + row.id + '/files/' + part)}>
                    {part === 'transcript' ? '복구 전사 JSON 다운로드' : '복구 trace JSON 다운로드'}
                  </a>
                ))}
              {['running', 'held'].includes(row.status) && (
                <p>결과가 불명확합니다. 새 모델 호출이나 재투영을 자동 반복하지 않습니다.</p>
              )}
            </article>
          ))}
        </>
      )}
    </section>
  );
};
