import { useEffect, useRef, useState } from 'react';
import { PageTitle } from './PageTitle';
import { Button } from './hangyeol/primitives/button';
import { Input } from './hangyeol/primitives/input';
import { Textarea } from './hangyeol/primitives/textarea';
import { Pagination, usePagination } from './Pagination';
import {
  directCueIssues,
  directCueValue,
  directSmiIssue,
  downloadDirectSubtitle,
  readDirectSrt,
  type DirectCueEdit,
  type DirectEdits,
  type SubtitleFormat,
} from './direct-subtitle';
import type { SrtCopyDocument } from './srt-copy';
import './direct-subtitle.css';

export const DirectSubtitleEditor = () => {
  const [document, setDocument] = useState<SrtCopyDocument | null>(null);
  const [filename, setFilename] = useState('');
  const [edits, setEdits] = useState<DirectEdits>({});
  const [format, setFormat] = useState<SubtitleFormat>('srt');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [selection, setSelection] = useState(0);
  const sequence = useRef(0);
  const page = usePagination(document?.cues || [], String(selection), 20);
  const invalidIndex =
    document?.cues.findIndex((_, index) =>
      Object.values(directCueIssues(directCueValue(document, edits, index))).some(Boolean),
    ) ?? -1;
  const smiIssue = document && format === 'smi' ? directSmiIssue(document, edits) : '';
  const choose = async (file?: File) => {
    if (!file) {
      return;
    }
    const token = ++sequence.current;
    setFilename(file.name);
    setDocument(null);
    setEdits({});
    setFormat('srt');
    setError('');
    setLoading(true);
    setSelection(token);
    try {
      const next = await readDirectSrt(file);
      if (token === sequence.current) {
        setDocument(next);
      }
    } catch (reason) {
      if (token === sequence.current) {
        setError(reason instanceof Error ? reason.message : 'SRT 파일을 읽지 못했습니다.');
      }
    } finally {
      if (token === sequence.current) {
        setLoading(false);
      }
    }
  };
  const update = (index: number, changes: DirectCueEdit) => {
    setEdits((previous) => ({ ...previous, [index]: { ...previous[index], ...changes } }));
    setError('');
  };
  const download = () => {
    if (!document || invalidIndex !== -1 || smiIssue) {
      return;
    }
    try {
      downloadDirectSubtitle(filename, document, edits, format);
      setError('');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '수정본을 만들지 못했습니다.');
    }
  };
  useEffect(
    () => () => {
      sequence.current++;
    },
    [],
  );
  return (
    <main className="video-main direct-subtitle-page">
      <PageTitle>자막 파일 편집</PageTitle>
      <div className="direct-subtitle-file">
        <label htmlFor="direct-subtitle-file">SRT 파일 선택</label>
        <input
          id="direct-subtitle-file"
          type="file"
          accept=".srt"
          aria-describedby="direct-subtitle-file-help"
          onClick={(event) => {
            event.currentTarget.value = '';
          }}
          onChange={(event) => void choose(event.target.files?.[0])}
        />
        <p id="direct-subtitle-file-help">UTF-8 SRT · 최대 16MiB, 10000개 자막</p>
      </div>
      {filename && <p className="direct-subtitle-filename">{filename}</p>}
      <p>원래 파일은 바뀌지 않습니다. 편집한 자막은 별도 파일로 받으세요.</p>
      {loading && <p role="status">자막 불러오는 중</p>}
      {error && <p role="alert">{error}</p>}
      {invalidIndex !== -1 && (
        <p role="alert">
          자막 문구·시각을 확인하세요.{' '}
          <Button
            variant="quiet"
            onClick={() => page.onPage(Math.floor(invalidIndex / page.pageSize) + 1)}
          >
            해당 자막으로
          </Button>
        </p>
      )}
      {document && (
        <>
          <ol className="direct-subtitle-cues" start={page.offset + 1}>
            {page.items.map((cue, offset) => {
              const index = page.offset + offset,
                value = directCueValue(document, edits, index),
                issues = directCueIssues(value);
              return (
                <li key={index}>
                  <h2>자막 {cue.id}</h2>
                  <div className="direct-subtitle-times">
                    {(['start', 'end'] as const).map((field) => (
                      <div key={field}>
                        <label htmlFor={`direct-cue-${index}-${field}`}>
                          {field === 'start' ? '시작' : '종료'}
                        </label>
                        <Input
                          id={`direct-cue-${index}-${field}`}
                          aria-label={`자막 ${index + 1} ${field === 'start' ? '시작' : '종료'}`}
                          value={value[field]}
                          aria-invalid={!!issues[field]}
                          aria-describedby={`direct-cue-${index}-${field}-help`}
                          onChange={(event) => update(index, { [field]: event.target.value })}
                        />
                        <p id={`direct-cue-${index}-${field}-help`}>
                          {issues[field] || 'HH:MM:SS,mmm'}
                        </p>
                      </div>
                    ))}
                  </div>
                  <label htmlFor={`direct-cue-${index}-text`}>문구</label>
                  <Textarea
                    id={`direct-cue-${index}-text`}
                    aria-label={`자막 ${index + 1} 문구`}
                    value={value.text}
                    aria-invalid={!!issues.text}
                    aria-describedby={`direct-cue-${index}-text-help`}
                    onChange={(event) => update(index, { text: event.target.value })}
                  />
                  <p id={`direct-cue-${index}-text-help`}>{issues.text}</p>
                </li>
              );
            })}
          </ol>
          <Pagination {...page} />
        </>
      )}
      <div className="direct-subtitle-actions">
        <label htmlFor="direct-subtitle-format">출력 형식</label>
        <select
          id="direct-subtitle-format"
          value={format}
          onChange={(event) => {
            setFormat(event.target.value as SubtitleFormat);
            setError('');
          }}
        >
          <option value="srt">SRT</option>
          <option value="smi">SMI</option>
        </select>
        <Button
          disabled={!document || loading || invalidIndex !== -1 || !!smiIssue}
          onClick={download}
        >
          {format.toUpperCase()} 받기
        </Button>
      </div>
      {smiIssue && <p role="alert">{smiIssue}</p>}
    </main>
  );
};
