import type { ReactNode } from 'react';
import { UnitRecoveryPanel } from './UnitRecoveryPanel';
import { executionStateLabel } from './job-execution-flow';

/** Selected-task actions only. Job-wide logs and files have separate owners. */
export const JobTaskInspector = ({
  jobId,
  runId,
  title,
  state,
  canManage,
  unitRecoveryEnabled,
  onChanged,
  toolbar,
  children,
}: {
  jobId: string;
  runId?: string;
  title: string;
  state: string;
  canManage: boolean;
  unitRecoveryEnabled: boolean;
  onChanged: () => void | Promise<void>;
  toolbar?: ReactNode;
  children: ReactNode;
}) => (
  <section className="job-task-inspector" aria-label="선택한 단계 상세">
    <header>
      <h3 tabIndex={-1}>{title}</h3>
      <span>{state === 'review_required' ? '검수 대기' : executionStateLabel(state)}</span>
    </header>
    {toolbar}
    {unitRecoveryEnabled && runId && (
      <UnitRecoveryPanel jobId={jobId} runId={runId} canManage={canManage} onChanged={onChanged} />
    )}
    {children}
  </section>
);
