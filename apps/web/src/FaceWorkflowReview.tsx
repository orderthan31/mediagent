import { useEffect, useRef, useState } from 'react';
import { request, mediaUrl } from './api';
import { Button } from './hangyeol/primitives/button';
import './face-workflow.css';
type Candidate = { position: number };
type Contract = {
  kind: string;
  source?: { faces: Candidate[] };
  reference?: { faces: Candidate[] };
  expires_at?: number;
};
type Review = { id: string; revision: number; status: string; draft: unknown; contract: unknown };
type Editor = { review: Review; draft: Record<string, unknown>; error: string; uncertain: boolean };
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
const reconcileReview = (
  current: Editor,
  next: Review,
  read = false,
  acknowledged?: unknown,
): Editor => {
  if (
    next.id !== current.review.id ||
    next.revision < current.review.revision ||
    (next.revision === current.review.revision &&
      current.review.status === 'confirmed' &&
      next.status !== 'confirmed')
  ) {
    return current;
  }
  const dirty = !same(current.draft, current.review.draft);
  const saved =
    acknowledged !== undefined &&
    same(current.draft, acknowledged) &&
    same(next.draft, acknowledged);
  const keepDraft = dirty && !saved;
  const conflict =
    keepDraft &&
    !same(current.draft, next.draft) &&
    ((next.revision > current.review.revision && !same(current.review.draft, next.draft)) ||
      next.status === 'confirmed');
  return {
    review: next,
    draft: keepDraft ? current.draft : structuredClone(next.draft as Record<string, unknown>),
    uncertain: read || saved || next.status === 'confirmed' ? false : current.uncertain,
    error: conflict
      ? next.status === 'confirmed'
        ? '서버에서 확정되었습니다. 보존한 편집은 확정 내용에 반영되지 않았습니다.'
        : '검수 내용이 바뀌었습니다. 편집은 보존했습니다. 최신 내용을 확인한 뒤 저장하세요.'
      : read || saved
        ? ''
        : current.error,
  };
};

