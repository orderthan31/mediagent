import { request } from './api';
import { parseSrtCopy } from './srt-copy';

export type SubtitleCopy = {
  id: string;
  filename: string;
  title: string;
  created_at: string;
  cue_count: number;
};
export type SubtitleCopySave = { id: string; filename: string; title: string; srt: string };
const identity = /^[a-f0-9]{32}$/;
const metadata = (value: SubtitleCopy) => {
  if (
    !value ||
    !identity.test(value.id) ||
    typeof value.filename !== 'string' ||
    !value.filename ||
    typeof value.title !== 'string' ||
    !value.title.trim() ||
    typeof value.created_at !== 'string' ||
    !Number.isFinite(Date.parse(value.created_at)) ||
    !Number.isInteger(value.cue_count) ||
    value.cue_count < 1 ||
    value.cue_count > 10000
  ) {
    throw new Error('저장된 자막 정보를 확인할 수 없습니다.');
  }
  return value;
};
export const getSubtitleCopy = async (id: string, signal?: AbortSignal) => {
  if (!identity.test(id)) {
    throw new Error('저장된 자막 주소를 확인하세요.');
  }
  const value = await request<SubtitleCopy & { srt: string; srt_sha256?: string }>(
    `/subtitle-copies/${id}`,
    { signal },
  );
  metadata(value);
  if (value.id !== id || typeof value.srt !== 'string') {
    throw new Error('저장된 자막 내용이 일치하지 않습니다.');
  }
  const document = await parseSrtCopy(new TextEncoder().encode(value.srt));
  if (document.cues.length !== value.cue_count) {
    throw new Error('저장된 자막 개수를 확인할 수 없습니다.');
  }
  return { ...value, document };
};
export const saveSubtitleCopy = async (body: SubtitleCopySave, signal?: AbortSignal) => {
  const saved = await request<SubtitleCopy>('/subtitle-copies', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  });
  metadata(saved);
  if (saved.id !== body.id) {
    throw new Error('저장 응답이 일치하지 않습니다. 저장된 자막 목록을 확인하세요.');
  }
  const readback = await getSubtitleCopy(body.id, signal);
  if (
    readback.srt !== body.srt ||
    readback.filename !== body.filename ||
    readback.title !== body.title
  ) {
    throw new Error('저장 결과가 일치하지 않습니다. 저장된 자막 목록을 확인하세요.');
  }
  return readback;
};
export const listSubtitleCopies = async (after?: string, signal?: AbortSignal) => {
  if (after && !identity.test(after)) {
    throw new Error('목록 주소를 확인하세요.');
  }
  const value = await request<{ copies: SubtitleCopy[]; next_cursor: string | null }>(
    '/subtitle-copies' + (after ? `?after=${after}` : ''),
    { signal },
  );
  if (
    !Array.isArray(value.copies) ||
    value.copies.length > 20 ||
    (value.next_cursor !== null &&
      (!identity.test(value.next_cursor) || value.next_cursor === after))
  ) {
    throw new Error('저장된 자막 목록을 확인할 수 없습니다.');
  }
  value.copies.forEach(metadata);
  return value;
};
