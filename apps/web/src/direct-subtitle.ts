import { readSrtFile, maxSrtFileBytes } from './normal-inputs';
import { parseSmiInput } from './smi-input';
import {
  copyTextIssue,
  copyTimeMilliseconds,
  cueCopyText,
  parseSrtCopy,
  serializeSrtCopy,
  type SrtCopyDocument,
} from './srt-copy';

export type DirectCueEdit = { text?: string; start?: string; end?: string };
export type DirectEdits = Readonly<Record<number, DirectCueEdit>>;
export type SubtitleFormat = 'srt' | 'smi';
export const readDirectSrt = async (file: Pick<File, 'name' | 'size' | 'arrayBuffer'>) => {
  if (!file.name.toLowerCase().endsWith('.srt') || file.size < 1 || file.size > maxSrtFileBytes) {
    throw new Error('UTF-8 SRT 파일을 선택하세요 (1 byte~16MiB).');
  }
  return parseSrtCopy(new TextEncoder().encode(await readSrtFile(file)));
};
export const readDirectSubtitle = async (file: Pick<File, 'name' | 'size' | 'arrayBuffer'>) => {
  if (file.name.toLowerCase().endsWith('.srt')) {
    return readDirectSrt(file);
  }
  if (!/\.(smi|sami)$/i.test(file.name)) {
    throw new Error('UTF-8 SRT·SMI·SAMI 파일을 선택하세요.');
  }
  if (file.size < 1 || file.size > maxSrtFileBytes) {
    throw new Error('자막 파일은 1 byte~16MiB여야 합니다.');
  }
  return parseSmiInput(new Uint8Array(await file.arrayBuffer()));
};

export const directCueValue = (document: SrtCopyDocument, edits: DirectEdits, index: number) => {
  const cue = document.cues[index];
  const [start, end] = cue.clock.split(' --> ');
  return { text: cueCopyText(cue), start, end, ...edits[index] };
};
export const directCueIssues = (value: { text: string; start: string; end: string }) => {
  const start = copyTimeMilliseconds(value.start),
    end = copyTimeMilliseconds(value.end);
  return {
    text: copyTextIssue(value.text),
    start: start === null ? 'HH:MM:SS,mmm 형식으로 입력하세요.' : '',
    end:
      end === null
        ? 'HH:MM:SS,mmm 형식으로 입력하세요.'
        : start !== null && end <= start
          ? '종료는 시작보다 늦어야 합니다.'
          : '',
  };
};
export const directSmiIssue = (document: SrtCopyDocument, edits: DirectEdits) => {
  let previousEnd = 0;
  for (let index = 0; index < document.cues.length; index++) {
    const value = directCueValue(document, edits, index);
    const start = copyTimeMilliseconds(value.start),
      end = copyTimeMilliseconds(value.end);
    if (start === null || end === null || end <= start) {
      return '시작·종료 시각을 확인하세요.';
    }
    if (start < previousEnd) {
      return 'SMI는 겹치거나 순서가 뒤바뀐 시각을 표현할 수 없습니다. SRT로 받거나 시각을 직접 조정하세요.';
    }
    previousEnd = end;
  }
  return '';
};
const escapeSmiText = (value: string) =>
  value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
    .replace(/\u00a0/g, '&nbsp;');

export const serializeDirectSubtitle = (
  document: SrtCopyDocument,
  edits: DirectEdits,
  format: SubtitleFormat,
): Uint8Array => {
  const texts: Record<number, string> = {},
    clocks: Record<number, string> = {};
  for (let index = 0; index < document.cues.length; index++) {
    const value = directCueValue(document, edits, index);
    const issue = Object.values(directCueIssues(value)).find(Boolean);
    if (issue) {
      throw new Error(`자막 ${document.cues[index].id}: ${issue}`);
    }
    if (edits[index]?.text !== undefined) {
      texts[index] = value.text;
    }
    if (edits[index]?.start !== undefined || edits[index]?.end !== undefined) {
      clocks[index] = `${value.start} --> ${value.end}`;
    }
  }
  if (format === 'srt') {
    return serializeSrtCopy(document, texts, clocks);
  }
  if (format !== 'smi') {
    throw new Error('SRT 또는 SMI를 선택하세요.');
  }
  const issue = directSmiIssue(document, edits);
  if (issue) {
    throw new Error(issue);
  }
  // Match the existing SAMI producer's ordered millisecond events and clear markers.
  const events = new Map<number, string>([[0, '']]);
  for (let index = 0; index < document.cues.length; index++) {
    const value = directCueValue(document, edits, index);
    events.set(copyTimeMilliseconds(value.start)!, value.text);
    events.set(copyTimeMilliseconds(value.end)!, '');
  }
  const body = [...events]
    .sort(([a], [b]) => a - b)
    .map(
      ([at, text]) =>
        `<SYNC Start="${at}"><P Class="SUBTTL">${text ? text.split('\n').map(escapeSmiText).join('<BR>') : '&nbsp;'}</P></SYNC>`,
    )
    .join('');
  const bytes = new TextEncoder().encode(
    `<SAMI><HEAD><TITLE>Subtitles</TITLE><META http-equiv="Content-Type" content="text/html; charset=utf-8"><STYLE TYPE="text/css">.SUBTTL { Name: Subtitles; lang: und; SAMIType: CC; }</STYLE></HEAD><BODY>${body}</BODY></SAMI>\n`,
  );
  if (bytes.byteLength > maxSrtFileBytes) {
    throw new Error('수정본은 16MiB 이내여야 합니다.');
  }
  return bytes;
};

export const directDownloadName = (name: string, format: SubtitleFormat) =>
  (name.replace(/\.(srt|smi|sami)$/i, '').replace(/[\\/:*?"<>|\u0000-\u001f]/g, '_') || '자막') +
  '-수정본.' +
  format;
export const downloadDirectSubtitle = (
  name: string,
  document: SrtCopyDocument,
  edits: DirectEdits,
  format: SubtitleFormat,
) => {
  const bytes = serializeDirectSubtitle(document, edits, format);
  const url = URL.createObjectURL(
    new Blob([new Uint8Array(bytes).buffer], {
      type:
        format === 'srt'
          ? 'application/x-subrip;charset=utf-8'
          : 'application/x-sami;charset=utf-8',
    }),
  );
  const anchor = window.document.createElement('a');
  anchor.href = url;
  anchor.download = directDownloadName(name, format);
  window.document.body.append(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
};
