import type { Plugin } from 'vite';

/**
 * The map's built page without the words written for its readers: index.html explains itself in
 * HTML comments and in its inline scripts' line comments, and a phone downloads none of them
 * (e2e/shell.spec.ts PAGE_GZIP_BUDGET). A marker comment, `<!-- name:part:start -->` and the
 * like, stays, since the build's own scripts look for them (scripts/build-geo.mjs geo:still).
 */
const COMMENT = /[ \t]*<!--([\s\S]*?)-->[ \t]*\n?/gu;
const MARKER = /^ [\w-]+(?::[\w-]+)* $/u;
/** A classic inline script: no src and no type, or a JavaScript one. */
const SCRIPT =
  /(<script(?![^>]*\bsrc=)(?![^>]*\btype="(?!text\/javascript")[^"]*")[^>]*>)([\s\S]*?)(<\/script>)/gu;
/** A line that is only a line comment. */
const LINE_COMMENT = /^[ \t]*\/\/[^\n]*\n/gmu;

/**
 * A script's code without its whole-line comments. Only where no line of it can be inside a
 * string or a template: none has a backquote and none ends in a backslash.
 */
export function dropLineComments(code: string): string {
  if (code.includes('`') || code.includes('\\\n')) return code;
  return code.replace(LINE_COMMENT, '');
}

/** The page without its comments, its markers kept. */
export function dropComments(html: string): string {
  return html
    .replace(COMMENT, (all, text: string) => (MARKER.test(text) ? all : ''))
    .replace(
      SCRIPT,
      (_all, open: string, code: string, close: string) =>
        `${open}${dropLineComments(code)}${close}`,
    );
}

/** The Vite plugin, for the map's own index.html (and no other page). */
export function pageComments(): Plugin {
  return {
    name: 'snowlight:page-comments',
    transformIndexHtml: {
      order: 'post',
      handler(html, context) {
        return context.path === '/index.html' ? dropComments(html) : html;
      },
    },
  };
}
