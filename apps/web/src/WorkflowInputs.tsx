import { useEffect, useId, useRef, useState } from 'react';
import { languageLabel } from './language-label';
import {
  readSrtFile,
  inputChoiceKey,
  withSrtInput,
  selectAcceptedInput,
  type InputChoice,
  type NormalInputValue,
} from './normal-inputs';

export const WorkflowInputs = ({
  inputs,
  value,
  onChange,
  choices,
  loading = false,
  error = '',
  disabled = false,
  onReload,
}: {
  inputs: Record<string, string>;
  value: NormalInputValue;
  onChange: (next: NormalInputValue) => void;
  choices: InputChoice[];
  loading?: boolean;
  error?: string;
  disabled?: boolean;
  onReload?: () => void;
}) => {
  const [fileName, setFileName] = useState('');
  const [fileError, setFileError] = useState('');
  const [reading, setReading] = useState(false);
  const generation = useRef(0);
  const fieldId = useId();
  const transcriptMissing =
    !!inputs.transcript && !value.subtitle_srt && !value.accepted_inputs?.transcript && !reading;
  const audioMissing = !!inputs.audio && !value.accepted_inputs?.audio && !loading;
  const languageMissing = value.input_language === '' && !value.accepted_inputs?.transcript;
  const latest = useRef(value);
  latest.current = value;
  const choose = (port: 'transcript' | 'audio', identity: string) => {
    if (port === 'transcript') {
      ++generation.current;
      setReading(false);
      setFileError('');
      setFileName('');
    }
    onChange(
      selectAcceptedInput(
        value,
        port,
        choices.find((choice) => inputChoiceKey(choice) === identity),
      ),
    );
  };
  const read = async (file?: File) => {
    const current = ++generation.current;
    setFileError('');
    setFileName('');
    setReading(false);
    onChange(withSrtInput(value));
    if (!file) {
      return;
    }
    setReading(true);
    try {
      const text = await readSrtFile(file);
      if (current === generation.current) {
        setFileName(file.name);
        onChange(withSrtInput(latest.current, text));
      }
    } catch (reason) {
      if (current === generation.current) {
        setFileError(reason instanceof Error ? reason.message : 'SRT 파일을 읽지 못했습니다.');
      }
    } finally {
      if (current === generation.current) {
        setReading(false);
      }
    }
  };
  useEffect(
    () => () => {
      ++generation.current;
    },
    [],
  );
  return (
    <fieldset disabled={disabled} aria-label="워크플로우 선택 입력">
      <legend>필요한 입력</legend>
      {loading && <p role="status">완료 입력 확인 중</p>}
      {error && (
        <p role="alert">
          {error}{' '}
          {onReload && (
            <button type="button" onClick={onReload}>
              입력 목록 다시 확인
            </button>
          )}
        </p>
      )}
      {inputs.transcript && (
        <>
          <label>
            시간 자막 출처
            <select
              aria-label="시간 자막 출처"
              aria-invalid={transcriptMissing}
              aria-describedby={transcriptMissing ? `${fieldId}-transcript-required` : undefined}
              value={
                value.accepted_inputs?.transcript
                  ? inputChoiceKey(value.accepted_inputs.transcript)
                  : ''
              }
              onChange={(event) => choose('transcript', event.target.value)}
              disabled={loading}
            >
              <option value="">SRT 파일 선택</option>
              {choices
                .filter((choice) => choice.port === 'transcript')
                .map((choice) => (
                  <option key={inputChoiceKey(choice)} value={inputChoiceKey(choice)}>
                    {choice.label}
                  </option>
                ))}
            </select>
          </label>
          {!value.accepted_inputs?.transcript && (
            <>
              <label>
                SRT 파일 (UTF-8)
                <input
                  aria-label="SRT 파일"
                  aria-invalid={transcriptMissing || !!fileError}
                  aria-describedby={
                    fileError
                      ? `${fieldId}-file-error`
                      : transcriptMissing
                        ? `${fieldId}-transcript-required`
                        : undefined
                  }
                  type="file"
                  accept=".srt"
                  onChange={(event) => void read(event.target.files?.[0])}
                />
              </label>
              {reading && <p role="status">SRT 파일 읽는 중</p>}
              {fileName && <p>{fileName}</p>}
              {fileError && (
                <p id={`${fieldId}-file-error`} role="alert">
                  {fileError}
                </p>
              )}
              {transcriptMissing && (
                <small id={`${fieldId}-transcript-required`} className="field-validation">
                  자막을 선택하세요.
                </small>
              )}
              <label>
                선택 자막 원문 언어
                <input
                  aria-label="선택 자막 원문 언어"
                  aria-invalid={languageMissing}
                  aria-describedby={languageMissing ? `${fieldId}-language-required` : undefined}
                  value={value.input_language ?? 'auto'}
                  onChange={(event) => onChange({ ...value, input_language: event.target.value })}
                />
              </label>
              {languageMissing && (
                <small id={`${fieldId}-language-required`} className="field-validation">
                  원문 언어를 입력하세요.
                </small>
              )}
              <small>
                {value.input_language === 'auto' || !value.input_language
                  ? '원문 언어 미지정'
                  : languageLabel(value.input_language)}
              </small>
            </>
          )}
        </>
      )}
      {inputs.audio && (
        <label>
          같은 영상의 추출 음성 (16kHz 모노 PCM WAV)
          <select
            aria-label="재사용 추출 음성"
            aria-invalid={audioMissing}
            aria-describedby={audioMissing ? `${fieldId}-audio-required` : undefined}
            value={value.accepted_inputs?.audio ? inputChoiceKey(value.accepted_inputs.audio) : ''}
            onChange={(event) => choose('audio', event.target.value)}
            disabled={loading}
          >
            <option value="">완료된 추출 결과 선택</option>
            {choices
              .filter((choice) => choice.port === 'audio')
              .map((choice) => (
                <option key={inputChoiceKey(choice)} value={inputChoiceKey(choice)}>
                  {choice.label}
                </option>
              ))}
          </select>
          {audioMissing && (
            <small id={`${fieldId}-audio-required`} className="field-validation">
              추출 음성을 선택하세요.
            </small>
          )}
          {!loading && !choices.some((choice) => choice.port === 'audio') && (
            <small>같은 영상의 완료된 추출 결과가 없습니다.</small>
          )}
        </label>
      )}
    </fieldset>
  );
};
