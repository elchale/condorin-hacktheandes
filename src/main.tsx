import { createRoot } from "react-dom/client";
import { App } from "./App";
import { ErrorBoundary, reloadOnce } from "./components/ErrorBoundary";
import "./index.css";

// Vite fires this when a route chunk from an older deploy is gone; a fresh load gets the new build.
window.addEventListener("vite:preloadError", (e) => {
  if (reloadOnce()) e.preventDefault();
});

createRoot(document.getElementById("root")!).render(
  <ErrorBoundary>
    <App />
  </ErrorBoundary>,
);
