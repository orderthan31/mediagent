import {
  modelTypeLabels,
  modalityLabels,
  capabilityLabels,
  typeDefaults,
} from './registered-models';
export type ModelProfile = {
  model_types: string[];
  input_modalities: string[];
  output_modalities: string[];
  capabilities: string[];
};
export const emptyModelProfile = (): ModelProfile => ({
  model_types: [],
  input_modalities: [],
  output_modalities: [],
  capabilities: [],
});
export const ModelProfileFields = ({
  value,
  changed,
}: {
  value: ModelProfile;
  changed: (value: ModelProfile) => void;
}) => (
  <div className="model-profile-fields">
    {(
      [
        ['model_types', '모델 유형', modelTypeLabels],
        ['input_modalities', '입력', modalityLabels],
        ['output_modalities', '출력', modalityLabels],
        ['capabilities', '지원 기능', capabilityLabels],
      ] as const
    ).map(([field, title, labels]) => (
      <div className="model-profile-row" key={field} role="group" aria-label={title}>
        <span>{title}</span>
        <div className="model-profile-choices">
          {Object.entries(labels).map(([id, label]) => (
            <label className="serving-check" key={id}>
              <input
                type="checkbox"
                aria-label={`${title} ${label}`}
                checked={value[field].includes(id)}
                onChange={(event) => {
                  const next = event.target.checked
                    ? [...value[field], id]
                    : value[field].filter((item) => item !== id);
                  if (field === 'model_types' && event.target.checked) {
                    const defaults = typeDefaults[id];
                    changed({
                      model_types: next,
                      input_modalities: [
                        ...new Set([...value.input_modalities, ...defaults.inputs]),
                      ],
                      output_modalities: [
                        ...new Set([...value.output_modalities, ...defaults.outputs]),
                      ],
                      capabilities: [...new Set([...value.capabilities, ...defaults.capabilities])],
                    });
                  } else {
                    changed({ ...value, [field]: next });
                  }
                }}
              />
              {label}
            </label>
          ))}
        </div>
      </div>
    ))}
  </div>
);
