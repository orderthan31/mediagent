import { useEffect, useRef, useState } from 'react';
import {
  ArrowLeft,
  Download,
  FileText,
  Film,
  RefreshCw,
  Search,
  X,
  Pencil,
  FolderPlus,
  ArrowUpRight,
  ChevronDown,
} from 'lucide-react';
import { base, Job, request } from './api';
import { VideoAsset } from './video-api';
import { StageProgress } from './StageProgress';
import { failureMessage, isContentBlocked } from './job-failure';
import { SubtitleEditor } from './SubtitleEditor';
import { TicketSummary } from './TicketSummary';
import { JobTiming } from './JobTiming';
import { Button } from './hangyeol/primitives/button';
import { TextField } from './hangyeol/components/text-field';
import './job-detail.css';
import './ticket.css';
type Cue = {
  start: number;
  end: number;
  text: string;
};
type Track = {
  available: boolean;
  partial: boolean;
  cues: Cue[];
};
type Preview = {
  video_available: boolean;
  expired: boolean;
  tracks: Record<'original' | 'translated', Track>;
};
const timestamp = (value: number) => {
  const seconds = Math.floor(value);
  return [Math.floor(seconds / 3600), Math.floor(seconds / 60) % 60, seconds % 60]
    .map((n) => String(n).padStart(2, '0'))
    .join(':');
};
export const JobDetail = ({
  id,
  labels,
  promotedAssetId,
}: {
  id: string;
  labels: Record<string, string>;
  promotedAssetId?: string;
}) => {
  const [job, setJob] = useState<Job | null>(null),
    [preview, setPreview] = useState<Preview | null>(null);
  const [error, setError] = useState(''),
    [videoError, setVideoError] = useState(false);
  const [tab, setTab] = useState<'original' | 'translated'>('original'),
    [query, setQuery] = useState('');
  const [time, setTime] = useState(0),
    [reload, setReload] = useState(0);
  const [editing, setEditing] = useState(false);
  const [actionBusy, setActionBusy] = useState(false);
  const [promoting, setPromoting] = useState(false),
    [promotionError, setPromotionError] = useState('');
  const promotionDialog = useRef<HTMLDialogElement>(null);
  const video = useRef<HTMLVideoElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const track = preview?.tracks[tab];
  const videoAvailable = !!preview?.video_available || !!job?.metadata.asset_id;
  const videoUrl = preview?.video_available
    ? `${base}/jobs/${id}/stream`
    : `${base}/videos/${job?.metadata.asset_id}/stream`;
  const cues =
    track?.cues.filter((cue) => cue.text.toLocaleLowerCase().includes(query.toLocaleLowerCase())) ||
    [];
  const resultFiles = job?.metadata.result_files || [];
  const isFaceSwap = job?.metadata.workflow?.template === 'faceswap';
  const downloadFiles = [
    ...new Set([...resultFiles, ...(preview?.video_available ? ['final.mp4'] : [])]),
  ];
  const seek = (cue: Cue) => {
    if (!video.current || !videoAvailable || videoError) {
      return;
    }
    video.current.currentTime = cue.start;
    setTime(cue.start);
  };
  const faceSwapAction = async (action: 'cancel' | 'retry') => {
    setActionBusy(true);
    try {
      await request(`/jobs/${id}/${action}`, { method: 'POST' });
      setReload((n) => n + 1);
    } catch (e) {
      setError(e instanceof Error ? e.message : '요청에 실패했습니다.');
    } finally {
      setActionBusy(false);
    }
  };
  const promote = async () => {
    setPromoting(true);
    setPromotionError('');
    try {
      const asset = await request<VideoAsset>(`/jobs/${id}/promote-video`, { method: 'POST' });
      promotionDialog.current?.close();
      location.hash = `/videos/${asset.asset_id}`;
    } catch (e) {
      setPromotionError(e instanceof Error ? e.message : '원본 등록에 실패했습니다.');
    } finally {
      setPromoting(false);
    }
  };
  const resultLabel = (name: string) =>
    name === 'final.mp4'
      ? '결과 영상 · MP4'
      : name === 'audio.wav'
        ? '추출 음성 · WAV'
        : name.replace('original.', '전사록 · ').replace('translated.', '번역 자막 · ');
  useEffect(() => {
    heading.current?.focus();
  }, []);
  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    const refresh = async () => {
      try {
        const [next, data] = await Promise.all([
          request<Job>(`/jobs/${id}`, { signal: controller.signal }),
          request<Preview>(`/jobs/${id}/preview`, { signal: controller.signal }),
        ]);
        if (!disposed) {
          setJob(next);
          setPreview(data);
          setError('');
        }
      } catch (e) {
        if (!disposed) {
          setError(e instanceof Error ? e.message : '작업을 불러오지 못했습니다.');
        }
      } finally {
        if (!disposed) {
          timer = setTimeout(refresh, 5000);
        }
      }
    };
    void refresh();
    return () => {
      disposed = true;
      controller.abort();
      clearTimeout(timer);
    };
  }, [id, reload]);
  return (
    <main className="job-detail ticket-detail">
      <div className="detail-page-heading">
        <a
          href={job?.metadata.asset_id ? `#/videos/${job.metadata.asset_id}` : '#/jobs'}
          className="icon"
          title={job?.metadata.asset_id ? '입력 영상으로' : '작업 목록으로'}
        >
          <ArrowLeft size={22} />
        </a>
        <div>
          <p className="eyebrow">티켓 상세</p>
          <h1 ref={heading} tabIndex={-1}>
            {job?.original_filename || '작업 불러오는 중'}
          </h1>
        </div>
        {job?.status === 'COMPLETED' && !preview?.expired && downloadFiles.length > 0 && (
          <details className="result-downloads">
            <summary>
              <Download size={17} />
              다운로드
              <ChevronDown size={14} />
            </summary>
            <div>
              {downloadFiles.map((file) => (
                <a key={file} href={`${base}/jobs/${id}/results/${encodeURIComponent(file)}`}>
                  <Download size={15} />
                  {resultLabel(file)}
                </a>
              ))}
            </div>
          </details>
        )}
        {job?.status === 'AWAITING_REVIEW' && (
          <Button onClick={() => setEditing(true)}>자막 검수</Button>
        )}
        <Button variant="secondary" title="작업 새로고침" onClick={() => setReload((n) => n + 1)}>
          <RefreshCw size={18} />
          새로고침
        </Button>
      </div>
      {error && (
        <p role="alert" className="alert">
          {error}
        </p>
      )}
      {job && <TicketSummary job={job} labels={labels} />}
      {job && <JobTiming job={job} />}
      {job && failureMessage(job) && (
        <p className="alert" role="alert">
          {failureMessage(job)}
        </p>
      )}
      <div className="detail-panels">
        <section className="media-panel" aria-label="영상">
          <div className="panel-heading">
            <h2>
              <Film size={18} />
              {preview?.video_available ? '결과 영상' : '원본 영상'}
            </h2>
          </div>
          <div className="player-surface">
            {videoAvailable && !editing ? (
              <video
                ref={video}
                controls
                playsInline
                preload="metadata"
                src={videoUrl}
                onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
                onError={() => setVideoError(true)}
                onLoadedMetadata={(e) => {
                  setVideoError(false);
                  if (time > 0) {
                    e.currentTarget.currentTime = time;
                  }
                }}
              />
            ) : (
              <div className="media-empty">
                <Film size={36} />
                <p>
                  {editing
                    ? '자막 편집 중'
                    : preview?.expired
                      ? '영상 보관 기간이 만료되었습니다.'
                      : job?.status === 'COMPLETED'
                        ? '영상 파일이 없습니다.'
                        : '영상 처리 완료 후 재생할 수 있습니다.'}
                </p>
              </div>
            )}
          </div>
          {videoError && (
            <p className="alert" role="alert">
              영상을 재생할 수 없습니다. 브라우저의 코덱 지원이나 연결 상태를 확인하거나 MP4를
              다운로드해 주세요.
            </p>
          )}
          {job?.status === 'COMPLETED' && preview?.video_available && !preview.expired && (
            <div className="result-actions">
              {promotedAssetId ? (
                <a href={`#/videos/${promotedAssetId}`}>
                  <ArrowUpRight size={16} />
                  등록된 원본 열기
                </a>
              ) : (
                <Button
                  variant="secondary"
                  onClick={() => {
                    setPromotionError('');
                    promotionDialog.current?.showModal();
                  }}
                >
                  <FolderPlus size={16} />새 원본으로 등록
                </Button>
              )}
            </div>
          )}
          {job && (
            <dl className="media-info">
              <div>
                <dt>등록 일시</dt>
                <dd>{new Date(job.created_at).toLocaleString('ko-KR')}</dd>
              </div>
              <div>
                <dt>영상 설명</dt>
                <dd>{job.video_description || '없음'}</dd>
              </div>
            </dl>
          )}
        </section>
        {isFaceSwap ? (
          <section className="text-panel" aria-label="얼굴 합성 작업">
            <h2>얼굴 합성</h2>
            <p>
              영상을 최대 10분 구간으로 나누어 순서대로 합성한 뒤, 연결과 최종 인코딩을 진행합니다.
            </p>
            {job?.metadata.faceswap_chunks && (
              <p>
                합성 구간 {job.metadata.faceswap_chunks.completed} /{' '}
                {job.metadata.faceswap_chunks.total} 완료 · 재시도 시 완료 구간 재사용
              </p>
            )}
            <p>완료된 영상을 새 원본으로 등록하면 자막 작업을 이어서 시작할 수 있습니다.</p>
            {job && !['COMPLETED', 'FAILED', 'CANCELLED'].includes(job.status) && (
              <Button
                variant="secondary"
                disabled={actionBusy || !!job.metadata.cancel_requested}
                onClick={() => void faceSwapAction('cancel')}
              >
                {job.metadata.cancel_requested ? '취소 중…' : '합성 취소'}
              </Button>
            )}
            {job && ['FAILED', 'CANCELLED'].includes(job.status) && (
              <Button
                variant="secondary"
                disabled={actionBusy}
                onClick={() => void faceSwapAction('retry')}
              >
                합성 재시도
              </Button>
            )}
          </section>
        ) : (
          <section className="text-panel" aria-label="전사록과 번역 자막">
            <div className="tabs" role="tablist" aria-label="자막 종류">
              {(
                [
                  ['original', '전사록'],
                  ['translated', '번역 자막'],
                ] as const
              ).map(([value, label]) => (
                <Button
                  variant="secondary"
                  id={`tab-${value}`}
                  key={value}
                  role="tab"
                  aria-selected={tab === value}
                  aria-controls="cue-panel"
                  tabIndex={tab === value ? 0 : -1}
                  onClick={() => setTab(value)}
                  onKeyDown={(e) => {
                    if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) {
                      e.preventDefault();
                      const next =
                        e.key === 'Home'
                          ? 'original'
                          : e.key === 'End'
                            ? 'translated'
                            : tab === 'original'
                              ? 'translated'
                              : 'original';
                      setTab(next);
                      document.getElementById(`tab-${next}`)?.focus();
                    }
                  }}
                >
                  {label}
                </Button>
              ))}
            </div>
            {track?.partial && (
              <p className="ticket-partial" role="status">
                일부 결과 · 티켓 전체 완료를 뜻하지 않습니다.
              </p>
            )}
            {job && !['COMPLETED', 'AWAITING_REVIEW'].includes(job.status) && (
              <p className="ticket-note">
                읽기 전용 미리보기 · 현재 상태에서는 자막 편집을 제공하지 않습니다.
              </p>
            )}
            <div className="cue-toolbar">
              <TextField
                label="자막 검색"
                prefix={<Search size={16} aria-hidden="true" />}
                value={query}
                onValueChange={setQuery}
                placeholder="대사에서 검색"
                clearable
              />
              <span>
                {track?.available
                  ? `${cues.length}개${track.partial ? ' · 일부 결과' : ''}`
                  : '자막 개수 미확인'}
              </span>
            </div>
            <div
              id="cue-panel"
              role="tabpanel"
              aria-labelledby={`tab-${tab}`}
              className="cue-panel"
              tabIndex={0}
            >
              {track?.available ? (
                cues.length ? (
                  cues.map((cue, index) => (
                    <Button
                      variant="secondary"
                      className={
                        'preview-cue ' + (time >= cue.start && time < cue.end ? 'current' : '')
                      }
                      key={`${cue.start}-${index}`}
                      disabled={!videoAvailable || videoError}
                      onClick={() => seek(cue)}
                      aria-label={`${timestamp(cue.start)} ${cue.text}`}
                    >
                      <time>{timestamp(cue.start)}</time>
                      <span>{cue.text}</span>
                    </Button>
                  ))
                ) : (
                  <div className="text-empty">
                    <FileText size={28} />
                    <p>{query ? '검색 결과가 없습니다.' : '저장된 대사가 없습니다.'}</p>
                  </div>
                )
              ) : (
                <div className="text-empty">
                  <FileText size={28} />
                  <p>
                    {preview?.expired
                      ? '자막 보관 기간이 만료되었습니다.'
                      : tab === 'original'
                        ? '전사 결과를 기다리고 있습니다.'
                        : '번역 결과를 기다리고 있습니다.'}
                  </p>
                </div>
              )}
            </div>
            {job?.status === 'COMPLETED' && !preview?.expired && track?.available && (
              <div className="text-download">
                <Button variant="primary" title="최종 자막 편집" onClick={() => setEditing(true)}>
                  <Pencil size={18} />
                  자막 수정
                </Button>
                <a
                  className="download"
                  href={`${base}/jobs/${id}/results/${tab === 'original' ? 'original' : 'translated'}.srt`}
                >
                  <Download size={16} />
                  {tab === 'original' ? '원문 SRT' : '번역 SRT'}
                </a>
              </div>
            )}
          </section>
        )}
      </div>
      {editing && job && (
        <SubtitleEditor
          job={job}
          initialTrack={tab}
          onClose={() => setEditing(false)}
          onRendered={() => setReload((n) => n + 1)}
        />
      )}
      <dialog
        className="confirm-modal promotion-modal"
        ref={promotionDialog}
        onCancel={(e) => {
          if (promoting) {
            e.preventDefault();
          }
        }}
      >
        <h2>결과 영상을 새 원본으로 등록할까요?</h2>
        <p>
          가공된 영상의 복사본이 원본 보관함에 추가됩니다. 기존 작업과 자막은 그대로 유지되며,
          복사본만큼 저장 공간을 사용합니다.
        </p>
        {promotionError && (
          <p role="alert" className="alert">
            {promotionError}
          </p>
        )}
        <div>
          <Button
            variant="secondary"
            autoFocus
            disabled={promoting}
            onClick={() => promotionDialog.current?.close()}
          >
            취소
          </Button>
          <Button variant="secondary" disabled={promoting} onClick={() => void promote()}>
            {promoting ? '등록 중…' : '새 원본 등록'}
          </Button>
        </div>
      </dialog>
    </main>
  );
};
