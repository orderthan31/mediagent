import { useCallback, useEffect, useRef, useState } from 'react';
import { SrtCopyAction } from './SrtCopyEditor';
import { trackSrtSource } from './srt-copy';
import { request, mediaUrl } from './api';
import { jsonPost } from './video-api';
import { Button } from './hangyeol/primitives/button';
import './subtitle-tracks.css';

type Ref = { sha256: string; bytes: number; type: string };
type Cue = { id: string | number; start: number; end: number; text: string; speaker?: string };
type Review = {
  id: string;
  revision: number;
  status: string;
  contract: {
    kind?: string;
    tracks?: Record<string, { language: string }>;
    duration_seconds?: number;
  };
  draft: Record<string, unknown>;
};
type Track = { revision: number; name: string; language: string; transcript: Ref; cues: Cue[] };
const title = (name: string, language: string) =>
  `${name === 'original' ? '원문' : name === 'translated' ? '주 번역' : '추가 번역'} · ${language}`;

export const SubtitleTrackReview = ({
  review,
  canManage,
  assetId,
  onChanged,
}: {
  review: Review;
  canManage: boolean;
  assetId: string;
  onChanged: () => void;
}) => {
  const [row, setRow] = useState(review);
  const [name, setName] = useState('translated');
  const [track, setTrack] = useState<Track | null>(null);
  const [cues, setCues] = useState<Cue[]>([]);
  const [dirty, setDirty] = useState(false);
  const [ack, setAck] = useState(false);
  const [page, setPage] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [current, setCurrent] = useState(0);
  const video = useRef<HTMLVideoElement>(null);
  const sequence = useRef(0);
  const base = '/renewal/reviews/' + review.id;
  const load = useCallback(
    async (selected: string) => {
      const token = ++sequence.current;
      const data = await request<Track>(base + '/subtitle-tracks/' + encodeURIComponent(selected));
      if (token !== sequence.current) {
        return;
      }
      setTrack(data);
      setCues(data.cues);
      setDirty(false);
      setAck(false);
      setPage(0);
    },
    [base],
  );
  const disabled =
    !canManage || row.status === 'confirmed' || busy || !track || track.name !== name;
  const change = (index: number, patch: Partial<Cue>) => {
    setCues((old) => old.map((cue, i) => (i === index ? { ...cue, ...patch } : cue)));
    setDirty(true);
    setAck(false);
  };
  const act = async (action: () => Promise<void>) => {
    setBusy(true);
    setError('');
    try {
      await action();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '요청 실패. 편집 내용은 유지됩니다.');
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => {
    setRow((old) => (review.revision >= old.revision ? review : old));
  }, [review]);
  useEffect(() => {
    void load(name).catch((reason: unknown) =>
      setError(reason instanceof Error ? reason.message : '검수 자막 조회 실패'),
    );
    return () => {
      sequence.current++;
    };
  }, [name, load]);
  return (
    <section className="subtitle-track-review" aria-label="원문·다국어 자막 검수">
      <h4>원문·다국어 자막 검수 {row.status === 'confirmed' ? '· 확정됨' : ''}</h4>
      <p>
        언어별 내용·시작/끝 시각을 편집하고 저장하세요. 확정은 실행이 아니며, 새 계획·동의 뒤 이어
        실행합니다.
      </p>
      <video
        ref={video}
        src={mediaUrl('/videos/' + assetId + '/stream')}
        controls
        preload="none"
        onTimeUpdate={() => setCurrent(video.current?.currentTime || 0)}
      />
      <label>
        검수 언어
        <select
          value={name}
          disabled={busy}
          onChange={(event) => {
            if (!dirty || window.confirm('저장하지 않은 편집이 있습니다. 언어를 바꿀까요?')) {
              setName(event.target.value);
              setError('');
            }
          }}
        >
          {Object.entries(row.contract.tracks || {}).map(([key, value]) => (
            <option key={key} value={key}>
              {title(key, value.language)}
            </option>
          ))}
        </select>
      </label>
      <p>
        저장 개정 {track?.revision} · 자막 {cues.length.toLocaleString()}개 · 현재{' '}
        {current.toFixed(3)}초 / 원본 {row.contract.duration_seconds?.toFixed(3)}초
      </p>
      {track && (
        <details>
          <summary>자막 저장 정보</summary>
          <p className="subtitle-sha">SHA256 {track.transcript.sha256}</p>
        </details>
      )}
      {error && (
        <p role="alert">
          {error} 자동 재전송하지 않습니다. 저장 결과가 불명이면 새로 읽어 확인하세요.
        </p>
      )}
      {cues.slice(page * 25, (page + 1) * 25).map((cue, offset) => {
        const index = page * 25 + offset;
        return (
          <fieldset
            key={cue.id}
            className={current >= cue.start && current < cue.end ? 'active-cue' : ''}
            disabled={disabled}
          >
            <legend>
              자막 {index + 1} · ID {String(cue.id)}
            </legend>
            <div className="subtitle-times">
              <label>
                시작(초)
                <input
                  aria-label={`자막 ${index + 1} 시작`}
                  type="number"
                  min="0"
                  step="0.001"
                  value={cue.start}
                  onChange={(event) => change(index, { start: Number(event.target.value) })}
                />
              </label>
              <label>
                끝(초)
                <input
                  aria-label={`자막 ${index + 1} 끝`}
                  type="number"
                  min="0"
                  step="0.001"
                  value={cue.end}
                  onChange={(event) => change(index, { end: Number(event.target.value) })}
                />
              </label>
            </div>
            <label>
              내용
              <textarea
                aria-label={`자막 ${index + 1} 내용`}
                rows={2}
                maxLength={1000}
                value={cue.text}
                onChange={(event) => change(index, { text: event.target.value })}
              />
            </label>
            <Button
              variant="secondary"
              onClick={() => {
                if (video.current) {
                  video.current.currentTime = cue.start;
                }
              }}
            >
              이 시각 보기
            </Button>
            <Button
              variant="secondary"
              disabled={cues.length <= 1}
              onClick={() => {
                setCues((old) => old.filter((_, i) => i !== index));
                setDirty(true);
                setAck(false);
              }}
            >
              자막 삭제
            </Button>
          </fieldset>
        );
      })}
      <div className="subtitle-actions">
        <Button
          variant="secondary"
          disabled={page === 0 || busy}
          onClick={() => setPage((old) => old - 1)}
        >
          이전 25개
        </Button>
        <Button
          variant="secondary"
          disabled={(page + 1) * 25 >= cues.length || busy}
          onClick={() => setPage((old) => old + 1)}
        >
          다음 25개
        </Button>
        <Button
          variant="secondary"
          disabled={disabled || cues.length >= 10000}
          onClick={() => {
            const duration = row.contract.duration_seconds || 0;
            const start = Math.max(0, Math.min(current, duration - 0.1));
            setCues((old) => [
              ...old,
              {
                id: 'edit-' + crypto.randomUUID(),
                start,
                end: Math.min(start + 0.5, duration),
                text: '',
              },
            ]);
            setPage(Math.floor(cues.length / 25));
            setDirty(true);
            setAck(false);
          }}
        >
          자막 추가
        </Button>
        <Button
          variant="secondary"
          disabled={disabled}
          onClick={() => {
            setCues((old) => [...old].sort((a, b) => a.start - b.start || a.end - b.end));
            setDirty(true);
            setAck(false);
          }}
        >
          시각순 정렬
        </Button>
        <Button
          disabled={disabled || !dirty || !track}
          onClick={() =>
            void act(async () => {
              const saved = await jsonPost<Review>(
                base + '/subtitle-tracks/' + encodeURIComponent(name) + '/save',
                { revision: row.revision, cues },
              );
              setRow(saved);
              await load(name);
              onChanged();
            })
          }
        >
          이 언어 검수 저장
        </Button>
        <Button
          variant="secondary"
          disabled={busy}
          onClick={() => {
            if (!dirty || window.confirm('편집을 버리고 저장 자료를 다시 읽을까요?')) {
              void act(async () => {
                await load(name);
                onChanged();
              });
            }
          }}
        >
          저장 자막 다시 읽기
        </Button>
      </div>
      <p>
        구간 삭제·추가는 가능하지만 시간순·겹침·원본 길이·빈 내용 제한을 확인합니다. 저장할 때 읽기
        편한 줄 길이로 나눌 수 있습니다. 원래 구간과의 연결 기록은 보존됩니다.
      </p>
      <label>
        <input
          type="checkbox"
          checked={ack}
          disabled={disabled || dirty}
          onChange={(event) => setAck(event.target.checked)}
        />
        저장된 원문·주 번역·추가 언어 모두를 확인했고 이 개정으로 확정하겠습니다.
      </label>
      <Button
        disabled={disabled || dirty || !ack}
        onClick={() =>
          void act(async () => {
            const approved = await jsonPost<Review>(base + '/save', {
              revision: row.revision,
              draft: { ...row.draft, approved: true },
            });
            setRow(approved);
            const confirmed = await jsonPost<Review>(base + '/confirm', {
              revision: approved.revision,
            });
            setRow(confirmed);
            setAck(false);
            onChanged();
          })
        }
      >
        저장한 전체 언어 검수 확정
      </Button>
    </section>
  );
};

