/** Fail closed: originals, jobs and subtitle file editing/saved copies. */
export const isOrdinaryRoute = (route: string): boolean =>
  /^#\/(?:|start(?:\/subtitles\/[a-f0-9]{32}(?:\/translate)?)?|subtitles(?:\/saved(?:\/[a-f0-9]{32})?)?|jobs(?:\/[a-f0-9]{32})?|videos\/[a-f0-9]{32})$/.test(
    route,
  );
