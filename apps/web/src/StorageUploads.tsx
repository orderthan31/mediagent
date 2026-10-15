import { Pause, Play, Trash2, X } from 'lucide-react';
import { type UploadItem } from './upload-queue';
import { type VideoUpload, sizeLabel } from './video-api';
import { Badge } from './hangyeol/primitives/badge';
import { Progress } from './hangyeol/primitives/progress';
import { Button } from './hangyeol/primitives/button';
import { EmptyState } from './hangyeol/components/empty-state';

const uploadLabel = (item: UploadItem) => {
  if (item.state === 'uploading' && item.progress === item.size) {
    return '영상 확인 및 등록 중';
  }
  return {
    waiting: '전송 대기',
    uploading: '전송 중',
    paused: '일시정지',
    error: '실패',
    done: '완료',
  }[item.state];
};
const uploadSize = (value: number) =>
  value < 1024
    ? `${value} B`
    : value < 1024 ** 2
      ? `${(value / 1024).toFixed(1)} KB`
      : sizeLabel(value);
const percentage = (value: number, max: number) =>
  max > 0 ? `${Math.floor((value / max) * 100)}%` : '진행률 미확인';

type Props = {
  uploads: UploadItem[];
  sessions: VideoUpload[];
  online: boolean;
  busy: string;
  onPause: (key: string) => void;
  onResume: (key: string) => void;
  onRemove: (key: string) => void;
  onRegister: (id: string) => void;
  onChooseResume: (id: string) => void;
  onDeleteSession: (session: VideoUpload) => void;
};
export const StorageUploads = ({
  uploads,
  sessions,
  online,
  busy,
  onPause,
  onResume,
  onRemove,
  onRegister,
  onChooseResume,
  onDeleteSession,
}: Props) => (
  <section className="storage-upload-shelf" aria-labelledby="storage-upload-title">
    <div className="storage-section-heading">
      <h2 id="storage-upload-title">업로드</h2>
      <span>
        {online || uploads.length + sessions.length > 0
          ? `${uploads.length + sessions.length}개 표시`
          : '저장된 업로드 확인 필요'}
      </span>
    </div>
    {(uploads.length > 0 || sessions.length > 0) && (
      <p className="storage-section-description">
        파일은 순서대로 전송돼요. 중단된 업로드는 같은 원본 파일을 선택해 이어갈 수 있어요.
      </p>
    )}
    {!online && (
      <p className="storage-upload-notice">서버에 저장된 업로드 정보는 최신이 아닐 수 있어요.</p>
    )}
    {!uploads.length && !sessions.length && (
      <EmptyState
        className="storage-upload-empty"
        heading={
          online ? '진행 중인 업로드가 없습니다.' : '저장된 업로드 정보가 확인되지 않았어요.'
        }
        description={
          online
            ? '위의 영상 업로드에서 파일을 선택해 시작하세요.'
            : '서버 연결을 확인해 주세요. 새 파일 선택은 계속 사용할 수 있어요.'
        }
      />
    )}
    <div className="storage-upload-list">
      {uploads.map((item) => (
        <article className="storage-upload" key={item.key} aria-label={item.name}>
          <div className="storage-upload-heading">
            <h3>{item.name}</h3>
            <Badge
              tone={
                item.state === 'error'
                  ? 'danger'
                  : ['uploading', 'done'].includes(item.state)
                    ? 'info'
                    : 'neutral'
              }
            >
              {uploadLabel(item)}
            </Badge>
          </div>
          <p className="storage-upload-meta">
            {percentage(item.progress, item.size)} · {uploadSize(item.progress)} /{' '}
            {uploadSize(item.size)}
          </p>
          <Progress label={`전송 진행: ${item.name}`} value={item.progress} max={item.size} />
          {item.state === 'waiting' && (
            <p className="storage-upload-help">앞선 전송이 끝나면 순서대로 시작해요.</p>
          )}
          {item.error && (
            <p role="alert" className="storage-upload-error">
              {item.error}
            </p>
          )}
          <div className="storage-upload-actions">
            {item.state !== 'done' && (
              <Button
                variant="secondary"
                size="small"
                aria-label={`${item.state === 'error' ? '업로드 재시도' : item.state === 'paused' ? '업로드 재개' : '업로드 일시정지'}: ${item.name}`}
                onClick={() =>
                  ['paused', 'error'].includes(item.state) ? onResume(item.key) : onPause(item.key)
                }
              >
                {['paused', 'error'].includes(item.state) ? (
                  <Play size={16} aria-hidden="true" />
                ) : (
                  <Pause size={16} aria-hidden="true" />
                )}
                {item.state === 'error' ? '재시도' : item.state === 'paused' ? '재개' : '일시정지'}
              </Button>
            )}
            <Button
              variant="quiet"
              size="small"
              aria-label={`업로드 제거: ${item.name}`}
              onClick={() => onRemove(item.key)}
            >
              <X size={16} aria-hidden="true" />
              목록에서 제거
            </Button>
          </div>
        </article>
      ))}
      {sessions.map((session) => (
        <article className="storage-upload" key={session.upload_id} aria-label={session.filename}>
          <div className="storage-upload-heading">
            <h3>{session.filename}</h3>
            <Badge tone={session.status === 'READY' ? 'info' : 'neutral'}>
              {session.status === 'READY' ? '등록 대기' : '업로드 미완료'}
            </Badge>
          </div>
          <p className="storage-upload-meta">
            {percentage(session.uploaded_bytes, session.expected_size)} ·{' '}
            {uploadSize(session.uploaded_bytes)} / {uploadSize(session.expected_size)}
          </p>
          <Progress
            label={`저장된 업로드 진행: ${session.filename}`}
            value={session.uploaded_bytes}
            max={session.expected_size}
          />
          <p className="storage-upload-help">
            {session.status === 'READY'
              ? '전송된 파일의 영상 등록을 다시 시도할 수 있어요.'
              : '같은 원본 파일을 선택하면 저장된 위치부터 이어서 전송해요.'}
          </p>
          <div className="storage-upload-actions">
            <Button
              variant="secondary"
              size="small"
              loading={busy === session.upload_id}
              aria-label={`${session.status === 'READY' ? '영상 등록 재시도' : '파일 선택 후 업로드 재개'}: ${session.filename}`}
              onClick={() =>
                session.status === 'READY'
                  ? onRegister(session.upload_id)
                  : onChooseResume(session.upload_id)
              }
            >
              <Play size={16} aria-hidden="true" />
              {session.status === 'READY' ? '등록 재시도' : '파일 선택 후 재개'}
            </Button>
            <Button
              variant="quiet"
              size="small"
              className="storage-delete"
              aria-label={`업로드 삭제: ${session.filename}`}
              onClick={() => onDeleteSession(session)}
            >
              <Trash2 size={16} aria-hidden="true" />
              업로드 삭제
            </Button>
          </div>
        </article>
      ))}
    </div>
  </section>
);
