// Minimal hash router: "#/mandates/123" -> "/mandates/123". Hash routes need no server rewrites.
import { useEffect, useState } from "react";

export function currentPath() {
  return window.location.hash.replace(/^#/, "") || "/";
}

export function navigate(path: string) {
  window.location.hash = path;
}

export function usePath() {
  const [path, setPath] = useState(currentPath);
  useEffect(() => {
    const onChange = () => {
      setPath(currentPath());
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return path;
}

/** match("/mandates/:id", "/mandates/42") -> { id: "42" }; null when it does not match. */
export function match(pattern: string, path: string): Record<string, string> | null {
  const p = pattern.split("/");
  const parts = path.split("?")[0].split("/");
  if (p.length !== parts.length) return null;
  const params: Record<string, string> = {};
  for (let i = 0; i < p.length; i++) {
    if (p[i].startsWith(":")) params[p[i].slice(1)] = decodeURIComponent(parts[i]);
    else if (p[i] !== parts[i]) return null;
  }
  return params;
}

export function query(path: string) {
  return new URLSearchParams(path.split("?")[1] ?? "");
}
