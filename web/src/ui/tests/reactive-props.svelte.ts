/** Props a test can change after mounting, as a parent changes them: a Svelte state proxy. */
export function reactiveProps<T extends Record<string, unknown>>(initial: T): T {
  const props = $state(initial);
  return props;
}
