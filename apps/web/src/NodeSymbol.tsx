import { Boxes, GitBranch, UserRoundCheck } from 'lucide-react';
import { isControlNode } from './workflow-controls';
export const nodeKind = (type: string): 'agent' | 'control' | 'review' =>
  type === 'review' ? 'review' : isControlNode(type) ? 'control' : 'agent';
export const nodeKindLabel = (type: string) =>
  ({ agent: '에이전트', control: '제어 노드', review: '사람 검수' })[nodeKind(type)];
export const NodeSymbol = ({ type, size = 20 }: { type: string; size?: number }) => {
  const Icon = { agent: Boxes, control: GitBranch, review: UserRoundCheck }[nodeKind(type)];
  return <Icon size={size} aria-hidden="true" />;
};
