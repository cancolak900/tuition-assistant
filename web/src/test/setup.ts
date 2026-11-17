// jsdom has no layout, so window.scrollTo only prints "Not implemented"; tests that care stub it themselves.
// (Skipped for tests that run in the node environment, which has no window.)
if (typeof window !== "undefined") window.scrollTo = () => {};
