import { useId } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import { Button } from './hangyeol/primitives/button';
import { Input } from './hangyeol/primitives/input';
import {
  formDefaults,
  type FieldSchema,
  type FormValue,
  type ReviewMaterial,
} from './form-contract';
import './data-form.css';

type Props = {
  schema: FieldSchema;
  value: FormValue;
  onChange: (value: FormValue) => void;
  disabled?: boolean;
  path?: string;
  depth?: number;
};
const safeMedia = (url?: string) =>
  url && /^\/mock\/[A-Za-z0-9_.-]+$/.test(url) ? url : undefined;
export const DataField = ({
  schema,
  value,
  onChange,
  disabled = false,
  path = '',
  depth = 0,
}: Props) => {
  const identity = useId();
  const locked = disabled || !!schema.readOnly;
  const label = schema.title;
  const object = value && typeof value === 'object' && !Array.isArray(value) ? value : {};
  const choices = schema.choices || [];
  if (depth > 10) {
    return <p role="alert">이 항목은 표시할 수 없습니다.</p>;
  }
  if (schema.type === 'object') {
    return (
      <fieldset className="data-object" disabled={locked}>
        {depth > 0 && <legend>{label}</legend>}
        <div className="data-form-grid">
          {Object.entries(schema.properties || {}).map(([key, child]) => (
            <DataField
              key={key}
              schema={child}
              value={object[key] ?? formDefaults(child)}
              path={`${path}/${key}`}
              disabled={locked}
              depth={depth + 1}
              onChange={(next) => onChange({ ...object, [key]: next })}
            />
          ))}
        </div>
      </fieldset>
    );
  }
  if (schema.type === 'array' && schema.items) {
    const rows = Array.isArray(value) ? value : [];
    const minimum = schema.minItems ?? 0;
    const maximum = Math.min(schema.maxItems ?? 100, 100);
    return (
      <fieldset className="data-array" disabled={locked}>
        <legend>
          {label}
          <span>{rows.length}</span>
        </legend>
        <ol>
          {rows.map((row, index) => (
            <li className="data-array-row" key={index}>
              <span className="data-row-number" aria-hidden="true">
                {index + 1}
              </span>
              <DataField
                schema={schema.items!}
                value={row}
                path={`${path}/${index}`}
                disabled={locked}
                depth={depth + 1}
                onChange={(next) =>
                  onChange(rows.map((item, number) => (number === index ? next : item)))
                }
              />
              {!locked && maximum > minimum && (
                <Button
                  type="button"
                  variant="quiet"
                  size="small"
                  disabled={rows.length <= minimum}
                  aria-label={`${label} ${index + 1} 삭제`}
                  onClick={() => onChange(rows.filter((_, number) => number !== index))}
                >
                  <Trash2 size={15} />
                </Button>
              )}
            </li>
          ))}
        </ol>
        {!locked && rows.length < maximum && (
          <Button
            type="button"
            variant="secondary"
            size="small"
            onClick={() => onChange([...rows, formDefaults(schema.items!)])}
          >
            <Plus size={15} />
            항목 추가
          </Button>
        )}
      </fieldset>
    );
  }
  if (schema.type === 'boolean') {
    return (
      <label className="data-checkbox">
        <input
          type="checkbox"
          checked={value === true}
          disabled={locked}
          onChange={(event) => onChange(event.target.checked)}
        />
        {label}
      </label>
    );
  }
  if (schema.type === 'string' && choices.some((choice) => choice.image)) {
    return (
      <fieldset className="data-choices" disabled={locked}>
        <legend>{label}</legend>
        <div>
          {choices.map((choice) => (
            <label key={choice.value} className={value === choice.value ? 'is-selected' : ''}>
              <input
                type="radio"
                name={identity}
                value={choice.value}
                checked={value === choice.value}
                onChange={() => onChange(choice.value)}
              />
              {safeMedia(choice.image) && (
                <img src={safeMedia(choice.image)} alt="" loading="lazy" />
              )}
              <span>{choice.label}</span>
            </label>
          ))}
        </div>
      </fieldset>
    );
  }
  if (schema.type === 'string' && choices.length) {
    return (
      <label className="data-field">
        {label}
        <select
          aria-label={label}
          value={typeof value === 'string' ? value : ''}
          disabled={locked}
          onChange={(event) => onChange(event.target.value)}
        >
          <option value="" disabled>
            선택
          </option>
          {choices.map((choice) => (
            <option key={choice.value} value={choice.value}>
              {choice.label}
            </option>
          ))}
        </select>
      </label>
    );
  }
  if (schema.type === 'string' && schema.format === 'multiline') {
    return (
      <label className="data-field data-field-wide">
        {label}
        <textarea
          aria-label={label}
          rows={2}
          value={typeof value === 'string' ? value : ''}
          maxLength={schema.maxLength ?? 10000}
          disabled={locked}
          onChange={(event) => onChange(event.target.value)}
        />
      </label>
    );
  }
  if (['string', 'number', 'integer'].includes(schema.type)) {
    const number = schema.type === 'number' || schema.type === 'integer';
    return (
      <label className="data-field">
        {label}
        {schema.format === 'seconds' && <span className="data-unit">초</span>}
        <Input
          aria-label={label}
          type={number ? 'number' : 'text'}
          value={typeof value === 'string' || typeof value === 'number' ? value : ''}
          min={schema.minimum}
          max={schema.maximum}
          step={schema.type === 'integer' ? 1 : schema.format === 'seconds' ? 0.001 : 'any'}
          maxLength={schema.maxLength ?? 10000}
          disabled={locked}
          onChange={(event) =>
            onChange(
              number && event.target.value !== '' ? Number(event.target.value) : event.target.value,
            )
          }
        />
      </label>
    );
  }
  return <p role="alert">이 항목은 아직 수정할 수 없습니다.</p>;
};
export const DataForm = (props: Omit<Props, 'path' | 'depth'>) => (
  <div className="data-form">
    <DataField {...props} />
  </div>
);
export const ReviewMaterials = ({ materials }: { materials: ReviewMaterial[] }) => (
  <div className="review-materials">
    {materials.map((material) => (
      <figure key={material.id}>
        <figcaption>{material.label}</figcaption>
        {material.kind === 'video' && safeMedia(material.url) ? (
          <video controls playsInline preload="metadata" src={safeMedia(material.url)} />
        ) : material.kind === 'audio' && safeMedia(material.url) ? (
          <audio controls preload="none" src={safeMedia(material.url)} />
        ) : material.kind === 'image' && safeMedia(material.url) ? (
          <img src={safeMedia(material.url)} alt={material.label} />
        ) : (
          <p>{material.text || '자료를 불러올 수 없습니다.'}</p>
        )}
      </figure>
    ))}
  </div>
);
