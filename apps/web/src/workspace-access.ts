/** Fail closed: originals, jobs and the browser-only subtitle file editor. */
export const isOrdinaryRoute = (route: string): boolean =>
  /^#\/(?:|start|subtitles|jobs(?:\/[a-f0-9]{32})?|videos\/[a-f0-9]{32})$/.test(route);
