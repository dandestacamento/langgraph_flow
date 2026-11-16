import "@testing-library/jest-dom/vitest";

// jsdom doesn't implement scrollIntoView - ChatWindow's auto-scroll
// effect calls it, so stub it globally rather than per-test.
Element.prototype.scrollIntoView = () => {};
