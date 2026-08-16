import { useEffect, useState } from "react";

const STORAGE_KEY = "seemetvc.show-admin";
const EVENT = "seemetvc-show-admin";

export function readShowAdmin(): boolean {
  try {
    return sessionStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

export function setShowAdmin(show: boolean): void {
  try {
    if (show) sessionStorage.setItem(STORAGE_KEY, "1");
    else sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    /* ignore */
  }
  window.dispatchEvent(new CustomEvent(EVENT, { detail: show }));
}

export function useShowAdmin(): boolean {
  const [show, setShow] = useState(readShowAdmin);
  useEffect(() => {
    const on = (ev: Event) => {
      const next = ev instanceof CustomEvent ? Boolean(ev.detail) : readShowAdmin();
      setShow(next);
    };
    window.addEventListener(EVENT, on);
    return () => window.removeEventListener(EVENT, on);
  }, []);
  return show;
}
