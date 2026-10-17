export const pageWindow = (total: number, requested: number, size = 20) => {
  const pageSize = Math.max(1, Math.floor(size));
  const pages = Math.max(1, Math.ceil(Math.max(0, total) / pageSize));
  const page = Math.min(pages, Math.max(1, Math.floor(requested)));
  const offset = (page - 1) * pageSize;
  return {
    total,
    page,
    pages,
    pageSize,
    offset,
    first: total ? offset + 1 : 0,
    last: Math.min(total, offset + pageSize),
  };
};
