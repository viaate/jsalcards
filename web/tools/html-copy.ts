import type { Plugin } from 'vite';

/** Matches `%copy.some.path%` placeholders in index.html. */
const TOKEN = /%copy\.([A-Za-z0-9_.]+)%/g;

const HTML_ESCAPES: Readonly<Record<string, string>> = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
};

export function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (char) => HTML_ESCAPES[char] ?? char);
}

function lookup(source: unknown, path: string): string {
  let node: unknown = source;
  for (const key of path.split('.')) {
    if (typeof node !== 'object' || node === null || !Object.hasOwn(node, key)) {
      throw new Error(`html-copy: "copy.${path}" does not exist in src/copy.ts`);
    }
    node = (node as Record<string, unknown>)[key];
  }
  if (typeof node !== 'string') {
    throw new Error(`html-copy: "copy.${path}" is not a string`);
  }
  return node;
}

/**
 * Replaces every `%copy.path%` placeholder with the HTML-escaped string from
 * the copy object, so index.html never carries a string of its own.
 */
export function renderHtmlCopy(html: string, source: unknown): string {
  return html.replace(TOKEN, (_match, path: string) => escapeHtml(lookup(source, path)));
}

/** Vite plugin that fills index.html placeholders from src/copy.ts. */
export function htmlCopy(source: unknown): Plugin {
  return {
    name: 'snowlight:html-copy',
    transformIndexHtml: {
      order: 'pre',
      handler: (html) => renderHtmlCopy(html, source),
    },
  };
}
