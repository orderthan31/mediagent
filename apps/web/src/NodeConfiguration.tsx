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
      {schema && (
        <section className="node-settings-block">
          <h4>처리 설정</h4>
          <DataForm
            schema={schema}
            value={optionsData(schema, options)}
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
        </section>
      )}
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