export const FaceWorkflowReview = ({
  initial,
  jobId,
  canManage,
  active = true,
  changed,
}: {
  initial: Review;
  jobId: string;
  canManage: boolean;
  active?: boolean;
  changed: () => Promise<void>;
}) => {
  const [editor, setEditor] = useState<Editor>(() => ({
    review: initial,
    draft: structuredClone(initial.draft as Record<string, unknown>),
    error: '',
    uncertain: false,
  }));
  const [busy, setBusy] = useState(false);
  const { review, draft, error, uncertain } = editor;
  const setError = (error: string) => setEditor((current) => ({ ...current, error }));
  const setUncertain = (uncertain: boolean) => setEditor((current) => ({ ...current, uncertain }));
  const setDraft = (draft: Record<string, unknown>) =>
    setEditor((current) => ({ ...current, draft }));
  const pending = useRef(false),
    alive = useRef(true);
  const contract = review.contract as Contract,
    selection = contract.kind === 'face_select',
    confirmed = review.status === 'confirmed';
  const dirty = !same(draft, review.draft);
  const displayDraft = confirmed ? (review.draft as Record<string, unknown>) : draft;
  const complete = selection
    ? Number.isInteger(draft.source_position) && Number.isInteger(draft.face_position)
    : draft.confirmed === true;
  const submit = async (action: 'save' | 'confirm') => {
    if (pending.current || !canManage || !active || confirmed || uncertain) {
      return;
    }
    pending.current = true;
    setBusy(true);
    setError('');
    const submitted = structuredClone(draft);
    try {
      const next = await request<Review | { reviews: Review[] }>(
        `/renewal/reviews/${review.id}/${action}`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            revision: review.revision,
            ...(action === 'save' ? { draft: submitted } : {}),
          }),
        },
      );
      if (alive.current) {
        if (action === 'save') {
          if (!('id' in next)) {
            throw new Error('저장 응답을 확인하지 못했습니다. 상태를 다시 확인하세요.');
          }
          setEditor((current) => reconcileReview(current, next, false, submitted));
        } else {
          if ('reviews' in next) {
            const confirmedReview = next.reviews.find((row) => row.id === review.id);
            if (confirmedReview) {
              setEditor((current) => reconcileReview(current, confirmedReview));
            }
          }
          await changed();
        }
      }
    } catch (e) {
      if (alive.current) {
        setError(e instanceof Error ? e.message : '저장 결과를 확인하지 못했습니다.');
        setUncertain(true);
      }
    } finally {
      pending.current = false;
      if (alive.current) {
        setBusy(false);
      }
    }
  };
  const reload = async () => {
    if (pending.current) {
      return;
    }
    pending.current = true;
    setBusy(true);
    setError('');
    try {
      const current = await request<{ reviews: Review[] }>(`/renewal/jobs/${jobId}`);
      const next = current.reviews.find((row) => row.id === review.id);
      if (!next) {
        throw new Error('현재 작업의 검수 자료를 찾지 못했습니다.');
      }
      if (alive.current) {
        setEditor((current) => reconcileReview(current, next, true));
      }
    } catch (e) {
      if (alive.current) {
        setError(e instanceof Error ? e.message : '최신 상태를 확인하지 못했습니다.');
      }
    } finally {
      pending.current = false;
      if (alive.current) {
        setBusy(false);
      }
    }
  };
  useEffect(() => {
    setEditor((current) => reconcileReview(current, initial));
  }, [initial]);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  return (
    <section
      className="face-workflow-review"
      aria-label={selection ? '합성할 인물 선택' : '합성 미리보기 확인'}
    >
      <h4>{selection ? '사진과 영상의 인물을 각각 선택하세요' : '합성 미리보기를 확인하세요'}</h4>
      {!canManage && <p>작업을 만든 사용자만 선택·확정할 수 있습니다.</p>}
      {selection ? (
        (['source', 'reference'] as const).map((group) => (
          <fieldset key={group} disabled={!canManage || !active || busy || confirmed || uncertain}>
            <legend>{group === 'source' ? '사진 인물' : '영상 인물'}</legend>
            <div className="face-candidates">
              {contract[group]?.faces.map((face) => (
                <label key={face.position}>
                  <img
                    alt={`${group === 'source' ? '사진' : '영상'} 인물 ${face.position + 1}`}
                    src={mediaUrl(
                      `/renewal/reviews/${review.id}/face-image/${group}/${face.position}`,
                    )}
                  />
                  <span>
                    <input
                      type="radio"
                      name={`${review.id}-${group}`}
                      checked={
                        displayDraft[group === 'source' ? 'source_position' : 'face_position'] ===
                        face.position
                      }
                      onChange={() =>
                        setDraft({
                          ...draft,
                          [group === 'source' ? 'source_position' : 'face_position']: face.position,
                        })
                      }
                    />
                    인물 {face.position + 1}
                  </span>
                </label>
              ))}
            </div>
            {!contract[group]?.faces.length && <p role="alert">선택할 인물이 없습니다.</p>}
          </fieldset>
        ))
      ) : (
        <>
          <img
            className="face-confirm-image"
            alt="합성 미리보기"
            src={mediaUrl(`/renewal/reviews/${review.id}/face-image/preview/0`)}
          />
          <label>
            <input
              type="checkbox"
              checked={displayDraft.confirmed === true}
              disabled={!canManage || !active || busy || confirmed || uncertain}
              onChange={(e) => setDraft({ confirmed: e.target.checked })}
            />
            이 미리보기의 인물과 합성 결과를 확인했습니다.
          </label>
          <p>
            확인 후 다음 시작에서 합성을 진행합니다. 미리보기가 만료되면 자동으로 다시 실행하지
            않습니다.
          </p>
        </>
      )}
      {canManage && !active && <p>현재 작업 상태에서는 검수 내용을 변경할 수 없습니다.</p>}
      {confirmed && dirty && (
        <p>
          저장하지 않은 편집은 별도로 보존됩니다.{' '}
          {selection
            ? `사진 인물 ${Number(draft.source_position) + 1} · 영상 인물 ${Number(draft.face_position) + 1}`
            : '미리보기 확인 편집'}
        </p>
      )}
      {error && <p role="alert">{error} 최신 상태를 다시 불러와 저장 여부를 확인하세요.</p>}
      <div className="face-review-actions">
        <Button
          disabled={!canManage || !active || busy || confirmed || uncertain || !complete || !dirty}
          onClick={() => void submit('save')}
        >
          선택 저장
        </Button>
        <Button
          disabled={!canManage || !active || busy || confirmed || uncertain || !complete || dirty}
          onClick={() => void submit('confirm')}
        >
          {selection ? '인물 선택 확정' : '미리보기 확인 확정'}
        </Button>
        <Button variant="quiet" disabled={busy} onClick={() => void reload()}>
          상태 다시 불러오기
        </Button>
      </div>
      {confirmed && <p role="status">확정됨</p>}
    </section>
  );
};
