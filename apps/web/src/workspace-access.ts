/** Fail closed: ordinary accounts can only enter original and job surfaces. */
export const isOrdinaryRoute = (route: string): boolean =>
  /^#\/(?:|start|jobs(?:\/[a-f0-9]{32})?|videos\/[a-f0-9]{32})$/.test(route);
