import { type ReactNode } from 'react';
import { ArrowRight } from 'lucide-react';
import { mediaUrl } from './api';
import { durationLabel, sizeLabel, type VideoAsset } from './video-api';
import { Badge } from './hangyeol/primitives/badge';

const videoDuration = (video: VideoAsset) => {
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
        {video.provenance.kind === 'result' ? '결과에서 등록' : '업로드 원본'}
      </Badge>
      <h2 className="ui02-list-title">{video.original_filename}</h2>
      <ul className="storage-metadata" aria-label="영상 정보">
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
      영상 열기 <ArrowRight size={17} aria-hidden="true" />
    </span>
  </a>
);

export const StorageVideoInfo = ({ video, assetId }: { video: VideoAsset; assetId: string }) => (
  <section className="storage-video-info" aria-label="원본 영상 정보">
    <div className="storage-preview">
      {video.web_preview && video.web_preview.status !== 'ready' ? (
        <p role="status">웹 전용 WebM을 준비하지 못했습니다. 원본은 그대로 받을 수 있습니다.</p>
      ) : (
        <video
          controls
          playsInline
          preload="none"
          poster={mediaUrl(`/videos/${assetId}/thumbnail`)}
          src={mediaUrl(`/videos/${assetId}/stream`)}
        />
      )}
    </div>
    <div className="storage-info">
      <h2>영상 정보</h2>
      <dl>
        <div>
          <dt>재생시간</dt>
          <dd>{videoDuration(video)}</dd>
        </div>
        <div>
          <dt>용량</dt>
          <dd>{sizeLabel(video.size_bytes)}</dd>
        </div>
        <div>
          <dt>해상도</dt>
          <dd>
            {video.media && video.media.width > 0 && video.media.height > 0
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
            {video.provenance.kind === 'result' ? '결과 영상에서 등록' : '파일 업로드'}
            {video.provenance.parent_asset_id && (
              <a href={`#/videos/${video.provenance.parent_asset_id}`}>이전 원본</a>
            )}
          </dd>
        </div>
      </dl>
      {video.web_preview && (
        <nav className="storage-downloads" aria-label="영상 다운로드">
          <a href={mediaUrl(`/videos/${assetId}/download`)} download>
            원본 받기
          </a>
          {video.web_preview.status === 'ready' && (
            <a href={mediaUrl(`/videos/${assetId}/stream?download=true`)} download>
              WebM 받기
            </a>
          )}
        </nav>
      )}
    </div>
  </section>
);
