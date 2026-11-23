/**
 * The words of the mode switch (flights spec D2, D17): its name and each mode's label, shared by
 * every mode, so a new mode adds its label here (or in its own copy module) and touches no other
 * mode's words. Held to the house style by scripts/check-copy.mjs, as copy.ts is. It loads with
 * the switch, never in the page's first script.
 */

function deepFreeze<T>(value: T): T {
  if (typeof value === 'object' && value !== null && !Object.isFrozen(value)) {
    for (const key of Reflect.ownKeys(value)) {
      deepFreeze((value as Record<PropertyKey, unknown>)[key]);
    }
    Object.freeze(value);
  }
  return value;
}

/** The mode switch at the top of the page (modes/registry.ts). */
export const modesCopy = /* @__PURE__ */ deepFreeze({
  label: 'Show',
  schools: 'Schools',
  flights: 'Flights',
});
