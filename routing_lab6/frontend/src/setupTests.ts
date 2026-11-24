import "@testing-library/jest-dom/vitest";

// jsdom doesn't implement scrollIntoView - ChatWindow's auto-scroll
// effect calls it, so stub it globally rather than per-test.
Element.prototype.scrollIntoView = () => {};

// jsdom doesn't implement object URLs - attachment previews
// (Composer/MessageAttachments) create and revoke them.
if (typeof URL.createObjectURL !== "function") {
  URL.createObjectURL = () => "blob:mock";
}
if (typeof URL.revokeObjectURL !== "function") {
  URL.revokeObjectURL = () => {};
}
