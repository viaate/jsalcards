/**
 * Each Schools piece's shared class in the other modes (flights spec D1, LR-F14.1). A mode gives
 * its own menu, search results and update line these classes beside its own (modes/registry.ts),
 * and every theme rule that draws Schools' piece draws them too (css.ts, snowball.ts), so a new
 * mode wears every theme as Schools does with no edit here.
 */
export const MODE_SIBLINGS: Readonly<Record<string, readonly string[]>> = {
  '.menu': ['.mode-menu'],
  '.results': ['.mode-results'],
  '.updated': ['.mode-updated'],
};

/** A piece and its siblings. */
export function withSiblings(piece: string): readonly string[] {
  return [piece, ...(MODE_SIBLINGS[piece] ?? [])];
}

/** `root piece rest` for the piece and each sibling, as one selector list. */
export function selectorsOf(root: string, piece: string, rest = ''): string {
  return withSiblings(piece)
    .map((each) => `${root} ${each}${rest}`)
    .join(',');
}
