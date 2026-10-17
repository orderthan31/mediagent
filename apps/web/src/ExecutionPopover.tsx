import { useState } from 'react';
import { ListVideo, X } from 'lucide-react';
import { type Job } from './api';
import { QueuePanel } from './QueuePanel';

export const ExecutionPopover = ({
  jobs,
  onChanged,
}: {
  jobs: Job[];
  onChanged: () => Promise<void>;
}) => {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        className="ui02-execution-trigger"
        popoverTarget="execution-controls"
        aria-label="실행 관리"
        title="실행 관리"
        aria-expanded={open}
      >
        <ListVideo size={19} aria-hidden="true" />
        <span>실행 관리</span>
      </button>
      <div
        id="execution-controls"
        popover="auto"
        className="ui02-execution-popover"
        onToggle={(event) => setOpen(event.currentTarget.matches(':popover-open'))}
      >
        <div className="ui02-popover-heading">
          <h2>실행 관리</h2>
          <button
            type="button"
            className="ui02-icon"
            popoverTarget="execution-controls"
            popoverTargetAction="hide"
            aria-label="실행 관리 닫기"
          >
            <X size={19} />
          </button>
        </div>
        {open && <QueuePanel jobs={jobs} onChanged={onChanged} />}
      </div>
    </>
  );
};
