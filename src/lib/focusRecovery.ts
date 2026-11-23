/**
 * Focus + screen-reader recovery after alt-tab / window switching.
 *
 * The Rust shell emits `murmur://window-focused` on native focus regain; the
 * DOM `focus`/`visibilitychange` events cover browser dev mode. On return we
 * restore keyboard focus only when it was lost to the document body, re-announce
 * status through a polite live region, and briefly show a focus ring. Tab is
 * never intercepted, so focus is never trapped.
 */

import { useEffect, useRef, useState, type RefObject } from "react";

export const FOCUS_RESTORED_EVENT = "murmur://window-focused";

/** True when focus fell back to the document instead of a real control. */
export function isFocusLost(active: Element | null): boolean {
  return !active || active === document.body || active === document.documentElement;
}

/** Stable announcement shared with the Rust shell's focus event payload. */
export function focusAnnouncement(label: string): string {
  return `${label} window is active. Keyboard focus restored.`;
}

export interface FocusRecovery {
  containerRef: RefObject<HTMLDivElement | null>;
  announcement: string;
}

export function useFocusRecovery(label = "Murmur AI"): FocusRecovery {
  const containerRef = useRef<HTMLDivElement>(null);
  const [announcement, setAnnouncement] = useState("");
  const away = useRef(false);

  useEffect(() => {
    let disposed = false;

    const clearRing = () => {
      const node = containerRef.current;
      if (node?.dataset.focusRestored) delete node.dataset.focusRestored;
    };
    const onAway = () => {
      away.current = true;
      // Clearing first guarantees the next identical message is re-announced.
      setAnnouncement("");
    };
    const onReturn = () => {
      if (!away.current || disposed) return;
      away.current = false;
      const node = containerRef.current;
      if (node && isFocusLost(document.activeElement)) {
        node.dataset.focusRestored = "true";
        node.focus({ preventScroll: true });
      }
      setAnnouncement(focusAnnouncement(label));
    };
    const onVisibility = () => {
      if (document.visibilityState === "hidden") onAway();
      else onReturn();
    };

    window.addEventListener("blur", onAway);
    window.addEventListener("focus", onReturn);
    document.addEventListener("visibilitychange", onVisibility);
    document.addEventListener("pointerdown", clearRing);
    document.addEventListener("keydown", clearRing);

    let unlisten: (() => void) | undefined;
    void import("@tauri-apps/api/event")
      .then(({ listen }) => {
        if (disposed) return undefined;
        return listen<string>(FOCUS_RESTORED_EVENT, () => onReturn()).then((fn) => {
          if (disposed) fn();
          else unlisten = fn;
        });
      })
      .catch(() => undefined); // Browser dev: DOM focus/visibility still work.

    return () => {
      disposed = true;
      window.removeEventListener("blur", onAway);
      window.removeEventListener("focus", onReturn);
      document.removeEventListener("visibilitychange", onVisibility);
      document.removeEventListener("pointerdown", clearRing);
      document.removeEventListener("keydown", clearRing);
      unlisten?.();
    };
  }, [label]);

  return { containerRef, announcement };
}
