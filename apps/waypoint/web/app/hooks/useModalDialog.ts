import { useEffect, useRef, useState, type RefObject } from "react";

// Modal dialog behaviour shared by every overlay in the app: focus moves in on
// open, Tab and Shift+Tab wrap inside, Escape closes, the rest of the page is
// inert while it's open, and focus goes back to whatever opened it on close.
//
// Dialogs stack. Only the topmost one owns the keyboard and stays interactive,
// so a confirmation opened over the invoice panel closes on its own Escape
// without also closing the panel underneath.

interface DialogEntry {
  container: HTMLElement;
  openers: HTMLElement[];
  onEscape: () => void;
}

const TABBABLE = [
  "a[href]",
  "area[href]",
  "button:not([disabled])",
  "input:not([disabled]):not([type='hidden'])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "iframe",
  "summary",
  "[contenteditable]:not([contenteditable='false'])",
  "[tabindex]",
].join(",");

const stack: DialogEntry[] = [];
let inerted: HTMLElement[] = [];
let listening = false;

function tabbables(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(TABBABLE)).filter((el) => {
    if (el.tabIndex < 0) return false;
    if (el.closest("[inert]")) return false;
    // Collapsed <details> content and display:none subtrees have no boxes.
    if (el.getClientRects().length === 0) return false;
    return getComputedStyle(el).visibility !== "hidden";
  });
}

// Make every sibling of the top dialog's ancestor chain inert. Elements that
// were already inert (e.g. hidden agent-map tiles) are left alone.
function applyInert() {
  for (const el of inerted) el.inert = false;
  inerted = [];
  const top = stack.at(-1)?.container;
  if (!top || !top.isConnected) return;
  for (let node: HTMLElement = top; node.parentElement && node !== document.body; ) {
    const parent: HTMLElement = node.parentElement;
    for (const sibling of Array.from(parent.children)) {
      if (sibling === node || !(sibling instanceof HTMLElement) || sibling.inert) continue;
      if (sibling.tagName === "SCRIPT" || sibling.tagName === "STYLE") continue;
      sibling.inert = true;
      inerted.push(sibling);
    }
    node = parent;
  }
}

function focusInto(entry: DialogEntry, preferred?: HTMLElement | null) {
  const target = preferred ?? tabbables(entry.container)[0] ?? entry.container;
  if (target === entry.container && !entry.container.hasAttribute("tabindex")) {
    entry.container.tabIndex = -1;
  }
  target.focus();
}

// True when `a` comes before `b` in document order (or contains it).
function precedes(a: Node, b: Node): boolean {
  return Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
}

function onKeyDown(event: KeyboardEvent) {
  const top = stack.at(-1);
  if (!top || event.isComposing) return;

  if (event.key === "Escape") {
    event.preventDefault();
    event.stopPropagation();
    top.onEscape();
    return;
  }

  if (event.key !== "Tab") return;
  const items = tabbables(top.container);
  if (items.length === 0) {
    event.preventDefault();
    focusInto(top);
    return;
  }
  const first = items[0];
  const last = items[items.length - 1];
  const active = document.activeElement;
  if (!active || !top.container.contains(active)) {
    event.preventDefault();
    (event.shiftKey ? last : first).focus();
    return;
  }
  // The active element may be a non-tabbable start point such as the heading,
  // so compare by document position rather than by index.
  if (event.shiftKey && !items.some((el) => el !== active && precedes(el, active))) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && !items.some((el) => el !== active && precedes(active, el))) {
    event.preventDefault();
    first.focus();
  }
}

function syncListener() {
  if (stack.length > 0 && !listening) {
    // Capture phase so the top dialog sees Escape before page-level handlers.
    window.addEventListener("keydown", onKeyDown, true);
    listening = true;
  } else if (stack.length === 0 && listening) {
    window.removeEventListener("keydown", onKeyDown, true);
    listening = false;
  }
}

function captureOpeners(): HTMLElement[] {
  if (typeof document === "undefined") return [];
  const active = document.activeElement as HTMLElement | null;
  if (!active || active === document.body) return [];
  // If the opener lives in a dialog that's about to be replaced (e.g. the
  // "Loading document" viewer swapping for the real one), fall back to that
  // dialog's own opener.
  const host = [...stack].reverse().find((entry) => entry.container.contains(active));
  return [active, ...(host?.openers ?? [])];
}

export interface ModalDialogOptions {
  onClose: () => void;
  /** Element to focus on open; defaults to the first tabbable control. */
  initialFocusRef?: RefObject<HTMLElement | null>;
  /** When false, Escape is swallowed but doesn't close (e.g. while submitting). */
  canClose?: boolean;
}

export function useModalDialog(
  containerRef: RefObject<HTMLElement | null>,
  { onClose, initialFocusRef, canClose = true }: ModalDialogOptions,
) {
  // Captured during the first render, before focus moves into the dialog.
  const [openers] = useState(captureOpeners);
  const closeRef = useRef(onClose);
  const canCloseRef = useRef(canClose);
  closeRef.current = onClose;
  canCloseRef.current = canClose;

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const entry: DialogEntry = {
      container,
      openers,
      onEscape: () => {
        if (canCloseRef.current) closeRef.current();
      },
    };
    stack.push(entry);
    applyInert();
    syncListener();
    // Respect a control that already took focus via autoFocus.
    if (!container.contains(document.activeElement)) {
      focusInto(entry, initialFocusRef?.current);
    }

    return () => {
      const index = stack.indexOf(entry);
      if (index !== -1) stack.splice(index, 1);
      applyInert();
      syncListener();
      const target = openers.find((el) => el.isConnected && !el.closest("[inert]"));
      if (target) {
        target.focus();
      } else if (stack.length > 0) {
        focusInto(stack[stack.length - 1]);
      }
    };
    // The dialog registers once per mount; callbacks are read through refs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}
