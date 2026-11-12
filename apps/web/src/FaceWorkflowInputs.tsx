import { useEffect, useRef, useState } from 'react';
import { request } from './api';
import type { VideoAsset } from './video-api';
import type { FaceInput, NormalInputValue } from './normal-inputs';
import './face-workflow.css';
type Engine = { revision: number; sha256: string; engine: string; face_protocol?: number };
export const FaceWorkflowInputs = ({
  assets,
  value,
  onChange,
  disabled = false,
}: {
  assets: VideoAsset[];
  value: NormalInputValue;
  onChange: (value: NormalInputValue) => void;
  disabled?: boolean;
}) => {
  const [engines, setEngines] = useState<Engine[]>([]),
    [loading, setLoading] = useState(true),
    [error, setError] = useState(''),
    [attempt, setAttempt] = useState(0);
  const selected: FaceInput = value.face_input || {
    photo_asset_id: '',
    engine_revision: null,
    engine_sha256: null,
    settings_revision: 1,
    reference_frame: 1,
  };
  const engine = engines.find(
    (e) => e.revision === selected.engine_revision && e.sha256 === selected.engine_sha256,
  );
  const change = (patch: Partial<FaceInput>) =>
    onChange({ ...value, face_input: { ...selected, ...patch } });
  const latest = useRef({ value, onChange });
  latest.current = { value, onChange };
  const invalidateEngine = (available: Engine[]) => {
    const current = latest.current.value.face_input;
    if (
      current?.engine_revision &&
      !available.some(
        (row) => row.revision === current.engine_revision && row.sha256 === current.engine_sha256,
      )
    ) {
      latest.current.onChange({
        ...latest.current.value,
        face_input: { ...current, engine_revision: null, engine_sha256: null },
      });
    }
  };
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError('');
    void request<{ engines: Engine[]; reason: string }>('/work-entry/faceswap-inputs', {
      signal: controller.signal,
    })
      .then((v) => {
        if (!controller.signal.aborted) {
          setEngines(v.engines);
          invalidateEngine(v.engines);
          if (!v.engines.length) {
            setError(v.reason || '등록 얼굴 합성 실행기가 없습니다.');
          }
        }
      })
      .catch((e) => {
        if (!controller.signal.aborted) {
          setEngines([]);
          invalidateEngine([]);
          setError(e instanceof Error ? e.message : '실행기 목록을 확인하지 못했습니다.');
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [attempt]);
  return (
    <fieldset className="face-workflow-fields" disabled={disabled} aria-label="얼굴 합성 입력">
      <legend>사진과 기준 인물 준비</legend>
      <label>
        원본 사진
        <select
          aria-label="원본 사진"
          value={selected.photo_asset_id}
          aria-invalid={!selected.photo_asset_id}
          onChange={(e) => change({ photo_asset_id: e.target.value })}
        >
          <option value="">JPEG·PNG 사진 선택</option>
          {assets
            .filter((a) => a.media_kind === 'image')
            .map((a) => (
              <option key={a.asset_id} value={a.asset_id}>
                {a.original_filename}
              </option>
            ))}
        </select>
      </label>
      <label>
        얼굴 합성 실행기
        <select
          aria-label="얼굴 합성 실행기"
          value={engine ? `${engine.revision}:${engine.sha256}` : ''}
          disabled={loading}
          aria-invalid={!engine}
          onChange={(e) => {
            const row = engines.find((v) => `${v.revision}:${v.sha256}` === e.target.value);
            change({ engine_revision: row?.revision || null, engine_sha256: row?.sha256 || null });
          }}
        >
          <option value="">등록 실행기 선택</option>
          {engines.map((e) => (
            <option key={e.sha256} value={`${e.revision}:${e.sha256}`}>
              {e.engine} · 버전 {e.revision}
            </option>
          ))}
        </select>
      </label>
      <label>
        영상 기준 프레임
        <input
          aria-label="영상 기준 프레임"
          type="number"
          min="1"
          max="3600"
          step="1"
          value={selected.reference_frame || ''}
          onChange={(e) => change({ reference_frame: Number(e.target.value) })}
        />
      </label>
      <p>
        30초·1280×720 이내 영상에서 사용할 인물을 직접 선택합니다. 사진 입력 확인은 얼굴 검출이나
        합성 성공을 뜻하지 않습니다.
      </p>
      {loading && <p role="status">등록 실행기 확인 중</p>}
      {error && (
        <p role="alert">
          {error}{' '}
          <button type="button" onClick={() => setAttempt((n) => n + 1)}>
            다시 확인
          </button>
        </p>
      )}
      {engine && engine.face_protocol !== 3 && (
        <p role="status">
          이 실행기는 단계별 얼굴 합성을 지원하지 않습니다. 입력은 확인할 수 있지만 시작할 수
          없습니다.
        </p>
      )}
      <p>분석 후 사진·영상의 인물을 선택하고, 생성된 미리보기를 확인한 뒤 합성을 시작합니다.</p>
    </fieldset>
  );
};
