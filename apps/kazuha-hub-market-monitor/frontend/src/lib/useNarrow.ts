import { useEffect, useState } from "react";

/** Phone width. Keep in step with the `max-width: 767px` blocks in style.css. */
export const NARROW_QUERY = "(max-width: 767px)";
/** A card layout instead of a table. Keep in step with `.mm-card-table--cards`. */
export const PHONE_QUERY = "(max-width: 575px)";

function media(query: string): MediaQueryList | null {
  return typeof window !== "undefined" &&
    typeof window.matchMedia === "function"
    ? window.matchMedia(query)
    : null;
}

function useMedia(query: string): boolean {
  const [matches, setMatches] = useState(() => media(query)?.matches ?? false);
  useEffect(() => {
    const mq = media(query);
    if (!mq) return;
    const onChange = () => setMatches(mq.matches);
    onChange();
    // Older Safari only has the deprecated addListener pair.
    if (mq.addEventListener) mq.addEventListener("change", onChange);
    else mq.addListener?.(onChange);
    return () => {
      if (mq.removeEventListener) mq.removeEventListener("change", onChange);
      else mq.removeListener?.(onChange);
    };
  }, [query]);
  return matches;
}

/** True while the viewport is phone-width; follows breakpoint crossings. */
export function useNarrow(): boolean {
  return useMedia(NARROW_QUERY);
}

/** True while the viewport is small enough for stacked cards instead of tables. */
export function usePhone(): boolean {
  return useMedia(PHONE_QUERY);
}
