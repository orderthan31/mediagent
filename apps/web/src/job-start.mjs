/** One explicit click authorizes the displayed immutable job, never a background start. */
export async function startSavedJob(get, post, id, nonce) {
  const base = '/renewal/jobs/' + id;
  const current = await get(base);
  if (current.status !== 'draft' || current.runs?.length)
    throw new Error('이미 시작된 작업입니다. 현재 진행 상태를 확인해 주세요.');
  await post(base + '/prepare-start', {
    revision: current.revision,
    request_id: nonce + '-prepare',
  });
  const plan = await get(base + '/plan');
  if (!plan.ready) throw new Error(plan.reasons?.join(' ') || '작업 설정을 확인해 주세요.');
  const consent = await post(base + '/confirm', {
    token: plan.token,
    request_id: nonce + '-confirm',
  });
  await post(base + '/admit', { consent_id: consent.id, request_id: nonce + '-admit' });
  return post(base + '/run', {});
}
