import { type ReactNode } from 'react';
import { ArrowRight } from 'lucide-react';
import { mediaUrl } from './api';
import { durationLabel, sizeLabel, type VideoAsset } from './video-api';
import { Badge } from './hangyeol/primitives/badge';
import { FullVideoPreview } from './FullVideoPreview';
import { renewalBackend } from './preview';

const videoDuration = (video: VideoAsset) => {
  if (video.media_kind === 'subtitle') {
    return typeof video.media?.segments === 'number'
      ? `${video.media.segments}구간`
      : '구간 수 미확인';
  }
  if (video.media_kind === 'image') {
    return `${video.media?.width} × ${video.media?.height}`;
  }
  const duration = video.media?.duration;
  return duration !== undefined && Number.isFinite(duration) && duration >= 0
    ? durationLabel(duration)
    : '재생시간 미확인';
};

export const StorageAssetRow = ({
  video,
  thumbnail,
}: {
  video: VideoAsset;
  thumbnail: ReactNode;
}) => (
  <a className="asset-row storage-asset-row ui02-list-item" href={`#/videos/${video.asset_id}`}>
    {thumbnail}
    <div className="storage-asset-copy ui02-list-copy">
      <Badge tone={video.provenance.kind === 'result' ? 'info' : 'neutral'}>
        {video.provenance.kind === 'result'
          ? '결과에서 등록'
          : video.provenance.kind === 'preserved_legacy'
            ? '원본'
            : video.media_kind === 'image'
              ? '사진 원본'
              : video.media_kind === 'audio'
                ? '음성 원본'
                : video.media_kind === 'subtitle'
                  ? '자막 원본'
                  : '원본'}
      </Badge>
      <h2 className="ui02-list-title">{video.original_filename}</h2>
      <ul className="storage-metadata" aria-label="원본 정보">
        <li>{videoDuration(video)}</li>
        <li>{sizeLabel(video.size_bytes)}</li>
        <li>
          <time dateTime={video.created_at}>
            {new Date(video.created_at).toLocaleString('ko-KR')}
          </time>
        </li>
      </ul>
    </div>
    <span className="storage-open">
      {video.media_kind === 'image'
        ? '사진 열기'
        : video.media_kind === 'audio'
          ? '음성 열기'
          : video.media_kind === 'subtitle'
            ? '자막 열기'
            : '영상 열기'}{' '}
      <ArrowRight size={17} aria-hidden="true" />
    </span>
  </a>
);

export const StorageVideoInfo = ({ video, assetId }: { video: VideoAsset; assetId: string }) => (
  <section className="storage-video-info" aria-label="원본 정보">
    <div className="storage-preview">
      {!video.media_kind &&
        (video.web_preview && video.web_preview.status !== 'ready' ? (
          !renewalBackend ? (
            <p role="status">미리보기를 준비하고 있습니다.</p>
          ) : null
        ) : (
          <video
            controls
            playsInline
            preload="none"
            poster={mediaUrl(`/videos/${assetId}/thumbnail`)}
            src={mediaUrl(`/videos/${assetId}/stream`)}
          />
        ))}
      {video.web_preview?.excerpt_seconds && (
        <p role="note">
          미리보기는 앞부분 {video.web_preview.excerpt_seconds}초입니다. 전체 영상은 원본 받기를
          사용하세요.
        </p>
      )}
      {renewalBackend && !video.media_kind && (
        <FullVideoPreview resource={`/videos/${assetId}/preview/full`} />
      )}
    </div>
    <div className="storage-info">
      <h2>
        {video.media_kind === 'image'
          ? '사진 정보'
          : video.media_kind === 'audio'
            ? '음성 정보'
            : video.media_kind === 'subtitle'
              ? '자막 정보'
              : '영상 정보'}
      </h2>
      {video.media_kind === 'audio' && <a href={`#/start/audio/${assetId}`}>음성 전사 준비</a>}
      {video.media_kind === 'subtitle' && (
        <a href={`#/start?target=${assetId}`}>자막 작업 만들기</a>
      )}
      {renewalBackend && video.media_kind !== 'audio' && video.media_kind !== 'subtitle' && (
        <a
          href={`#/start/faceswap?${video.media_kind === 'image' ? 'photo' : 'target'}=${assetId}`}
        >
          얼굴 합성 입력 준비
        </a>
      )}
      <dl>
        <div>
          <dt>원본 업로더</dt>
          <dd style={{ overflowWrap: 'anywhere' }}>{video.uploaded_by || '기록 없음'}</dd>
        </div>
        <div>
          <dt>
            {video.media_kind === 'image'
              ? '사진 형식'
              : video.media_kind === 'subtitle'
                ? '자막 구간'
                : '재생시간'}
          </dt>
          <dd>{video.media_kind === 'image' ? video.media_type : videoDuration(video)}</dd>
        </div>
        <div>
          <dt>용량</dt>
          <dd>{sizeLabel(video.size_bytes)}</dd>
        </div>
        <div>
          <dt>
            {video.media_kind === 'audio'
              ? '음성 형식'
              : video.media_kind === 'subtitle'
                ? '자막 형식'
                : '해상도'}
          </dt>
          <dd>
            {video.media_kind === 'subtitle'
              ? video.media?.format?.toUpperCase()
              : video.media_kind === 'audio'
                ? `${video.media?.codec} · ${video.media?.sample_rate}Hz · ${video.media?.channels}채널`
                : video.media && (video.media.width || 0) > 0 && (video.media.height || 0) > 0
                  ? `${video.media.width} × ${video.media.height}`
                  : '미확인'}
          </dd>
        </div>
        <div>
          <dt>등록일</dt>
          <dd>
            <time dateTime={video.created_at}>
              {new Date(video.created_at).toLocaleString('ko-KR')}
            </time>
          </dd>
        </div>
        <div>
          <dt>등록 경로</dt>
          <dd>
            {video.provenance.kind === 'result'
              ? '결과 영상에서 등록'
              : video.provenance.kind === 'preserved_legacy'
                ? '파일 등록'
                : '파일 업로드'}
            {video.provenance.parent_asset_id && (
              <a href={`#/videos/${video.provenance.parent_asset_id}`}>이전 원본</a>
            )}
          </dd>
        </div>
      </dl>
      {(video.web_preview || !!video.media_kind) && (
        <nav className="storage-downloads" aria-label="원본 다운로드">
          <a href={mediaUrl(`/videos/${assetId}/download`)} download>
            원본 받기
          </a>
          {video.web_preview?.status === 'ready' && (
            <a href={mediaUrl(`/videos/${assetId}/stream?download=true`)} download>
              WebM 받기
            </a>
          )}
        </nav>
      )}
    </div>
  </section>
);
