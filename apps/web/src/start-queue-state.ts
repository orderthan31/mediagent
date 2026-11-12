export type StartQueueJob = {
  job_id: string;
  ticket_number: string;
  original_filename: string | null;
  workflow_name: string | null;
  status: 'QUEUED';
  access: { can_manage: boolean };
};
export type StartQueueSnapshot = {
  revision: number;
  paused: boolean;
  order: string[];
  jobs: string[];
  details: StartQueueJob[];
  progression?: 'checking' | 'ready' | 'unconfirmed' | 'disabled';
};
const id = /^[a-f0-9]{32}$/;
export const checkedStartQueue = (value: StartQueueSnapshot) => {
  if (
    !value ||
    !Number.isSafeInteger(value.revision) ||
    value.revision < 0 ||
    typeof value.paused !== 'boolean' ||
    (value.progression !== undefined &&
      !['checking', 'ready', 'unconfirmed', 'disabled'].includes(value.progression)) ||
    !Array.isArray(value.jobs) ||
    value.jobs.length > 1000 ||
    value.jobs.some((key) => typeof key !== 'string' || !id.test(key)) ||
    new Set(value.jobs).size !== value.jobs.length ||
    !Array.isArray(value.order) ||
    value.order.length > 1000 ||
    new Set(value.order).size !== value.order.length ||
    value.order.some((key) => !value.jobs.includes(key)) ||
    !Array.isArray(value.details) ||
    value.details.length !== value.jobs.length ||
    value.details.some(
      (job, index) =>
        !job ||
        job.job_id !== value.jobs[index] ||
        typeof job.ticket_number !== 'string' ||
        (job.original_filename !== null && typeof job.original_filename !== 'string') ||
        (job.workflow_name !== null && typeof job.workflow_name !== 'string') ||
        job.status !== 'QUEUED' ||
        typeof job.access?.can_manage !== 'boolean',
    )
  ) {
    throw new Error('대기열 응답을 확인하지 못했습니다.');
  }
  return value;
};
