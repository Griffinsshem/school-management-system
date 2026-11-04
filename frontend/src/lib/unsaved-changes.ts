"use client";

import { useEffect } from "react";

// A warning before unsaved work is lost (D8). A page calls
// useUnsavedChanges(dirty) with whether it has typed, unsaved changes. While
// any page part is dirty:
// - following a link inside the app asks first (confirmLeave below);
// - code that leaves or reloads the page in another way (Log out, a term or
//   date selector) calls confirmLeave() and stops if it returns false;
// - closing or reloading the tab, or going to another site, shows the
//   browser's own warning.
// The browser's Back button inside the app is not covered: Next.js offers no
// reliable way to stop it.

export const LEAVE_MESSAGE = "You have unsaved changes. Leave this page and lose them?";

// One entry per page part with unsaved changes (several comment boxes can
// be dirty at once, but the person is asked once).
const dirtyParts = new Set<symbol>();
let listening = false;

export function hasUnsavedChanges(): boolean {
  return dirtyParts.size > 0;
}

// True when it is fine to leave: nothing is unsaved, or the person agreed to
// lose it. Agreeing forgets the changes, so leaving does not ask again.
export function confirmLeave(): boolean {
  if (!hasUnsavedChanges()) {
    return true;
  }
  if (!window.confirm(LEAVE_MESSAGE)) {
    return false;
  }
  dirtyParts.clear();
  return true;
}

function onBeforeUnload(event: BeforeUnloadEvent) {
  if (hasUnsavedChanges()) {
    event.preventDefault();
    // Older browsers need returnValue set to show their warning.
    event.returnValue = "";
  }
}

// Runs before Next.js handles a link click (capture phase on window), so a
// refused click never starts the navigation.
function onClick(event: MouseEvent) {
  if (!hasUnsavedChanges() || event.defaultPrevented || event.button !== 0) {
    return;
  }
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
    return; // Opens a new tab or window: this page stays.
  }
  const link = (event.target as Element | null)?.closest?.("a[href]");
  if (!(link instanceof HTMLAnchorElement) || link.target === "_blank" || link.hasAttribute("download")) {
    return;
  }
  const to = new URL(link.href, window.location.href);
  if (to.origin !== window.location.origin) {
    return; // Another site: the browser's own warning covers it.
  }
  if (to.pathname === window.location.pathname && to.search === window.location.search) {
    return; // Same page (a #section link).
  }
  if (!confirmLeave()) {
    event.preventDefault();
    event.stopPropagation();
  }
}

function listen() {
  if (listening) {
    return;
  }
  listening = true;
  window.addEventListener("beforeunload", onBeforeUnload);
  window.addEventListener("click", onClick, true);
}

export function useUnsavedChanges(dirty: boolean) {
  useEffect(() => {
    if (!dirty) {
      return;
    }
    listen();
    const part = Symbol("unsaved");
    dirtyParts.add(part);
    return () => {
      dirtyParts.delete(part);
    };
  }, [dirty]);
}
