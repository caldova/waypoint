import { useEffect, useState } from "react";

const QUERY = "(prefers-reduced-motion: reduce)";

// Live prefers-reduced-motion flag for inline-style transitions that a CSS
// media query can't reach.
export function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(
    () => typeof window !== "undefined" && window.matchMedia?.(QUERY).matches === true,
  );
  useEffect(() => {
    const media = window.matchMedia?.(QUERY);
    if (!media) return;
    const update = () => setReduced(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  return reduced;
}
