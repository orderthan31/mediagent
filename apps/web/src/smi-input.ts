import { maxSrtFileBytes } from './normal-inputs';
import { copyTextIssue, maxCopyCues, parseSrtCopy } from './srt-copy';

const invalid = (message: string): never => {
  throw new Error(message);
};
const entities: Record<string, string> = {
  amp: '&',
  lt: '<',
  gt: '>',
  quot: '"',
  apos: "'",
  nbsp: '\u00a0',
  hellip: '…',
  ndash: '–',
  mdash: '—',
  copy: '©',
  reg: '®',
  trade: '™',
  lsquo: '‘',
  rsquo: '’',
  ldquo: '“',
  rdquo: '”',
  middot: '·',
  bull: '•',
};
const decodeText = (value: string) => {
  if (/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(value)) {
    invalid('SMI에 지원하지 않는 제어 문자가 있습니다.');
  }
  return value.replace(/&([^;\s&<>]+);/g, (_, entity: string) => {
    if (entity.startsWith('#')) {
      if (!/^#(?:[0-9]{1,7}|x[0-9a-f]{1,6})$/i.test(entity)) {
        return invalid('SMI 문자 엔티티를 확인하세요.');
      }
      const point =
        entity[1].toLowerCase() === 'x'
          ? parseInt(entity.slice(2), 16)
          : parseInt(entity.slice(1), 10);
      if (
        point > 0x10ffff ||
        (point >= 0xd800 && point <= 0xdfff) ||
        (point < 32 && ![9, 10, 13].includes(point))
      ) {
        return invalid('SMI 문자 엔티티를 확인하세요.');
      }
      return String.fromCodePoint(point);
    }
    const name = entity.toLowerCase();
    return Object.hasOwn(entities, name)
      ? entities[name]
      : invalid('지원하지 않는 SMI 문자 엔티티입니다. UTF-8 일반 문자로 저장해 주세요.');
  });
};
// Keep physical source layout separate from BR and decoded entity characters.
// decodeText rejects both marker characters in source/entities, preventing collisions.
const decodeCaptionSource = (value: string) =>
  value
    .split(/([ \t]*(?:\r\n|\r|\n)[ \t]*)/)
    .map((part, index) => (index % 2 ? '\u0001' : decodeText(part)))
    .join('');
const attributes = (value: string) => {
  const result: Record<string, string> = {};
  const pattern = /([a-z][a-z0-9_-]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+))/giy;
  let at = 0;
  while (at < value.length) {
    while (/\s/.test(value[at] || '') && at < value.length) {
      at++;
    }
    if (at === value.length) {
      break;
    }
    pattern.lastIndex = at;
    const match = pattern.exec(value);
    if (!match) {
      return invalid('SMI 태그의 속성을 확인하세요.');
    }
    const name = match[1].toLowerCase();
    if (name in result) {
      return invalid('SMI에 중복된 태그 속성이 있습니다.');
    }
    result[name] = decodeText(match[2] ?? match[3] ?? match[4]);
    at = pattern.lastIndex;
  }
  return result;
};
const allowAttributes = (attrs: Record<string, string>, allowed: string[]) => {
  if (Object.keys(attrs).some((name) => !allowed.includes(name))) {
    invalid('지원하지 않는 SMI 속성입니다. SYNC/P/BR 중심의 단순 자막으로 저장해 주세요.');
  }
};
const clock = (ms: number) =>
  `${Math.floor(ms / 3600000)
    .toString()
    .padStart(2, '0')}:${Math.floor((ms / 60000) % 60)
    .toString()
    .padStart(2, '0')}:${Math.floor((ms / 1000) % 60)
    .toString()
    .padStart(2, '0')},${(ms % 1000).toString().padStart(3, '0')}`;
type Event = { at: number; text: string; paragraph: boolean; track: string };

