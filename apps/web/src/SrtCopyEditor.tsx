import { useEffect, useId, useRef, useState } from 'react';
import { Button } from './hangyeol/primitives/button';
import { Textarea } from './hangyeol/primitives/textarea';
import { Pagination, usePagination } from './Pagination';
import {
  copyTextIssue,
  cueCopyText,
  downloadSrtCopy,
  readSrtCopy,
  srtSourcePath,
  type SrtCopyDocument,
  type SrtCopySource,
} from './srt-copy';
import './srt-copy.css';

const SrtCopyEditor = ({ source, onClose }: { source: SrtCopySource; onClose: () => void }) => {
  const [document, setDocument] = useState<SrtCopyDocument | null>(null);
  const [edits, setEdits] = useState<Record<number, string>>({});
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [attempt, setAttempt] = useState(0);
  const dialog = useRef<HTMLDialogElement>(null);
  const prefix = useId();
  const key = srtSourcePath(source);
  const page = usePagination(document?.cues || [], key, 20);
  const invalid = Object.entries(edits).find(([, text]) => copyTextIssue(text));
  const retry = () => {
    setDocument(null);
    setEdits({});
    setError('');
    setLoading(true);
    setAttempt((value) => value + 1);
  };
  const download = () => {
    if (!document || invalid) {
      return;
    }
    try {
      downloadSrtCopy(source, document, edits);
      setError('');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '수정본을 만들지 못했습니다.');
    }
  };
  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    return () => element?.close();
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    void readSrtCopy(source, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) {
          setDocument(value);
          setLoading(false);
        }
      })
      .catch((reason) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : '자막 파일을 불러오지 못했습니다.');
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [key, attempt]);
  return (
    <dialog
      ref={dialog}
      className="srt-copy-dialog"
      aria-labelledby={`${prefix}-title`}
      aria-describedby={`${prefix}-notice`}
      onKeyDown={(event) => {
        if (event.key === 'Escape') {
          event.stopPropagation();
        }
      }}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      <div className="srt-copy-heading">
        <h2 id={`${prefix}-title`}>자막 수정</h2>
        <Button variant="secondary" onClick={onClose}>
          닫기
        </Button>
      </div>
      <div className="srt-copy-body" aria-busy={loading}>
        <p className="srt-copy-filename">{source.filename}</p>
        <p id={`${prefix}-notice`}>
          문구만 수정한 SRT 사본을 받습니다. 원래 결과 파일과 영상은 바뀌지 않습니다.
        </p>
        {loading && <p role="status">자막 불러오는 중</p>}
        {error && <p role="alert">{error}</p>}
        {!loading && !document && (
          <Button variant="secondary" onClick={retry}>
            다시 확인
          </Button>
        )}
        {invalid && document && (
          <p role="alert">
            자막 {document.cues[Number(invalid[0])].id}: {copyTextIssue(invalid[1])}{' '}
            <Button
              variant="quiet"
              onClick={() => page.onPage(Math.floor(Number(invalid[0]) / page.pageSize) + 1)}
            >
              해당 자막으로
            </Button>
          </p>
        )}
        {document && (
          <>
            <ol className="srt-copy-cues" start={page.offset + 1}>
              {page.items.map((cue, offset) => {
                const index = page.offset + offset;
                const text = edits[index] ?? cueCopyText(cue);
                const issue = copyTextIssue(text);
                return (
                  <li key={index}>
                    <label htmlFor={`${prefix}-cue-${index}`}>자막 {cue.id} 문구</label>
                    <p className="srt-copy-clock">{cue.clock}</p>
                    <Textarea
                      id={`${prefix}-cue-${index}`}
                      value={text}
                      aria-invalid={!!issue}
                      aria-describedby={`${prefix}-cue-${index}-issue`}
                      onChange={(event) => {
                        setEdits((previous) => ({ ...previous, [index]: event.target.value }));
                        setError('');
                      }}
                    />
                    <p id={`${prefix}-cue-${index}-issue`}>{issue}</p>
                  </li>
                );
              })}
            </ol>
            <Pagination {...page} />
          </>
        )}
      </div>
      <div className="srt-copy-actions">
        <Button disabled={!document || loading || !!invalid} onClick={download}>
          수정본 받기
        </Button>
      </div>
    </dialog>
  );
};

const SrtCopyControl = ({ source }: { source: SrtCopySource }) => {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button variant="quiet" onClick={() => setOpen(true)}>
        자막 수정
      </Button>
      {open && <SrtCopyEditor source={source} onClose={() => setOpen(false)} />}
    </>
  );
};
export const SrtCopyAction = ({ source }: { source: SrtCopySource | null }) =>
  source ? <SrtCopyControl key={srtSourcePath(source)} source={source} /> : null;
