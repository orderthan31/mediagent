import './loading-skeleton.css';
export type SkeletonLayout = 'list' | 'table' | 'media' | 'form' | 'canvas' | 'agent';
const Bar = ({ wide = false }: { wide?: boolean }) => (
  <i className={`loading-bar ${wide ? 'is-wide' : ''}`} />
);
export const LoadingSkeleton = ({
  layout = 'list',
  label = '불러오는 중',
}: {
  layout?: SkeletonLayout;
  label?: string;
}) => (
  <section
    className={`loading-skeleton loading-${layout}`}
    data-skeleton={layout}
    role="status"
    aria-label={label}
    aria-busy="true"
  >
    <div aria-hidden="true">
      {layout === 'canvas' ? (
        <div className="loading-canvas">
          {[0, 1, 2, 3].map((i) => (
            <div className="loading-node" key={i}>
              <Bar wide />
              <Bar />
            </div>
          ))}
        </div>
      ) : layout === 'media' ? (
        <div className="loading-media">
          <div className="loading-player" />
          <div className="loading-fields">
            {[0, 1, 2, 3, 4].map((i) => (
              <div key={i}>
                <Bar />
                <Bar wide />
              </div>
            ))}
          </div>
        </div>
      ) : layout === 'form' ? (
        <div className="loading-fields">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <div key={i}>
              <Bar />
              <div className="loading-input" />
            </div>
          ))}
        </div>
      ) : layout === 'agent' ? (
        <>
          <Bar />
          <div className="loading-fields">
            {[0, 1, 2].map((i) => (
              <div key={i}>
                <Bar />
                <Bar wide />
              </div>
            ))}
          </div>
          <div className="loading-table-row">
            <Bar />
            <Bar />
            <Bar />
          </div>
        </>
      ) : (
        [0, 1, 2, 3, 4].map((i) => (
          <div key={i} className={layout === 'table' ? 'loading-table-row' : 'loading-list-row'}>
            {layout === 'list' && <div className="loading-thumbnail" />}
            <div>
              <Bar wide />
              <Bar />
            </div>
            {layout === 'table' && (
              <>
                <Bar />
                <Bar />
                <Bar />
              </>
            )}
          </div>
        ))
      )}
    </div>
    <span className="loading-sr-only">{label}</span>
  </section>
);
