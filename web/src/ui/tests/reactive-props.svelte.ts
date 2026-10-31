/** Props a test can change after mounting, as a parent changes them: a Svelte state proxy. */
export function reactiveProps<T extends Record<string, unknown>>(initial: T): T {
  const props = $state(initial);
  return props;
}

/**
 * One prop a test can replace after mounting, held as given (never a deep state proxy, so a
 * value that throws on reading stays as it is): the props object and its setter.
 */
export function rawProp<K extends string, T>(
  key: K,
  initial: T,
): { readonly props: Record<K, T>; readonly set: (next: T) => void } {
  let value = $state.raw(initial);
  const props = {
    get [key](): T {
      return value;
    },
  } as Record<K, T>;
  return {
    props,
    set: (next) => {
      value = next;
    },
  };
}
