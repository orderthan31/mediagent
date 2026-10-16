import { useState } from 'react';
import { ChevronLeft, ChevronRight, FileVideo, Pause, Play, Trash2, X } from 'lucide-react';
import { type UploadItem } from './upload-queue';
import { type VideoUpload, sizeLabel } from './video-api';
import { Progress } from './hangyeol/primitives/progress';

const uploadLabel = (item: UploadItem) =>
  item.state === 'uploading' && item.progress === item.size
    ? '등록 중'
    : { waiting: '대기', uploading: '업로드 중', paused: '일시정지', error: '실패', done: '완료' }[
        item.state
      ];
const uploadSize = (value: number) =>
  value < 1024
    ? `${value} B`
    : value < 1024 ** 2
      ? `${(value / 1024).toFixed(1)} KB`
      : sizeLabel(value);
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
}: Props) => {
  const [selected, setSelected] = useState<string | null>(null);
  const entries = [
    ...uploads.filter((item) => item.state === 'uploading'),
    ...uploads.filter((item) => item.state !== 'uploading' && item.state !== 'done'),
    ...sessions,
    ...uploads.filter((item) => item.state === 'done'),
  ];
  const keyOf = (entry: UploadItem | VideoUpload) => ('key' in entry ? entry.key : entry.upload_id);
  const index = Math.max(
    0,
    entries.findIndex((entry) => keyOf(entry) === selected),
  );
  const entry = entries[index];
  if (!entry)
    return (
      <p className="upload-strip-empty" role="status">
        {online ? '진행 중인 업로드 없음' : '업로드 정보 확인 불가'}
      </p>
    );
  const item = 'key' in entry ? entry : null;
  const session = 'upload_id' in entry ? entry : null;
  const name = item ? item.name : session!.filename;
  const value = item ? item.progress : session!.uploaded_bytes;
  const max = item ? item.size : session!.expected_size;
  const percent = max > 0 ? Math.min(100, Math.max(0, Math.floor((value / max) * 100))) : null;
  const label = item ? uploadLabel(item) : session!.status === 'READY' ? '등록 대기' : '중단됨';
  const resume = item ? ['paused', 'error'].includes(item.state) : true;
  return (
    <div className="upload-strip-shell">
      <article className="upload-strip" aria-label={name}>
        <span className="upload-strip-video">
          <FileVideo size={25} aria-hidden="true" />
        </span>
        <div className="upload-strip-file">
          <strong title={name}>{name}</strong>
          <span>
            {label}
            {!online && ' · 최신 상태 미확인'}
          </span>
        </div>
        <div className="upload-strip-progress">
          <div>
            <span>
              {uploadSize(value)} / {uploadSize(max)}
            </span>
            <strong>{percent === null ? '—' : `${percent}%`}</strong>
          </div>
          <Progress
            label={`업로드 진행: ${name}`}
            value={max > 0 ? Math.min(value, max) : null}
            max={max}
          />
        </div>
        <div className="upload-strip-actions">
          {(!item || item.state !== 'done') && (
            <button
              type="button"
              className="ui02-icon"
              disabled={session ? busy === session.upload_id : false}
              aria-label={`${item ? (resume ? '업로드 재개' : '업로드 일시정지') : session!.status === 'READY' ? '영상 등록 재시도' : '파일 선택 후 재개'}: ${name}`}
              title={resume ? '재개' : '일시정지'}
              onClick={() =>
                item
                  ? resume
                    ? onResume(item.key)
                    : onPause(item.key)
                  : session!.status === 'READY'
                    ? onRegister(session!.upload_id)
                    : onChooseResume(session!.upload_id)
              }
            >
              {resume ? <Play size={16} /> : <Pause size={16} />}
            </button>
          )}
          <button
            type="button"
            className="ui02-icon"
            aria-label={`${item ? '업로드 목록에서 제거' : '업로드 삭제'}: ${name}`}
            title={item ? '목록에서 제거' : '업로드 삭제'}
            onClick={() => (item ? onRemove(item.key) : onDeleteSession(session!))}
          >
            {item ? <X size={16} /> : <Trash2 size={16} />}
          </button>
        </div>
      </article>
      {item?.error && (
        <p role="alert" className="upload-strip-error">
          {item.error}
        </p>
      )}
      {entries.length > 1 && (
        <nav className="upload-strip-pager" aria-label="다른 업로드">
          <button
            type="button"
            className="ui02-icon"
            aria-label="이전 업로드"
            disabled={index === 0}
            onClick={() => setSelected(keyOf(entries[index - 1]))}
          >
            <ChevronLeft size={15} />
          </button>
          <span>
            {index + 1} / {entries.length}
          </span>
          <button
            type="button"
            className="ui02-icon"
            aria-label="다음 업로드"
            disabled={index === entries.length - 1}
            onClick={() => setSelected(keyOf(entries[index + 1]))}
          >
            <ChevronRight size={15} />
          </button>
        </nav>
      )}
    </div>
  );
};
