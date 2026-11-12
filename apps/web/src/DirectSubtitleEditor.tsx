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
  readDirectSubtitle,
  serializeDirectSubtitle,
  type DirectCueEdit,
  type DirectEdits,
  type SubtitleFormat,
} from './direct-subtitle';
import type { SrtCopyDocument } from './srt-copy';
import {
  getSubtitleCopy,
  saveSubtitleCopy,
  type SubtitleCopy,
  type SubtitleCopySave,
} from './subtitle-copies';
import './direct-subtitle.css';

export const DirectSubtitleEditor = ({ savedId }: { savedId?: string }) => {
  const [document, setDocument] = useState<SrtCopyDocument | null>(null);
  const [filename, setFilename] = useState('');
  const [edits, setEdits] = useState<DirectEdits>({});
  const [format, setFormat] = useState<SubtitleFormat>('srt');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [selection, setSelection] = useState(0);
  const [title, setTitle] = useState('');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<SubtitleCopy | null>(null);
  const [openedAt, setOpenedAt] = useState('');
  const sequence = useRef(0);
  const attempt = useRef<SubtitleCopySave | null>(null);
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
    setTitle(file.name);
    setSaved(null);
    setOpenedAt('');
    attempt.current = null;
    setDocument(null);
    setEdits({});
    setFormat('srt');
    setError('');
    setLoading(true);
    setSelection(token);
    try {
      const next = await readDirectSubtitle(file);
      if (token === sequence.current) {
        setDocument(next);
      }
    } catch (reason) {
      if (token === sequence.current) {
        setError(reason instanceof Error ? reason.message : '자막 파일을 읽지 못했습니다.');
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
    setSaved(null);
  };
  const save = async () => {
    if (!document || saving || loading || invalidIndex !== -1 || !title.trim()) {
      return;
    }
    const token = sequence.current;
    setSaving(true);
    setError('');
    setSaved(null);
    try {
      const bytes = serializeDirectSubtitle(document, edits, 'srt');
      const srt = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(bytes);
      const previous = attempt.current;
      const body =
        previous &&
        previous.srt === srt &&
        previous.title === title &&
        previous.filename === filename
          ? previous
          : { id: crypto.randomUUID().replaceAll('-', ''), filename, title, srt };
      attempt.current = body;
      const receipt = await saveSubtitleCopy(body);
      if (token === sequence.current) {
        setSaved(receipt);
        attempt.current = null;
      }
    } catch (reason) {
      if (token === sequence.current) {
        setError(
          (reason instanceof Error ? reason.message : '수정본을 저장하지 못했습니다.') +
            ' 저장된 자막 목록에서 결과를 확인할 수 있습니다.',
        );
      }
    } finally {
      if (token === sequence.current) {
        setSaving(false);
      }
    }
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
  useEffect(() => {
    if (!savedId) {
      return () => {
        sequence.current++;
      };
    }
    const controller = new AbortController(),
      token = ++sequence.current;
    setLoading(true);
    void getSubtitleCopy(savedId, controller.signal)
      .then((copy) => {
        if (token === sequence.current && !controller.signal.aborted) {
          setDocument(copy.document);
          setFilename(copy.filename);
          setTitle(copy.title);
          setOpenedAt(copy.created_at);
          setSelection(token);
        }
      })
      .catch((reason: unknown) => {
        if (token === sequence.current && !controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : '저장된 자막을 불러오지 못했습니다.');
        }
      })
      .finally(() => {
        if (token === sequence.current && !controller.signal.aborted) {
          setLoading(false);
        }
      });
    return () => {
      sequence.current++;
      controller.abort();
    };
  }, [savedId]);
  return (
    <main className="video-main direct-subtitle-page">
      <PageTitle>자막 파일 편집</PageTitle>
      <a href="#/subtitles/saved">저장된 자막</a>
      {openedAt && (
        <p>
          저장 시각 <time dateTime={openedAt}>{new Date(openedAt).toLocaleString('ko-KR')}</time>
        </p>
      )}
      <div className="direct-subtitle-file">
        <label htmlFor="direct-subtitle-file">자막 파일 선택</label>
        <input
          id="direct-subtitle-file"
          type="file"
          disabled={saving}
          accept=".srt,.smi,.sami"
          aria-describedby="direct-subtitle-file-help"
          onClick={(event) => {
            event.currentTarget.value = '';
          }}
          onChange={(event) => void choose(event.target.files?.[0])}
        />
        <p id="direct-subtitle-file-help">UTF-8 SRT·SMI·SAMI · 최대 16MiB, 10000개 자막</p>
      </div>
      {filename && <p className="direct-subtitle-filename">{filename}</p>}
      <p>원래 파일은 바뀌지 않습니다. 수정본을 별도로 저장하거나 파일로 받으세요.</p>
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
                          disabled={saving}
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
                    disabled={saving}
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
      {document && (
        <div className="direct-subtitle-save">
          <label htmlFor="direct-subtitle-title">수정본 제목</label>
          <Input
            id="direct-subtitle-title"
            maxLength={255}
            value={title}
            disabled={saving}
            onChange={(event) => {
              setTitle(event.target.value);
              setSaved(null);
            }}
          />
          <p>
            저장하면 로그인 후 다시 열 수 있는 별도 자막이 만들어집니다. 다시 저장할 때마다 새
            수정본이 생깁니다.
          </p>
          <Button
            disabled={loading || saving || invalidIndex !== -1 || !title.trim()}
            onClick={() => void save()}
          >
            {saving ? '수정본 저장 중' : '수정본 저장'}
          </Button>
          {saved && (
            <p role="status">
              <span>수정본을 저장했습니다.</span>{' '}
              <a href={`#/subtitles/saved/${saved.id}`}>저장한 자막 열기</a>
            </p>
          )}
        </div>
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