type Output = {
  run_id: string;
  review: { id: string; revision: number; confirmed_sha256: string } | null;
  tracks: Record<
    string,
    {
      language: string;
      transcript: Ref;
      files: Record<string, { filename: string; reference: Ref }>;
    }
  >;
};
export const SubtitleOutputs = ({ jobId, revision }: { jobId: string; revision: number }) => {
  const [data, setData] = useState<Output[]>([]);
  const [error, setError] = useState('');
  const base = '/renewal/jobs/' + jobId + '/subtitle-outputs';
  useEffect(() => {
    let active = true;
    void request<{ outputs: Output[] }>(base)
      .then((next) => {
        if (active) {
          setData(next.outputs);
          setError('');
        }
      })
      .catch((reason: unknown) => {
        if (active) {
          setError(reason instanceof Error ? reason.message : '언어별 산출물 조회 실패');
        }
      });
    return () => {
      active = false;
    };
  }, [base, revision]);
  return (
    <section className="subtitle-track-review" aria-label="언어별 자막 산출물">
      <h3>언어별 자막 산출물</h3>
      {error && <p role="alert">{error}</p>}
      {!data.length && (
        <p>
          실행 뒤 언어별 파일을 받을 수 있습니다. 검수 OFF는 별도 확정 없이 진행합니다. 아직 완료
          파일이 없습니다.
        </p>
      )}
      {data.map((output) => (
        <div key={output.run_id}>
          {output.review ? (
            <p className="subtitle-sha">
              확정 검수 {output.review.id} / 개정 {output.review.revision} · SHA{' '}
              {output.review.confirmed_sha256}
            </p>
          ) : (
            <p>검수 OFF · 자동 생성 · 사람 검수 확정 아님</p>
          )}
          {Object.entries(output.tracks).map(([name, track]) => (
            <section key={name}>
              <h4>{title(name, track.language)}</h4>
              <p className="subtitle-sha">전사 SHA {track.transcript.sha256}</p>
              {Object.entries(track.files).map(([extension, file]) => (
                <div key={extension} className="subtitle-sha">
                  <a
                    href={mediaUrl(
                      base + '/' + output.run_id + '/' + encodeURIComponent(name) + '/' + extension,
                    )}
                    download
                  >
                    {file.filename} 받기
                  </a>{' '}
                  <SrtCopyAction
                    source={trackSrtSource(jobId, output.run_id, name, extension, file)}
                  />
                  · {file.reference.bytes.toLocaleString()} bytes · {file.reference.sha256}
                </div>
              ))}
            </section>
          ))}
        </div>
      ))}
    </section>
  );
};