/** Plain single-track SAMI import. Tokens never enter DOM/HTML/CSS rendering. */
export const parseSmiInput = async (raw: Uint8Array) => {
  if (!raw.length || raw.length > maxSrtFileBytes) {
    return invalid('SMI 파일은 1 byte~16MiB여야 합니다.');
  }
  let text: string;
  try {
    text = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(raw);
  } catch {
    return invalid('SMI/SAMI 파일을 UTF-8로 저장한 뒤 다시 선택하세요.');
  }
  const events: Event[] = [];
  let root = false,
    body = false,
    seenBody = false,
    paragraph = false;
  let current: Event | undefined;
  let at = text.startsWith('\ufeff') ? 1 : 0;
  while (at < text.length) {
    if (text.startsWith('<!--', at)) {
      const end = text.indexOf('-->', at + 4);
      if (end === -1) {
        return invalid('SMI 주석이 닫히지 않았습니다.');
      }
      at = end + 3;
      continue;
    }
    if (text[at] !== '<') {
      const next = text.indexOf('<', at);
      const part = text.slice(at, next === -1 ? text.length : next);
      if (body && paragraph && current) {
        current.text += decodeCaptionSource(part);
      } else if (body && part.trim()) {
        return invalid('SMI 문구는 SYNC 안의 P 문단에 있어야 합니다.');
      } else if (!root && part.trim()) {
        return invalid('SAMI 형식의 자막 파일을 선택하세요.');
      }
      at = next === -1 ? text.length : next;
      continue;
    }
    let end = at + 1,
      quote = '';
    for (; end < text.length; end++) {
      const character = text[end];
      if (quote) {
        if (character === quote) {
          quote = '';
        }
      } else if (character === '"' || character === "'") {
        quote = character;
      } else if (character === '>') {
        break;
      }
    }
    if (end === text.length) {
      return invalid('SMI 태그가 닫히지 않았습니다.');
    }
    const token = text.slice(at + 1, end);
    at = end + 1;
    if (/^!doctype\s+sami\s*$/i.test(token) && !root) {
      continue;
    }
    const match = token.match(/^\s*(\/?)\s*([a-z][a-z0-9]*)\b([\s\S]*?)\s*$/i);
    if (!match) {
      return invalid('지원하지 않는 SMI 선언입니다. UTF-8 SAMI로 저장해 주세요.');
    }
    const closing = !!match[1],
      tag = match[2].toLowerCase();
    const attrs = attributes(match[3].replace(/\/\s*$/, ''));
    if (closing) {
      allowAttributes(attrs, []);
      if (tag === 'p' || tag === 'sync') {
        paragraph = false;
      } else if (tag === 'body' || tag === 'sami') {
        body = false;
        paragraph = false;
      } else if (!['head', 'title', 'style', 'b', 'i', 'u', 'font'].includes(tag)) {
        return invalid('지원하지 않는 SMI 태그입니다.');
      }
      continue;
    }
    if (tag === 'sami') {
      allowAttributes(attrs, []);
      if (root) {
        return invalid('SMI에는 하나의 SAMI 문서만 넣어 주세요.');
      }
      root = true;
      continue;
    }
    if (!root) {
      return invalid('SAMI 형식의 자막 파일을 선택하세요.');
    }
    if (tag === 'body') {
      allowAttributes(attrs, []);
      if (seenBody) {
        return invalid('SMI에는 하나의 BODY만 넣어 주세요.');
      }
      body = true;
      seenBody = true;
      continue;
    }
    if (!body) {
      if (['head', 'title'].includes(tag)) {
        allowAttributes(attrs, []);
      } else if (tag === 'style') {
        allowAttributes(attrs, ['type']);
      } else if (tag === 'meta') {
        allowAttributes(attrs, ['charset', 'http-equiv', 'content', 'name']);
        if (attrs['http-equiv'] && attrs['http-equiv'].toLowerCase() !== 'content-type') {
          return invalid('지원하지 않는 SMI META 선언입니다.');
        }
        const charset = attrs.charset || attrs.content?.match(/charset\s*=\s*([^;\s]+)/i)?.[1];
        if (charset && !/^utf-?8$/i.test(charset)) {
          return invalid('SMI/SAMI 파일을 UTF-8로 저장한 뒤 다시 선택하세요.');
        }
      } else {
        return invalid(
          '지원하지 않는 SMI 태그입니다. SYNC/P/BR 중심의 단순 자막으로 저장해 주세요.',
        );
      }
      continue;
    }
    if (tag === 'sync') {
      allowAttributes(attrs, ['start']);
      const start = attrs.start;
      if (!start || !/^[0-9]{1,12}$/.test(start) || Number(start) > 359999999999) {
        return invalid('SMI SYNC Start는 유효한 0 이상의 밀리초 정수여야 합니다.');
      }
      const time = Number(start);
      if (current && time <= current.at) {
        return invalid('SMI SYNC 시각은 중복 없이 오름차순이어야 합니다.');
      }
      current = { at: time, text: '', paragraph: false, track: '' };
      events.push(current);
      paragraph = false;
      if (events.length > 2 * maxCopyCues + 1) {
        return invalid('SMI 시각 항목이 너무 많습니다. 자막을 나누어 주세요.');
      }
    } else if (tag === 'p') {
      allowAttributes(attrs, ['class']);
      if (!current) {
        return invalid('SMI P 문단 앞에 SYNC Start가 필요합니다.');
      }
      if (current.paragraph) {
        return invalid('여러 언어·문단이 있는 SMI입니다. 한 언어만 선택해 내보낸 뒤 다시 여세요.');
      }
      if (attrs.class && !/^[a-z_][a-z0-9_-]{0,63}$/i.test(attrs.class)) {
        return invalid('지원하지 않는 SMI 자막 Class입니다.');
      }
      current.paragraph = true;
      current.track = attrs.class?.toLowerCase() || '';
      paragraph = true;
    } else if (tag === 'br' && paragraph && current) {
      allowAttributes(attrs, []);
      current.text += '\0';
    } else if (['b', 'i', 'u', 'font'].includes(tag) && paragraph) {
      allowAttributes(attrs, tag === 'font' ? ['color', 'size', 'face'] : []);
    } else {
      return invalid('지원하지 않는 SMI 태그입니다. SYNC/P/BR 중심의 단순 자막으로 저장해 주세요.');
    }
  }
  if (!root || !seenBody || !events.length) {
    return invalid('SYNC/P 시각과 문구가 있는 SAMI 파일이 필요합니다.');
  }
  const tracks = new Set<string>();
  const rows: { start: number; end: number; text: string }[] = [];
  for (let index = 0; index < events.length; index++) {
    const event = events[index];
    if (!event.paragraph) {
      return invalid('각 SMI SYNC에 P 문구 또는 빈 자막 표시(&nbsp;)가 필요합니다.');
    }
    const value = event.text
      .replace(/^\u0001+|\u0001+$/g, '')
      .replace(/\u0001*\0\u0001*/g, '\n')
      .replace(/\u0001+/g, ' ');
    const clear = !value.replace(/\u00a0/g, ' ').trim();
    if (event.track || !clear) {
      tracks.add(event.track);
    }
    if (tracks.size > 1) {
      return invalid('여러 언어가 있는 SMI입니다. 한 언어만 선택해 내보낸 뒤 다시 여세요.');
    }
    if (clear) {
      continue;
    }
    const issue = copyTextIssue(value);
    if (issue) {
      return invalid(`SMI ${rows.length + 1}번째 자막: ${issue}`);
    }
    const next = events[index + 1];
    if (!next) {
      return invalid(
        '마지막 자막의 종료 시각이 없습니다. 끝나는 SYNC 시각과 빈 자막 표시(&nbsp;)를 추가해 주세요.',
      );
    }
    rows.push({ start: event.at, end: next.at, text: value });
    if (rows.length > maxCopyCues) {
      return invalid('자막은 10000개 이내여야 합니다.');
    }
  }
  if (!rows.length) {
    return invalid('SMI 파일에 편집할 자막 문구가 없습니다.');
  }
  const srt =
    rows
      .map((row, index) => `${index + 1}\n${clock(row.start)} --> ${clock(row.end)}\n${row.text}`)
      .join('\n\n') + '\n';
  return parseSrtCopy(new TextEncoder().encode(srt));
};
