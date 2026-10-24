export type PortSpec = {
  inputs: Record<string, string>;
  outputs: Record<string, string>;
  options: Record<string, string[]>;
  conditional_outputs?: Record<string, Record<string, Record<string, string>>>;
  port_types_from_options?: Partial<Record<'inputs' | 'outputs', Record<string, string>>>;
};

export const resolvePorts = <T extends PortSpec>(
  spec: T | undefined,
  options: Record<string, string> = {},
): T | undefined => {
  if (!spec) {
    return undefined;
  }
  const result = { ...spec, inputs: { ...spec.inputs }, outputs: { ...spec.outputs } };
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
  return result;
};
