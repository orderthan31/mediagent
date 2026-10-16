import { useRef, useState } from 'react';
import { request, mediaUrl } from './api';
import { jsonPost } from './video-api';
import { Button } from './hangyeol/primitives/button';
import { Input } from './hangyeol/primitives/input';
import { Badge } from './hangyeol/primitives/badge';

type Cue = { start: number | string; end: number | string; text: string; speaker?: string };
export type ReviewDocument = {
  kind: string;
  editable: boolean;
  read_only_reason: string;
  source: Record<string, unknown>;
  revision: number;
  state_revision: number;
  sha256: string;
  document_sha256: string;
  target: string;
  cues: Cue[] | null;
  status: string;
  request_changes_reason: string;
  approval: null | { revision: number; sha256: string; input_sha256: string };
};

export const ReviewPanel = ({
  ticketId,
  ticketBase = '/settings/review-tickets',
  node,
  initial,
  executed,
  changed,
}: {
  ticketId: string;
  ticketBase?: string;
  node: string;
  initial: ReviewDocument;
  executed: boolean;
  changed: () => Promise<void>;
}) => {
  const base = `${ticketBase}/${ticketId}/reviews/${encodeURIComponent(node)}`;
  const [server, setServer] = useState(initial);
  const [cues, setCues] = useState(initial.cues);
  const [dirty, setDirty] = useState(false);
  const [reason, setReason] = useState('');
  const [error, setError] = useState('');
  const [status, setStatus] = useState('');
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState<ReviewDocument | null>(null);
  const pendingDecision = useRef<{ fingerprint: string; request_id: string } | null>(null);
  const target = () => ({
    target: server.target,
    state_revision: server.state_revision,
    revision: server.revision,
    sha256: server.sha256,
  });
  const reload = async () => {
    setBusy(true);
    setError('');
    try {
      const latest = await request<ReviewDocument>(base);
      setServer(latest);
      if (!dirty) {
        setCues(latest.cues);
      }
      setStatus(
        '최신 revision/SHA를 조회했습니다. 내 편집은 유지했습니다. 자동 병합/승인은 하지 않습니다.',
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : '자료 조회 실패 · 편집 보존');
    } finally {
      setBusy(false);
    }
  };
  const save = async () => {
    setBusy(true);
    setError('');
    try {
      const normalized = cues?.map((c) => {
        if (
          c.start === '' ||
          c.end === '' ||
          !Number.isFinite(Number(c.start)) ||
          !Number.isFinite(Number(c.end))
        ) {
          throw new Error('시작/끝에 유효한 초 단위 숫자를 입력하세요.');
        }
        return { ...c, start: Number(c.start), end: Number(c.end) };
      });
      const saved = await request<ReviewDocument>(base, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...target(), cues: normalized }),
      });
      setServer(saved);
      setCues(saved.cues);
      setDirty(false);
      pendingDecision.current = null;
      setStatus('수정본 별도 저장. 아직 승인/이어 실행하지 않았습니다.');
      await changed();
    } catch (e) {
      setError(e instanceof Error ? e.message : '저장 실패 · 편집 보존');
    } finally {
      setBusy(false);
    }
  };
  const decide = async (action: 'approve' | 'request_changes') => {
    setBusy(true);
    setError('');
    try {
      const payload = { ...target(), action, reason: action === 'request_changes' ? reason : '' };
      const fingerprint = JSON.stringify(payload);
      if (pendingDecision.current?.fingerprint !== fingerprint) {
        pendingDecision.current = { fingerprint, request_id: crypto.randomUUID() };
      }
      const next = await jsonPost<ReviewDocument>(base + '/decision', {
        ...payload,
        request_id: pendingDecision.current.request_id,
      });
      setServer(next);
      pendingDecision.current = null;
      setStatus(
        action === 'approve'
          ? '자료 확정 · 이어 실행 전. 별도 계획/비용 확인과 요청이 필요합니다.'
          : '수정 요청 · 검수 대기를 유지합니다. 영구 거절/가지 종료가 아닙니다.',
      );
      await changed();
    } catch (e) {
      setError(e instanceof Error ? e.message : '결정 저장 실패 · 자동 재실행 없음');
    } finally {
      setBusy(false);
    }
  };
  const shown = executed ? initial : server;
  const displayedCues = executed ? initial.cues : cues;
  return (
    <section className="review-panel" data-review-node={node}>
      <h4>사람 검수 · {node}</h4>
      <p>
        <Badge tone="neutral">
          {executed
            ? '승인 gate 통과'
            : shown.approval
              ? '자료 확정 · 이어 실행 전'
              : shown.status === 'changes_requested'
                ? '수정 요청 · 대기 유지'
                : '검수 대기'}
        </Badge>{' '}
        · 수정본 r{shown.revision} · 결정 상태 r{shown.state_revision}
      </p>
      <p className="review-sha">
        {executed ? '실행에 고정한 SHA' : '승인할 SHA'} {shown.sha256}
      </p>
      <p className="serving-help">
        저장 ≠ 승인 ≠ 계획 확인 ≠ 이어 실행. 원본·과거 수정본을 보존합니다. 승인 후 재편집/취소·실패
        재시도/전체 재개는 하지 않습니다.
      </p>
      {!shown.editable && <p>{shown.read_only_reason}</p>}
      <a href={mediaUrl(`${base}/input`)} target="_blank" rel="noreferrer">
        검수 입력 원본 열기
      </a>
      {shown.kind === 'video' && <video controls preload="none" src={mediaUrl(`${base}/input`)} />}
      {shown.kind === 'audio' && <audio controls preload="none" src={mediaUrl(`${base}/input`)} />}
      <details>
        <summary>원본 참조 · clock · provenance</summary>
        <pre>{JSON.stringify(shown.source, null, 2)}</pre>
      </details>
      {error && (
        <p role="alert" className="alert">
          {error}
        </p>
      )}
      {executed ? (
        <p role="status">
          정확한 승인 revision/SHA로 검수 단계를 통과했습니다. 이후 단계 상태는 별도로 확인하세요.
        </p>
      ) : (
        status && <p role="status">{status}</p>
      )}
      {initial.state_revision !== shown.state_revision && (
        <p className="serving-help">
          다른 화면의 상태와 차이가 있으면 최신값을 명시 조회하세요. 내 편집을 자동 교체하지
          않습니다.
        </p>
      )}
      {shown.request_changes_reason && <p>수정 요청 사유: {shown.request_changes_reason}</p>}
      {executed && dirty && (
        <details>
          <summary>보존된 로컬 미저장 편집 · 실행본 아님</summary>
          <pre>{JSON.stringify(cues, null, 2)}</pre>
        </details>
      )}
      {displayedCues?.map((cue, i) => (
        <fieldset key={i} disabled={busy || !shown.editable || !!shown.approval}>
          <legend>구간 {i + 1}</legend>
          <div className="review-times">
            <label>
              시작(원본 초)
              <Input
                aria-label={`구간 ${i + 1} 시작`}
                type="number"
                step="0.001"
                value={cue.start}
                onChange={(e) => {
                  setCues(
                    (cues || []).map((c, n) => (n === i ? { ...c, start: e.target.value } : c)),
                  );
                  setDirty(true);
                }}
              />
            </label>
            <label>
              끝(원본 초)
              <Input
                aria-label={`구간 ${i + 1} 끝`}
                type="number"
                step="0.001"
                value={cue.end}
                onChange={(e) => {
                  setCues(
                    (cues || []).map((c, n) => (n === i ? { ...c, end: e.target.value } : c)),
                  );
                  setDirty(true);
                }}
              />
            </label>
          </div>
          <label>
            텍스트
            <textarea
              aria-label={`구간 ${i + 1} 텍스트`}
              value={cue.text}
              onChange={(e) => {
                setCues((cues || []).map((c, n) => (n === i ? { ...c, text: e.target.value } : c)));
                setDirty(true);
              }}
            />
          </label>
        </fieldset>
      ))}
      <p className="serving-help">
        문서/수정 결과 각 1MiB 이하. 기존 구간 수·speaker를 유지한 텍스트/구간 수정만 지원하며 원본
        길이·겹침을 서버에서 검증합니다. 미디어 bytes·clockmap·manifest 구성원은 바꾸지 않습니다.
      </p>
      <div className="ticket-actions">
        <Button variant="secondary" disabled={busy} onClick={() => void reload()}>
          최신 서버값 조회 · 내 편집 유지
        </Button>
        <Button
          variant="secondary"
          disabled={busy || !dirty}
          onClick={() => {
            setCues(shown.cues);
            setDirty(false);
            setStatus('명시적으로 조회한 서버 수정본으로 편집을 교체했습니다.');
          }}
        >
          서버값으로 편집 교체
        </Button>
        <Button
          disabled={busy || !shown.editable || !!shown.approval || !dirty}
          onClick={() => void save()}
        >
          수정본 별도 저장
        </Button>
        <Button disabled={busy || dirty || !!shown.approval} onClick={() => void decide('approve')}>
          현재 revision/SHA 명시 승인
        </Button>
      </div>
      <label>
        수정 요청 사유
        <Input
          aria-label="수정 요청 사유"
          value={reason}
          maxLength={2000}
          disabled={busy || !!shown.approval}
          onChange={(e) => setReason(e.target.value)}
        />
      </label>
      <Button
        variant="secondary"
        disabled={busy || dirty || !!shown.approval || !reason.trim()}
        onClick={() => void decide('request_changes')}
      >
        반려 · 수정 요청으로 대기 유지
      </Button>
      <details>
        <summary>불변 수정본 이력</summary>
        {Array.from({ length: shown.revision }, (_, i) => (
          <Button
            variant="secondary"
            key={i}
            disabled={busy}
            onClick={() => {
              void request<ReviewDocument>(base + '/revisions/' + (i + 1))
                .then(setHistory)
                .catch((e) => setError(e instanceof Error ? e.message : '이력 조회 실패'));
            }}
          >
            r{i + 1} 조회
          </Button>
        ))}
        {history && (
          <pre>
            {JSON.stringify(
              {
                revision: history.revision,
                sha256: history.sha256,
                cues: history.cues,
                source: history.source,
              },
              null,
              2,
            )}
          </pre>
        )}
      </details>
    </section>
  );
};
