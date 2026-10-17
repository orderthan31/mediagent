/** Data-only form contracts for the publishing prototype; not a worker/runtime API. */
export type FormValue =
  string | number | boolean | null | FormValue[] | { [key: string]: FormValue };
export type FormData = { [key: string]: FormValue };
export type FieldChoice = { value: string; label: string; image?: string };
export type FieldSchema = {
  type: 'string' | 'number' | 'integer' | 'boolean' | 'object' | 'array';
  title: string;
  format?: 'multiline' | 'seconds';
  readOnly?: boolean;
  default?: FormValue;
  const?: FormValue;
  choices?: FieldChoice[];
  properties?: Record<string, FieldSchema>;
  items?: FieldSchema;
  required?: string[];
  minLength?: number;
  maxLength?: number;
  minimum?: number;
  maximum?: number;
  minItems?: number;
  maxItems?: number;
  order?: { from: string; to: string; message: string };
};
export type FormIssue = { path: string; message: string };
export type ReviewMaterial = {
  id: string;
  label: string;
  kind: 'video' | 'audio' | 'image' | 'text';
  url?: string;
  text?: string;
};
export type ReviewContract = {
  version: number;
  title: string;
  phase: 'before' | 'after';
  fields: FieldSchema;
  material_ports: string[];
};
export type NodeFormContract = {
  model_role?: string;
  settings_schema?: FieldSchema;
  review_contracts?: ReviewContract[];
};
export type ReviewTask = {
  id: string;
  job_id: string;
  node_id: string;
  contract: ReviewContract;
  materials: ReviewMaterial[];
  data: FormData;
  revision: number;
  state: 'waiting' | 'draft' | 'changes_requested' | 'confirmed';
  reason: string;
  confirmed?: { revision: number; data: FormData };
};
const reserved = new Set(['__proto__', 'prototype', 'constructor']);
export const formDefaults = (schema: FieldSchema): FormValue => {
  if (schema.default !== undefined) {
    return structuredClone(schema.default);
  }
  if (schema.type === 'object') {
    return Object.fromEntries(
      Object.entries(schema.properties || {})
        .filter(([key]) => !reserved.has(key))
        .map(([key, child]) => [key, formDefaults(child)]),
    );
  }
  if (schema.type === 'array') {
    return Array.from({ length: Math.min(schema.minItems || 0, 100) }, () =>
      schema.items ? formDefaults(schema.items) : null,
    );
  }
  if (schema.type === 'boolean') {
    return false;
  }
  if (schema.type === 'number' || schema.type === 'integer') {
    return schema.minimum ?? 0;
  }
  return schema.choices?.[0]?.value || '';
};
export const validateForm = (
  schema: FieldSchema,
  value: FormValue,
  path = '',
  depth = 0,
): FormIssue[] => {
  const fail = (message: string): FormIssue[] => [{ path, message: `${schema.title}: ${message}` }];
  if (depth > 10) {
    return fail('항목이 너무 많습니다.');
  }
  if (schema.const !== undefined && JSON.stringify(value) !== JSON.stringify(schema.const)) {
    return fail('확인이 필요합니다.');
  }
  if (schema.type === 'object') {
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
      return fail('입력값을 확인해 주세요.');
    }
    const properties = schema.properties || {};
    if (Object.keys(value).some((key) => reserved.has(key) || !Object.hasOwn(properties, key))) {
      return fail('허용되지 않은 항목이 있습니다.');
    }
    const issues = Object.entries(properties).flatMap(([key, child]) => {
      const next = value[key];
      if (next === undefined || next === null || (typeof next === 'string' && !next.trim())) {
        return schema.required?.includes(key)
          ? [{ path: `${path}/${key}`, message: `${child.title}을 입력해 주세요.` }]
          : [];
      }
      return validateForm(child, next, `${path}/${key}`, depth + 1);
    });
    if (schema.order && Number(value[schema.order.to]) <= Number(value[schema.order.from])) {
      issues.push({ path, message: schema.order.message });
    }
    return issues;
  }
  if (schema.type === 'array') {
    if (!Array.isArray(value) || !schema.items) {
      return fail('항목을 확인해 주세요.');
    }
    if (
      value.length < (schema.minItems ?? 0) ||
      value.length > Math.min(schema.maxItems ?? 100, 100)
    ) {
      return fail('항목 수를 확인해 주세요.');
    }
    return value.flatMap((item, index) =>
      validateForm(schema.items!, item, `${path}/${index}`, depth + 1),
    );
  }
  if (schema.type === 'boolean') {
    return typeof value === 'boolean' ? [] : fail('선택값을 확인해 주세요.');
  }
  if (schema.type === 'number' || schema.type === 'integer') {
    if (
      typeof value !== 'number' ||
      !Number.isFinite(value) ||
      (schema.type === 'integer' && !Number.isInteger(value))
    ) {
      return fail('숫자를 입력해 주세요.');
    }
    if (value < (schema.minimum ?? -Infinity) || value > (schema.maximum ?? Infinity)) {
      return fail('허용 범위를 확인해 주세요.');
    }
    return [];
  }
  if (schema.type !== 'string') {
    return fail('아직 지원하지 않는 항목입니다.');
  }
  if (
    typeof value !== 'string' ||
    value.length < (schema.minLength ?? 0) ||
    value.length > (schema.maxLength ?? 10000)
  ) {
    return fail('입력 내용을 확인해 주세요.');
  }
  if (schema.choices && !schema.choices.some((choice) => choice.value === value)) {
    return fail('목록에서 선택해 주세요.');
  }
  return [];
};
export const readonlyChanges = (
  schema: FieldSchema,
  before: FormValue,
  after: FormValue,
): boolean => {
  if (schema.readOnly) {
    return JSON.stringify(before) !== JSON.stringify(after);
  }
  if (
    schema.type === 'object' &&
    before &&
    after &&
    typeof before === 'object' &&
    typeof after === 'object' &&
    !Array.isArray(before) &&
    !Array.isArray(after)
  ) {
    return Object.entries(schema.properties || {}).some(([key, child]) =>
      readonlyChanges(child, before[key] ?? null, after[key] ?? null),
    );
  }
  if (schema.type === 'array' && schema.items && Array.isArray(before) && Array.isArray(after)) {
    return before.some((item, index) => readonlyChanges(schema.items!, item, after[index] ?? null));
  }
  return false;
};
