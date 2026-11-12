import type { CanvasDefinition } from './WorkflowCanvas';

export const savedGoalOption = (
  node: Pick<CanvasDefinition['nodes'][number], 'options' | 'tool_settings'>,
  spec: { option_roles?: Record<string, string>; option_defaults?: Record<string, string> },
  key: string,
  fallback: string,
) =>
  node.options[key] ??
  node.tool_settings?.[spec.option_roles?.[key] || '']?.[key] ??
  spec.option_defaults?.[key] ??
  fallback;

export const frozenGoalLanguages = (definition: CanvasDefinition | null) =>
  definition?.catalog_version === 2
    ? definition.nodes.flatMap((node) =>
        node.type === 'transcription_agent'
          ? [
              {
                id: node.id,
                label: '원문 언어',
                value: savedGoalOption(
                  node,
                  { option_roles: { source_language: 'transcribe' } },
                  'source_language',
                  'auto',
                ),
              },
            ]
          : node.type === 'translation_agent'
            ? [
                {
                  id: node.id,
                  label: '대상 언어',
                  value: savedGoalOption(
                    node,
                    { option_roles: { target_language: 'translate' } },
                    'target_language',
                    'ko',
                  ),
                },
              ]
            : [],
      )
    : [];
