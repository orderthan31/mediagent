import type { Job } from './api';
import { templates } from './video-api';

// Human ticket numbers are supplied by the data source, never truncated UUIDs.
export const ticketNumber = (job: Pick<Job, 'job_id' | 'ticket_number'>) =>
  job.ticket_number || `#${job.job_id}`;
export const workflowName = (job: Pick<Job, 'metadata'>) =>
  job.metadata.workflow?.name ||
  templates[job.metadata.workflow?.template || 'full'] ||
  '워크플로우';
