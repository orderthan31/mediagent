import { useEffect, useRef, useState } from 'react';
import { Trash2, RefreshCw, FolderPlus, ArrowUpRight } from 'lucide-react';
import { executionRequest } from './execution-request';
import { PageTitle } from './PageTitle';
import { request, type Job } from './api';
import { frontendOnly } from './preview';
import { ticketNumber } from './job-identity';
import type { VideoAsset } from './video-api';
import type { JobPreview } from './job-execution';
import { JobExecutionCanvas } from './JobExecutionCanvas';
import { SubtitleEditor } from './SubtitleEditor';
import { TicketSummary } from './TicketSummary';
import { Button } from './hangyeol/primitives/button';
import './job-detail.css';
import './ticket.css';

export const JobDetail = ({
  id,
  labels,
  promotedAssetId,
}: {
  id: string;
  labels: Record<string, string>;
  promotedAssetId?: string;
}) => {
  const [job, setJob] = useState<Job | null>(null);
  const [preview, setPreview] = useState<JobPreview | null>(null);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  const [editing, setEditing] = useState(false);
  const [track, setTrack] = useState<'original' | 'translated'>('original');
  const [actionBusy, setActionBusy] = useState(false);
  const [promoting, setPromoting] = useState(false);
  const [promotionError, setPromotionError] = useState('');
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState('');
  const deletePending = useRef(false);
  const heading = useRef<HTMLHeadingElement>(null);
  const deleteDialog = useRef<HTMLDialogElement>(null);
  const promotionDialog = useRef<HTMLDialogElement>(null);
  const removeJob = async () => {
    if (deletePending.current || !job || !['COMPLETED', 'FAILED', 'CANCELLED'].includes(job.status))
      return;
    deletePending.current = true;
    setDeleting(true);
    setDeleteError('');
    try {
      await request(`/jobs/${id}`, { method: 'DELETE' });
      deleteDialog.current?.close();
      location.hash = '/jobs';
    } catch (reason) {
      setDeleteError(reason instanceof Error ? reason.message : '작업 삭제 실패');
    } finally {
      deletePending.current = false;
      setDeleting(false);
    }
  };
  const faceSwapAction = async (action: 'cancel' | 'retry') => {
    if (actionBusy) return;
    setActionBusy(true);
    setError('');
    try {
      if (action === 'retry') await executionRequest(`/jobs/${id}/retry`);
      else await request(`/jobs/${id}/cancel`, { method: 'POST' });
      setReload((value) => value + 1);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '요청 실패');
    } finally {
      setActionBusy(false);
    }
  };
  const promote = async () => {
    if (promoting) return;
    setPromoting(true);
    setPromotionError('');
    try {
      const asset = await request<VideoAsset>(`/jobs/${id}/promote-video`, { method: 'POST' });
      promotionDialog.current?.close();
      location.hash = `/videos/${asset.asset_id}`;
    } catch (reason) {
      setPromotionError(reason instanceof Error ? reason.message : '원본 등록 실패');
    } finally {
      setPromoting(false);
    }
  };
  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    const refresh = async () => {
      try {
        const next = await request<Job>(`/jobs/${id}`, { signal: controller.signal });
        // Legacy preview is optional for a typed execution snapshot. A non-video
        // job must not lose its entire detail screen because no video exists.
        const data = await request<JobPreview>(`/jobs/${id}/preview`, {
          signal: controller.signal,
        }).catch(() => null);
        if (!disposed) {
          setJob(next);
          setPreview(data);
          setError('');
        }
      } catch (reason) {
        if (!disposed) setError(reason instanceof Error ? reason.message : '작업 조회 실패');
      } finally {
        if (!disposed) timer = setTimeout(refresh, 5000);
      }
    };
    void refresh();
    return () => {
      disposed = true;
      controller.abort();
      clearTimeout(timer);
    };
  }, [id, reload]);
  useEffect(() => {
    heading.current?.focus();
  }, [id, job?.job_id]);
  const videoActions =
    job?.status === 'COMPLETED' && !preview?.expired ? (
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
    ) : undefined;
  return (
    <main className="job-detail ticket-detail job-detail-canvas">
      <PageTitle ref={heading} tabIndex={-1}>
        {job ? ticketNumber(job) : '작업 불러오는 중'}
      </PageTitle>
      <div className="job-detail-toolbar">
        {job && (
          <span className="job-source-context" title={job.original_filename}>
            {job.original_filename}
          </span>
        )}
        <div>
          {job && ['COMPLETED', 'FAILED', 'CANCELLED'].includes(job.status) && (
            <Button
              variant="quiet"
              onClick={() => {
                setDeleteError('');
                deleteDialog.current?.showModal();
              }}
            >
              <Trash2 size={16} />
              작업 삭제
            </Button>
          )}
          <Button
            variant="quiet"
            title="작업 새로고침"
            onClick={() => setReload((value) => value + 1)}
          >
            <RefreshCw size={16} />
            새로고침
          </Button>
        </div>
      </div>
      {error && (
        <p role="alert" className="alert">
          {error}
        </p>
      )}
      {job && (
        <>
          <TicketSummary
            job={job}
            labels={
              frontendOnly && job.status_message
                ? { ...labels, AWAITING_REVIEW: job.status_message }
                : labels
            }
          />
          <JobExecutionCanvas
            job={job}
            preview={preview}
            onEdit={(value) => {
              setTrack(value);
              setEditing(true);
            }}
            videoActions={videoActions}
            renderNodeActions={(type) =>
              type === 'faceswap' ? (
                <div className="execution-node-actions">
                  {job.metadata.faceswap_chunks && (
                    <p>
                      합성 구간 {job.metadata.faceswap_chunks.completed} /{' '}
                      {job.metadata.faceswap_chunks.total} 완료
                    </p>
                  )}
                  {!['COMPLETED', 'FAILED', 'CANCELLED'].includes(job.status) && (
                    <Button
                      variant="secondary"
                      disabled={actionBusy || !!job.metadata.cancel_requested}
                      onClick={() => void faceSwapAction('cancel')}
                    >
                      {job.metadata.cancel_requested ? '취소 중…' : '합성 취소'}
                    </Button>
                  )}
                  {['FAILED', 'CANCELLED'].includes(job.status) && (
                    <Button
                      variant="secondary"
                      disabled={actionBusy}
                      onClick={() => void faceSwapAction('retry')}
                    >
                      합성 재시도
                    </Button>
                  )}
                </div>
              ) : null
            }
          />
        </>
      )}
      {editing && job && (
        <SubtitleEditor
          job={job}
          initialTrack={track}
          onClose={() => setEditing(false)}
          onRendered={() => setReload((value) => value + 1)}
        />
      )}
      <dialog
        className="confirm-modal promotion-modal"
        ref={promotionDialog}
        onCancel={(event) => {
          if (promoting) event.preventDefault();
        }}
      >
        <h2>결과 영상을 새 원본으로 등록할까요?</h2>
        <p>
          가공된 영상의 복사본이 원본 보관함에 추가됩니다. 기존 작업과 자막은 유지되며 복사본만큼
          저장 공간을 사용합니다.
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
          <Button disabled={promoting} onClick={() => void promote()}>
            {promoting ? '등록 중…' : '새 원본 등록'}
          </Button>
        </div>
      </dialog>
      <dialog
        className="confirm-modal storage-confirm"
        ref={deleteDialog}
        aria-labelledby="job-delete-title"
        onCancel={(event) => {
          if (deleting) event.preventDefault();
        }}
      >
        <h2 id="job-delete-title">작업을 삭제할까요?</h2>
        <p>{job?.original_filename}</p>
        <p>작업과 결과 파일이 삭제됩니다. 이 작업은 되돌릴 수 없습니다.</p>
        {deleteError && (
          <p role="alert" className="alert">
            {deleteError}
          </p>
        )}
        <div>
          <Button
            variant="secondary"
            autoFocus
            disabled={deleting}
            onClick={() => deleteDialog.current?.close()}
          >
            취소
          </Button>
          <Button
            className="storage-confirm-delete"
            disabled={deleting}
            onClick={() => void removeJob()}
          >
            {deleting ? '삭제 중' : '삭제'}
          </Button>
        </div>
      </dialog>
    </main>
  );
};
