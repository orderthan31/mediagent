import { mediaUrl } from './api';
import { authenticatedFetch } from './auth-session';
import { maxSrtFileBytes, readSrtFile } from './normal-inputs';

// Same finite track/cue budgets as subtitle_tracks_v1 and selected timed inputs.
export const maxCopyCues = 10000;
export type SrtFileRun = {
  id: string;
  node_id: string;
  status: string;
  result?: { outputs: Record<string, { type: string }> } | null;
};
export type SrtCopySource = { jobId: string; runId: string; filename: string } & (
  { kind: 'artifact'; port: 'subtitles' } | { kind: 'track'; track: string }
);
const identity = /^[a-f0-9]{32}$/;
const trackName = /^(original|translated(?:\.[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*)?)$/;
export const artifactSrtSource = (
  base: string,
  run: SrtFileRun | undefined,
  port: string,
): SrtCopySource | null => {
  const jobId = base.match(/^\/renewal\/jobs\/([a-f0-9]{32})$/)?.[1];
  return jobId &&
    run &&
    identity.test(run.id) &&
    run.status === 'completed' &&
    port === 'subtitles' &&
    run.result?.outputs[port]?.type === 'subtitle'
    ? { kind: 'artifact', jobId, runId: run.id, port, filename: `${run.id}-${port}.srt` }
    : null;
};
export const trackSrtSource = (
  jobId: string,
  runId: string,
  track: string,
  extension: string,
  file: { filename: string; reference: { type: string } },
): SrtCopySource | null =>
  identity.test(jobId) &&
  identity.test(runId) &&
  trackName.test(track) &&
  extension === 'srt' &&
  file.reference.type === 'subtitle' &&
  file.filename === track + '.srt'
    ? { kind: 'track', jobId, runId, track, filename: file.filename }
    : null;
export const srtSourcePath = (source: SrtCopySource) => {
  if (!identity.test(source.jobId) || !identity.test(source.runId)) {
    throw new Error('자막 파일 정보를 다시 확인하세요.');
  }
  const root = `/renewal/jobs/${source.jobId}`;
  if (
    source.kind === 'artifact' &&
    source.port === 'subtitles' &&
    source.filename === `${source.runId}-subtitles.srt`
  ) {
    return `${root}/artifacts/${source.runId}/subtitles?download=true`;
  }
  if (
    source.kind === 'track' &&
    trackName.test(source.track) &&
    source.filename === source.track + '.srt'
  ) {
    return `${root}/subtitle-outputs/${source.runId}/${encodeURIComponent(source.track)}/srt`;
  }
  throw new Error('자막 파일 정보를 다시 확인하세요.');
};

export type CopyCue = {
  id: string;
  clock: string;
  start: number;
  end: number;
  from: number;
  to: number;
  text: string;
  clockFrom: number;
  clockTo: number;
  eols: string[];
  eol: string;
};
export type SrtCopyDocument = { raw: Uint8Array; text: string; cues: CopyCue[] };
const clockPattern = /^(\d{2,5}:[0-5]\d:[0-5]\d,\d{3}) --> (\d{2,5}:[0-5]\d:[0-5]\d,\d{3})$/;
// TranscriptSegment permits 1..128 Unicode characters (no C0 controls) or an
// integer. preserved_files writes that literal ID, without renumbering it.
const literalCueId = (id: string) =>
  id.length > 0 &&
  !/[\u0000-\u001f]/.test(id) &&
  (/^-?(?:0|[1-9][0-9]*)$/.test(id) || [...id].length <= 128);
const milliseconds = (stamp: string) => {
  const [hours, minutes, seconds, ms] = stamp.split(/[:,]/).map(Number);
  return ((hours * 60 + minutes) * 60 + seconds) * 1000 + ms;
};
export const copyTimeMilliseconds = (stamp: string): number | null =>
  /^\d{2,5}:[0-5]\d:[0-5]\d,\d{3}$/.test(stamp) ? milliseconds(stamp) : null;
export const cueCopyText = (cue: CopyCue) => cue.text.replace(/\r\n|\r/g, '\n');
export const copyTextIssue = (text: string) =>
  !text.trim()
    ? '문구를 입력하세요.'
    : text.split(/\r\n|\r|\n/).some((line) => /^[ \t]*$/.test(line))
      ? '문구 안의 빈 줄을 지워 주세요.'
      : '';

export const parseSrtCopy = async (raw: Uint8Array): Promise<SrtCopyDocument> => {
  if (!raw.byteLength) {
    throw new Error('자막 파일 내용이 없습니다.');
  }
  if (raw.byteLength > maxSrtFileBytes) {
    throw new Error('SRT 파일은 16MiB 이내여야 합니다.');
  }
  // Reuse the existing UTF-8/fatal/BOM and 16MiB file-read contract, without its input submission flow.
  const text = await readSrtFile({
    name: 'accepted.srt',
    size: raw.byteLength,
    arrayBuffer: async () => new Uint8Array(raw).buffer,
  });
  const lines: { value: string; from: number; to: number; eol: string }[] = [];
  const pattern = /([^\r\n]*)(\r\n|\r|\n|$)/gy;
  let at = text.startsWith('\ufeff') ? 1 : 0;
  while (at < text.length) {
    pattern.lastIndex = at;
    const line = pattern.exec(text)!;
    lines.push({ value: line[1], from: at, to: at + line[1].length, eol: line[2] });
    at = pattern.lastIndex;
  }
  const cues: CopyCue[] = [];
  const ids = new Set<string>();
  let index = 0;
  while (index < lines.length) {
    // A producer literal ID may contain only spaces. Its following clock line
    // distinguishes it from blank separators; preserve the ID without trimming.
    const candidate = lines[index].value;
    if (
      /^[ \t]*$/.test(candidate) &&
      !(literalCueId(candidate) && clockPattern.test(lines[index + 1]?.value || ''))
    ) {
      index++;
      continue;
    }
    const id = lines[index++].value;
    if (!literalCueId(id)) {
      throw new Error('번호·시각·문구가 있는 SRT 파일이 필요합니다.');
    }
    if (ids.has(id)) {
      throw new Error(`자막 ${id}: 번호가 중복되었습니다.`);
    }
    const clock = lines[index++];
    const match = clock?.value.match(clockPattern);
    if (!match || milliseconds(match[1]) >= milliseconds(match[2])) {
      throw new Error(`자막 ${id}: 시작·종료 시각을 확인하세요 (HH:MM:SS,mmm).`);
    }
    const first = index;
    while (index < lines.length && !/^[ \t]*$/.test(lines[index].value)) {
      if (clockPattern.test(lines[index].value)) {
        throw new Error(`자막 ${id}: 구간 사이의 빈 줄을 확인하세요.`);
      }
      index++;
    }
    if (first === index) {
      throw new Error(`자막 ${id}: 문구가 없습니다.`);
    }
    const from = lines[first].from,
      to = lines[index - 1].to;
    const value = text.slice(from, to);
    if (copyTextIssue(value)) {
      throw new Error(`자막 ${id}: 문구를 확인하세요.`);
    }
    cues.push({
      id,
      clock: clock.value,
      start: milliseconds(match[1]),
      end: milliseconds(match[2]),
      from,
      to,
      text: value,
      clockFrom: clock.from,
      clockTo: clock.to,
      eols: lines.slice(first, index - 1).map((line) => line.eol),
      eol: clock.eol,
    });
    ids.add(id);
    if (cues.length > maxCopyCues) {
      throw new Error('자막은 10000개 이내여야 합니다.');
    }
  }
  if (!cues.length) {
    throw new Error('시각과 문구가 있는 SRT 파일이 필요합니다.');
  }
  return { raw: new Uint8Array(raw), text, cues };
};

export const serializeSrtCopy = (
  document: SrtCopyDocument,
  edits: Readonly<Record<number, string>>,
  clocks: Readonly<Record<number, string>> = {},
): Uint8Array => {
  const parts: string[] = [];
  let from = 0,
    changed = false;
  for (const [index, cue] of document.cues.entries()) {
    const clock = clocks[index];
    if (clock !== undefined && clock !== cue.clock) {
      const match = clock.match(clockPattern);
      if (!match || milliseconds(match[1]) >= milliseconds(match[2])) {
        throw new Error(`자막 ${cue.id}: 시작·종료 시각을 확인하세요.`);
      }
      parts.push(document.text.slice(from, cue.clockFrom), clock);
      from = cue.clockTo;
      changed = true;
    }
    const value = edits[index];
    if (value === undefined || value === cueCopyText(cue)) {
      continue;
    }
    const issue = copyTextIssue(value);
    if (issue) {
      throw new Error(`자막 ${cue.id}: ${issue}`);
    }
    const lines = value.replace(/\r\n|\r/g, '\n').split('\n');
    const replacement = lines
      .map((line, i) => line + (i < lines.length - 1 ? cue.eols[i] || cue.eol : ''))
      .join('');
    parts.push(document.text.slice(from, cue.from), replacement);
    from = cue.to;
    changed = true;
  }
  if (!changed) {
    return new Uint8Array(document.raw);
  }
  parts.push(document.text.slice(from));
  const result = new TextEncoder().encode(parts.join(''));
  if (result.byteLength > maxSrtFileBytes) {
    throw new Error('수정본은 16MiB 이내여야 합니다.');
  }
  return result;
};

export const readSrtCopy = async (source: SrtCopySource, signal: AbortSignal) => {
  const response = await authenticatedFetch(mediaUrl(srtSourcePath(source)), {
    method: 'GET',
    signal,
    redirect: 'error',
  });
  if (!response.ok) {
    throw new Error('자막 파일을 불러오지 못했습니다. 원래 파일을 다시 확인해 주세요.');
  }
  const disposition = response.headers.get('content-disposition') || '';
  const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  const filename = encoded
    ? decodeURIComponent(encoded)
    : disposition.match(/filename="([^"]+)"/i)?.[1];
  if (
    filename !== source.filename ||
    !/^(text\/plain|application\/(x-subrip|srt))(?:;|$)/i.test(
      response.headers.get('content-type') || '',
    )
  ) {
    throw new Error('선택한 결과의 SRT 파일인지 확인할 수 없습니다.');
  }
  const size = response.headers.get('content-length');
  if (size !== null && (!/^\d+$/.test(size) || Number(size) > maxSrtFileBytes)) {
    throw new Error('SRT 파일은 16MiB 이내여야 합니다.');
  }
  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error('자막 파일 내용이 없습니다.');
  }
  const chunks: Uint8Array[] = [];
  let length = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }
      length += value.byteLength;
      if (length > maxSrtFileBytes) {
        throw new Error('SRT 파일은 16MiB 이내여야 합니다.');
      }
      chunks.push(value);
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
  const raw = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) {
    raw.set(chunk, offset);
    offset += chunk.length;
  }
  return parseSrtCopy(raw);
};

export const downloadSrtCopy = (
  source: SrtCopySource,
  document: SrtCopyDocument,
  edits: Readonly<Record<number, string>>,
) => {
  srtSourcePath(source);
  const bytes = serializeSrtCopy(document, edits);
  const blob = new Blob([new Uint8Array(bytes).buffer], {
    type: 'application/x-subrip;charset=utf-8',
  });
  const url = URL.createObjectURL(blob);
  const anchor = window.document.createElement('a');
  anchor.href = url;
  anchor.download = source.filename.replace(/\.srt$/i, '-수정본.srt');
  window.document.body.append(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
};
