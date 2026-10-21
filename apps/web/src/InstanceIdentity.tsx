import { useState } from 'react';
import { Copy, Check } from 'lucide-react';

export const InstanceIdentity = ({ id }: { id: string }) => {
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(id);
      setCopied(true);
      setError(false);
    } catch {
      setCopied(false);
      setError(true);
    }
  };
  return (
    <div className="agent-instance-identity">
      <details>
        <summary title={id} aria-label={`실행 ID 전체 보기: ${id}`}>
          <code>{id.length > 20 ? `${id.slice(0, 8)}…${id.slice(-8)}` : id}</code>
        </summary>
        <code className="agent-instance-full-id">{id}</code>
      </details>
      <button
        type="button"
        className="ui02-icon"
        aria-label={`실행 ID 복사: ${id}`}
        onClick={() => void copy()}
      >
        {copied ? <Check size={16} /> : <Copy size={16} />}
      </button>
      <span className="ui02-sr-only" role="status">
        {copied ? 'ID 복사됨' : ''}
      </span>
      {error && <span role="alert">복사 실패</span>}
    </div>
  );
};
