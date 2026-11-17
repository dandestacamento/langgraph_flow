import { useCallback, useEffect, useState } from "react";

const THEME_STORAGE_KEY = "routing-lab3-theme";

type Theme = "light" | "dark";

function initialTheme(): Theme {
  const stored = localStorage.getItem(THEME_STORAGE_KEY);
  if (stored === "light" || stored === "dark") return stored;
  // First visit: follow the OS preference (guarded - jsdom has no matchMedia).
  if (typeof window.matchMedia === "function") {
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  return "light";
}

/** Light/dark theme, persisted in localStorage and applied as a `dark`
 * class on <html> (see index.css's @custom-variant). */
export function useTheme() {
  const [theme, setTheme] = useState<Theme>(initialTheme);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  }, [theme]);

  const toggleTheme = useCallback(() => {
    setTheme((current) => (current === "dark" ? "light" : "dark"));
  }, []);

  return { theme, toggleTheme };
}
