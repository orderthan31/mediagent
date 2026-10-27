export type View = { x: number; y: number; scale: number };
export type Point = { x: number; y: number };
export const pinchView = (
  view: View,
  anchor: Point,
  midpoint: Point,
  startDistance: number,
  distance: number,
  min = 0.02,
  max = 1.8,
): View => {
  if (startDistance <= 0) {
    return view;
  }
  const scale = Math.min(max, Math.max(min, (view.scale * distance) / startDistance));
  return {
    scale,
    x: midpoint.x - ((anchor.x - view.x) * scale) / view.scale,
    y: midpoint.y - ((anchor.y - view.y) * scale) / view.scale,
  };
};
