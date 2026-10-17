import { useEffect, useRef, useState } from 'react';
import { Check, ClipboardCheck } from 'lucide-react';
import { request } from './api';
import { Button } from './hangyeol/primitives/button';
import { DataForm, ReviewMaterials } from './DataForm';
import { validateForm, type FormData, type FormIssue, type ReviewTask } from './form-contract';

const TaskForm = ({
  initial,
  onUpdated,
}: {
  initial: ReviewTask;
  onUpdated: (task: ReviewTask) => void;
}) => {
  const [task, setTask] = useState(initial);
  const [data, setData] = useState<FormData>(structuredClone(initial.data));
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [issues, setIssues] = useState<FormIssue[]>([]);
  const [notice, setNotice] = useState('');
  const [requestChanges, setRequestChanges] = useState(false);
  const [reason, setReason] = useState('');
  const pending = useRef(false);
  const confirmed = task.state === 'confirmed';
  const submit = async (action: 'save' | 'confirm' | 'request_changes' | 'reopen') => {
    if (pending.current) {
      return;
    }
    if ((action === 'confirm' || action === 'request_changes') && dirty) {
      setError('변경 내용을 먼저 저장해 주세요.');
      return;
    }
    if (action === 'confirm') {
      const found = validateForm(task.contract.fields, data);
      if (found.length) {
        setIssues(found);
        return;
      }
    }
    if (action === 'request_changes' && !reason.trim()) {
      setError('수정할 내용을 적어 주세요.');
      return;
    }
    pending.current = true;
    setBusy(action);
    setError('');
    setNotice('');
    try {
      const next = await request<ReviewTask>(`/publishing/reviews/${task.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action,
          revision: task.revision,
          contract_version: task.contract.version,
          data,
          reason,
        }),
      });
      setTask(next);
      setData(structuredClone(next.data));
      setDirty(false);
      setIssues([]);
      setRequestChanges(false);
      setReason('');
      setNotice(
        action === 'save'
          ? '저장됨'
          : action === 'confirm'
            ? '확인 완료 · 아직 실행 전'
            : action === 'reopen'
              ? '수정 중'
              : '수정 요청됨',
      );
      onUpdated(next);
    } catch (value) {
      setError(value instanceof Error ? value.message : '저장하지 못했습니다.');
    } finally {
      pending.current = false;
      setBusy('');
    }
  };
  return (
    <div className="generic-review-body">
      <ReviewMaterials materials={task.materials} />
      <div className="generic-review-form">
        <h3>{task.contract.title}</h3>
        {confirmed && (
          <p className="review-confirmed">
            <Check size={17} />
            확인 완료
          </p>
        )}
        {task.state === 'changes_requested' && <p className="alert">수정 요청 · {task.reason}</p>}
        <DataForm
          schema={task.contract.fields}
          value={data}
          disabled={confirmed || !!busy}
          onChange={(value) => {
            if (!value || typeof value !== 'object' || Array.isArray(value)) {
              return;
            }
            setData(value);
            setDirty(true);
            setIssues([]);
            setNotice('');
          }}
        />
        {issues.length > 0 && (
          <ul role="alert" className="review-form-errors">
            {issues.map((issue, index) => (
              <li key={`${issue.path}-${index}`}>{issue.message}</li>
            ))}
          </ul>
        )}
        {error && (
          <p className="alert" role="alert">
            {error}
          </p>
        )}
        {requestChanges && (
          <div className="review-change-reason">
            <label>
              수정할 내용
              <textarea
                value={reason}
                maxLength={1000}
                onChange={(event) => setReason(event.target.value)}
                rows={3}
              />
            </label>
          </div>
        )}
        <div className="review-action-bar">
          <span role="status">
            {dirty ? '미저장' : notice || (confirmed ? '확인 완료 · 아직 실행 전' : '확인 필요')}
          </span>
          {confirmed ? (
            <Button variant="secondary" disabled={!!busy} onClick={() => void submit('reopen')}>
              다시 수정
            </Button>
          ) : (
            <>
              {requestChanges ? (
                <>
                  <Button
                    variant="quiet"
                    disabled={!!busy}
                    onClick={() => setRequestChanges(false)}
                  >
                    취소
                  </Button>
                  <Button
                    variant="secondary"
                    disabled={!!busy || !reason.trim()}
                    loading={busy === 'request_changes'}
                    onClick={() => void submit('request_changes')}
                  >
                    수정 요청
                  </Button>
                </>
              ) : (
                <>
                  <Button variant="quiet" disabled={!!busy} onClick={() => setRequestChanges(true)}>
                    수정 요청
                  </Button>
                  <Button
                    variant="secondary"
                    disabled={!!busy || !dirty}
                    loading={busy === 'save'}
                    onClick={() => void submit('save')}
                  >
                    저장
                  </Button>
                  <Button
                    disabled={!!busy || dirty}
                    loading={busy === 'confirm'}
                    onClick={() => void submit('confirm')}
                  >
                    확정
                  </Button>
                </>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
};
export const GenericJobReview = ({ jobId }: { jobId: string }) => {
  const [tasks, setTasks] = useState<ReviewTask[]>([]);
  const [selected, setSelected] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const active = tasks.find((task) => task.id === selected) || tasks[0];
  const load = async (signal?: AbortSignal) => {
    setLoading(true);
    setError('');
    try {
      const result = await request<{ tasks: ReviewTask[] }>(`/publishing/jobs/${jobId}/reviews`, {
        signal,
      });
      if (!signal?.aborted) {
        setTasks(result.tasks);
      }
    } catch (value) {
      if (!signal?.aborted) {
        setError(value instanceof Error ? value.message : '검토할 자료를 불러오지 못했습니다.');
      }
    } finally {
      if (!signal?.aborted) {
        setLoading(false);
      }
    }
  };
  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [jobId]);
  return (
    <section className="generic-review" aria-label="검토">
      <div className="generic-review-heading">
        <ClipboardCheck size={21} />
        <h2>검토</h2>
        {!loading && !error && (
          <span>
            {tasks.filter((task) => task.state === 'confirmed').length} / {tasks.length} 확인
          </span>
        )}
      </div>
      {error && (
        <p className="alert" role="alert">
          {error}
          <Button variant="quiet" onClick={() => void load()}>
            다시 불러오기
          </Button>
        </p>
      )}
      {loading ? (
        <p role="status">자료 불러오는 중</p>
      ) : !error && active ? (
        <>
          {tasks.length > 1 && (
            <div className="review-task-tabs">
              {tasks.map((task) => (
                <button
                  type="button"
                  key={task.id}
                  aria-pressed={task.id === active.id}
                  onClick={() => setSelected(task.id)}
                >
                  {task.contract.title}
                  {task.state === 'confirmed' ? ' · 완료' : ''}
                </button>
              ))}
            </div>
          )}
          <TaskForm
            key={active.id}
            initial={active}
            onUpdated={(next) =>
              setTasks((previous) => previous.map((task) => (task.id === next.id ? next : task)))
            }
          />
        </>
      ) : (
        !error && <p>검토할 자료가 없습니다.</p>
      )}
    </section>
  );
};
