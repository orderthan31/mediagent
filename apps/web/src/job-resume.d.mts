export type ResumeJobSnapshot = {
  id: string;
  revision: number;
  status: string;
  access?: { can_manage: boolean };
  cancel_requested?: boolean;
  runs: {
    id: string;
    status: string;
    result?: { unit_recovery?: { id?: string }; [key: string]: unknown } | null;
  }[];
  reviews?: { status: string }[];
};
export type ResumeRequest = <T = ResumeJobSnapshot>(path: string, init?: RequestInit) => Promise<T>;
export function resumeProof(job: unknown): string | null;
export function resumeAttempt(job: unknown): 'checking' | 'uncertain' | 'sent' | null;
export function inspectResume(jobId: string, request: ResumeRequest): Promise<ResumeJobSnapshot>;
export function resumeExistingJob(
  job: ResumeJobSnapshot,
  request: ResumeRequest,
  isCurrent?: () => boolean,
): Promise<{
  state: 'blocked' | 'stale' | 'sent' | 'uncertain' | 'read-error';
  job?: ResumeJobSnapshot;
}>;

export function continuePreparedRecovery(
  view: {
    job_id: string;
    run_id: string;
    job_revision: number;
    recovery_revision: number;
    context_sha256: string;
    access: { can_manage: boolean };
    recovery: { id: string; request_id: string; can_continue: boolean } | null;
  },
  request: ResumeRequest,
  isCurrent?: () => boolean,
): Promise<{ state: 'blocked' | 'stale' | 'sent' | 'uncertain' | 'read-error' }>;
