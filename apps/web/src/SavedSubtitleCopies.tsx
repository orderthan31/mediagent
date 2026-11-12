import { useEffect, useState } from 'react';
import { PageTitle } from './PageTitle';
import { Button } from './hangyeol/primitives/button';
import { listSubtitleCopies, type SubtitleCopy } from './subtitle-copies';
import './direct-subtitle.css';

export const SavedSubtitleCopies = () => {
  const [copies, setCopies] = useState<SubtitleCopy[]>([]);
  const [after, setAfter] = useState<string>();
  const [next, setNext] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError('');
    setCopies([]);
    setNext(null);
    void listSubtitleCopies(after, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) {
          setCopies(value.copies);
          setNext(value.next_cursor);
        }
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : '저장된 자막을 불러오지 못했습니다.');
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [after, refresh]);
  return (
    <main className="video-main direct-subtitle-page">
      <PageTitle>저장된 자막</PageTitle>
      <a href="#/subtitles">자막 파일 편집</a>
      <p>수정본을 열어 문구·시각을 편집하거나 SRT·SMI 사본을 받을 수 있습니다.</p>
      {loading && <p role="status">저장된 자막 불러오는 중</p>}
      {error && <p role="alert">{error}</p>}
      {!loading && !error && !copies.length && <p>저장된 자막이 없습니다.</p>}
      <ul className="direct-subtitle-cues">
        {copies.map((copy) => (
          <li key={copy.id}>
            <h2>
              <a href={`#/subtitles/saved/${copy.id}`}>{copy.title}</a>
            </h2>
            <p>{copy.filename}</p>
            <a href={`#/start/subtitles/${copy.id}`}>영상 작업 준비</a>
            <p>
              <time dateTime={copy.created_at}>
                {new Date(copy.created_at).toLocaleString('ko-KR')}
              </time>{' '}
              · 자막 {copy.cue_count}개
            </p>
          </li>
        ))}
      </ul>
      <div className="direct-subtitle-actions">
        <Button
          variant="quiet"
          disabled={loading}
          onClick={() => {
            setAfter(undefined);
            setRefresh((value) => value + 1);
          }}
        >
          처음부터 새로고침
        </Button>
        {next && (
          <Button disabled={loading} onClick={() => setAfter(next)}>
            다음 목록
          </Button>
        )}
      </div>
    </main>
  );
};
