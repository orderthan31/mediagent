import { modelCallOptionLabel } from './model-call-budget';
import { useState } from 'react';
import { DataForm } from './DataForm';
import {
  formDefaults,
  type FormData,
  type FieldSchema,
  type NodeFormContract,
  type ReviewContract,
} from './form-contract';

const optionsData = (schema: FieldSchema, options: Record<string, string>): FormData => {
  const defaults = formDefaults(schema) as FormData;
  return Object.fromEntries(
    Object.entries(schema.properties || {}).map(([key, field]) => {
      const raw = options[key];
      if (raw === undefined) {
        return [key, defaults[key]];
      }
      if (field.type === 'number' || field.type === 'integer') {
        return [key, raw === '' ? '' : Number(raw)];
      }
      if (field.type === 'boolean') {
        return [key, raw === 'true'];
      }
      if (field.type === 'object' || field.type === 'array') {
        try {
          return [key, JSON.parse(raw)];
        } catch {
          return [key, defaults[key]];
        }
      }
      return [key, raw];
    }),
  );
};
const FormPreview = ({ contracts }: { contracts: ReviewContract[] }) => {
  const [index, setIndex] = useState(0);
  const contract = contracts[index] || contracts[0];
  if (!contract) {
    return <p role="alert">검토 시점을 다시 선택해 주세요.</p>;
  }
  return (
    <details className="node-review-preview">
      <summary>검토 화면 보기</summary>
      <div>
        {contracts.length > 1 && (
          <div className="review-task-tabs">
            {contracts.map((item, number) => (
              <button
                type="button"
                key={item.phase}
                aria-pressed={number === index}
                onClick={() => setIndex(number)}
              >
                {item.title}
              </button>
            ))}
          </div>
        )}
        <DataForm
          schema={contract.fields}
          value={formDefaults(contract.fields)}
          disabled
          onChange={() => {}}
        />
      </div>
    </details>
  );
};
export const NodeConfiguration = ({
  contract,
  options,
  changed,
}: {
  contract: NodeFormContract;
  options: Record<string, string>;
  changed: (value: Record<string, string>) => void;
}) => {
  const schema = contract.settings_schema;
  const reviews = contract.review_contracts || [];
  const mode = options.review_mode || 'none';
  const choices: { value: string; label: string }[] = reviews.map((review) => ({
    value: review.phase,
    label: review.phase === 'before' ? '시작 전' : '완료 후',
  }));
  if (reviews.length > 1) {
    choices.push({ value: 'both', label: '시작 전·완료 후' });
  }
  return (
    <div className="node-configuration">
      {schema &&
        (() => {
          const labels: Record<string, string> = {
            max_model_calls: '최대 모델 호출 수',
            audio_filter: '음성 처리',
            vad_mode: '음성 구간 처리',
            subtitle_mode: '자막 표시',
            video_codec: '영상 형식',
            quality_profile: '화질',
            resolution: '해상도',
            target_language: '번역 언어',
            format: '자막 형식',
            track: '출력 언어',
          };
          const internal = new Set([
            'batch_policy',
            'clock_policy',
            'media_budget',
            'processing_profile',
            'translation_profile',
            'model_source',
            'video_budget',
          ]);
          const render = (advanced: boolean) => {
            const properties = Object.fromEntries(
              Object.entries(schema.properties || {})
                .filter(([key]) => internal.has(key) === advanced)
                .map(([key, value]) => [
                  key,
                  {
                    ...value,
                    title: labels[key] || value.title,
                    ...(key === 'max_model_calls'
                      ? {
                          choices: value.choices?.map((choice) => ({
                            ...choice,
                            label: modelCallOptionLabel(choice.value),
                          })),
                        }
                      : {}),
                  },
                ]),
            );
            if (!Object.keys(properties).length) {
              return null;
            }
            const partial = {
              ...schema,
              properties,
              required: schema.required?.filter((key) => key in properties),
            };
            return (
              <DataForm
                schema={partial}
                value={optionsData(partial, options)}
                onChange={(value) => {
                  if (!value || typeof value !== 'object' || Array.isArray(value)) {
                    return;
                  }
                  changed({
                    ...options,
                    ...Object.fromEntries(
                      Object.entries(value).map(([key, field]) => [
                        key,
                        typeof field === 'object' ? JSON.stringify(field) : String(field ?? ''),
                      ]),
                    ),
                  });
                }}
              />
            );
          };
          return (
            <section className="node-settings-block">
              <h4>처리 설정</h4>
              {render(false)}
              <details>
                <summary>고급 처리 설정</summary>
                {render(true)}
              </details>
            </section>
          );
        })()}
      {reviews.length > 0 && (
        <section className="node-settings-block">
          <h4>검토</h4>
          <div className="node-review-options">
            <label>
              <input
                type="checkbox"
                checked={mode !== 'none'}
                onChange={(event) =>
                  changed({
                    ...options,
                    review_mode: event.target.checked ? reviews[0].phase : 'none',
                  })
                }
              />
              사람이 확인
            </label>
            {mode !== 'none' && (
              <select
                aria-label="검토 시점"
                value={mode}
                onChange={(event) => changed({ ...options, review_mode: event.target.value })}
              >
                {choices.map((choice) => (
                  <option key={choice.value} value={choice.value}>
                    {choice.label}
                  </option>
                ))}
              </select>
            )}
          </div>
          {mode !== 'none' && (
            <FormPreview
              contracts={reviews.filter((review) => mode === 'both' || review.phase === mode)}
            />
          )}
        </section>
      )}
    </div>
  );
};
