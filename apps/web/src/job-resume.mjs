// Same-job dispatch only. Receipt presence is a UI gate, not claim authority.
const attempts = new Map();
const identifier = (value) => typeof value === 'string' && /^[A-Za-z0-9_-]+$/.test(value);
export function resumeProof(job) {
  if (
    !identifier(job?.id) ||
    !Number.isSafeInteger(job.revision) ||
    job.revision < 0 ||
    job.access?.can_manage !== true ||
    !['running', 'waiting'].includes(job.status) ||
    job.cancel_requested === true ||
    !Array.isArray(job.runs) ||
    !job.runs.length ||
    job.runs.some((run) => !identifier(run?.id) || run.status !== 'completed') ||
    new Set(job.runs.map((run) => run.id)).size !== job.runs.length ||
    (job.reviews !== undefined &&
      (!Array.isArray(job.reviews) || job.reviews.some((review) => review?.status !== 'confirmed')))
  )
    return null;
  const receipts = job.runs
    .filter((run) => identifier(run.result?.unit_recovery?.id))
    .map((run) => [run.id, run.result.unit_recovery.id])
    .sort();
  if (!receipts.length) return null;
  return JSON.stringify([job.id, job.runs.map((run) => run.id).sort(), receipts]);
}
const attemptKey = (proof) => {
  return proof;
};
function recorded(key) {
  if (attempts.has(key)) return attempts.get(key);
  try {
    const value = globalThis.sessionStorage?.getItem(`job-resume:${key}`);
    return value === 'sent' || value === 'uncertain' ? value : null;
  } catch {
    return null;
  }
}
function record(key, state) {
  // Persist before sending so a page reload cannot turn a lost reply into a retry.
  // If browser storage exists but rejects writes, fail before dispatch.
  globalThis.sessionStorage?.setItem(`job-resume:${key}`, state);
  attempts.set(key, state);
}
export function resumeAttempt(job) {
  const proof = resumeProof(job);
  return proof ? recorded(attemptKey(proof)) : null;
}
export async function inspectResume(jobId, request) {
  if (!identifier(jobId)) throw Error('작업 식별자가 올바르지 않습니다.');
  const fresh = await request(`/renewal/jobs/${jobId}`);
  if (fresh?.id !== jobId) throw Error('조회한 작업이 현재 작업과 다릅니다.');
  return fresh;
}
export async function resumeExistingJob(job, request, isCurrent = () => true) {
  const proof = resumeProof(job);
  if (!proof) return { state: 'blocked' };
  const key = attemptKey(proof);
  if (recorded(key)) return { state: 'blocked' };
  attempts.set(key, 'checking');
  let submitted = false;
  try {
    const fresh = await inspectResume(job.id, request);
    if (!isCurrent() || resumeProof(fresh) !== proof || fresh.revision !== job.revision) {
      attempts.delete(key);
      return { state: 'stale', job: fresh };
    }
    // Lock before awaiting: double clicks, remounts and unclear replies cannot replay.
    record(key, 'uncertain');
    submitted = true;
    await request(`/renewal/jobs/${job.id}/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    });
    record(key, 'sent');
    return { state: 'sent' };
  } catch {
    if (!submitted) attempts.delete(key);
    return { state: submitted ? 'uncertain' : 'read-error' };
  }
}

// /unit-recovery/continue includes adoption AND downstream dispatch. It is never
// part of zero-call decision confirmation. Share the future run-frontier lock
// with ordinary /run so a lost continue response cannot be retried via that UI.
export async function continuePreparedRecovery(view, request, isCurrent = () => true) {
  if (
    !identifier(view?.job_id) ||
    !identifier(view?.run_id) ||
    !identifier(view?.recovery?.id) ||
    view.access?.can_manage !== true ||
    view.recovery.can_continue !== true ||
    !Number.isSafeInteger(view.job_revision) ||
    !Number.isSafeInteger(view.recovery_revision) ||
    typeof view.recovery.request_id !== 'string' ||
    !view.recovery.request_id ||
    !/^[a-f0-9]{64}$/.test(view.context_sha256)
  )
    return { state: 'blocked' };
  let key = null,
    submitted = false;
  try {
    const job = await inspectResume(view.job_id, request);
    const fresh = await request(`/renewal/jobs/${view.job_id}/runs/${view.run_id}/unit-recovery`);
    if (
      !isCurrent() ||
      job.revision !== view.job_revision ||
      fresh.job_id !== view.job_id ||
      fresh.run_id !== view.run_id ||
      fresh.job_revision !== view.job_revision ||
      fresh.recovery_revision !== view.recovery_revision ||
      fresh.context_sha256 !== view.context_sha256 ||
      fresh.access?.can_manage !== true ||
      fresh.recovery?.id !== view.recovery.id ||
      fresh.recovery.request_id !== view.recovery.request_id ||
      fresh.recovery.can_continue !== true
    )
      return { state: 'stale' };
    if (
      !Array.isArray(job.runs) ||
      !job.runs.some((run) => run.id === view.run_id && run.status === 'running')
    )
      return { state: 'blocked' };
    // This projection derives only the lock identity for the expected adoption;
    // it is never displayed or persisted as a fabricated server result.
    const frontier = {
      ...job,
      runs: job.runs.map((run) =>
        run.id === view.run_id
          ? { ...run, status: 'completed', result: { unit_recovery: { id: view.recovery.id } } }
          : run,
      ),
    };
    key = resumeProof(frontier);
    if (!key || recorded(key)) return { state: 'blocked' };
    record(key, 'uncertain');
    submitted = true;
    await request(`/renewal/jobs/${view.job_id}/runs/${view.run_id}/unit-recovery/continue`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ request_id: view.recovery.request_id }),
    });
    record(key, 'sent');
    return { state: 'sent' };
  } catch {
    if (key && !submitted) attempts.delete(key);
    return { state: submitted ? 'uncertain' : 'read-error' };
  }
}
