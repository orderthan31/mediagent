export type PortSpec = {
  inputs: Record<string, string>;
  outputs: Record<string, string>;
  options: Record<string, string[]>;
  option_roles?: Record<string, string>;
  option_defaults?: Record<string, string>;
  conditional_outputs?: Record<string, Record<string, Record<string, string>>>;
  hidden_outputs?: Record<string, Record<string, string[]>>;
  hidden_options?: Record<string, Record<string, string[]>>;
  port_types_from_options?: Partial<Record<'inputs' | 'outputs', Record<string, string>>>;
};

export const compatiblePortTypes = (source?: string, target?: string) =>
  !!source && !!target && (source === target || target === 'control_signal');

export const resolvePorts = <T extends PortSpec>(
  spec: T | undefined,
  options: Record<string, string> = {},
  toolSettings: Record<string, Record<string, string>> = {},
): T | undefined => {
  if (!spec) {
    return undefined;
  }
  options = {
    ...Object.fromEntries(
      Object.entries(spec.option_roles || {}).flatMap(([key, role]) =>
        key in (toolSettings[role] || {}) ? [[key, toolSettings[role][key]]] : [],
      ),
    ),
    ...options,
  };
  const result = {
    ...spec,
    options: { ...spec.options },
    inputs: { ...spec.inputs },
    outputs: { ...spec.outputs },
  };
  for (const direction of ['inputs', 'outputs'] as const) {
    for (const [port, key] of Object.entries(spec.port_types_from_options?.[direction] || {})) {
      const value = options[key] || spec.options[key][0];
      if (spec.options[key].includes(value)) {
        result[direction][port] = value;
      }
    }
  }
  for (const [key, variants] of Object.entries(spec.conditional_outputs || {})) {
    Object.assign(result.outputs, variants[options[key]] || {});
  }
  for (const [key, variants] of Object.entries(spec.hidden_outputs || {})) {
    for (const port of variants[options[key]] || []) {
      delete result.outputs[port];
    }
  }
  for (const [key, variants] of Object.entries(spec.hidden_options || {})) {
    for (const name of variants[options[key]] || []) {
      delete result.options[name];
    }
  }
  return result;
};
