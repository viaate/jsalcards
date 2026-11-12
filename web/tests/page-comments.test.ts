import { describe, expect, it } from 'vitest';

import indexHtml from '../index.html?raw';
import { dropComments, dropLineComments } from '../tools/page-comments.ts';

/** The map's built page without the comments written for its readers (tools/page-comments.ts). */
describe('the page without its comments', () => {
  it('drops every explaining comment of index.html and keeps its markers', () => {
    const out = dropComments(indexHtml);
    const markers = indexHtml.match(/<!-- [\w-]+(?::[\w-]+)* -->/gu) ?? [];
    expect(markers).toContain('<!-- geo:still:start -->');
    expect(out.match(/<!--[\s\S]*?-->/gu) ?? []).toEqual(markers);
    expect(out.length).toBeLessThan(indexHtml.length);
  });

  it("drops a classic script's whole-line comments, and nothing else of any script", () => {
    expect(dropComments('<script>\n  // why\n  var a = 1; // kept\n</script>')).toBe(
      '<script>\n  var a = 1; // kept\n</script>',
    );
    expect(dropComments('<script data-x="1">\n// why\nrun();\n</script>')).toBe(
      '<script data-x="1">\nrun();\n</script>',
    );
    for (const kept of [
      '<script type="module">\n// why\n</script>',
      '<script type="application/json">\n// not code\n</script>',
      '<script src="/a.js">\n// why\n</script>',
    ]) {
      expect(dropComments(kept)).toBe(kept);
    }
    // Where a line could sit inside a template or a string, the code is left as it is.
    for (const code of ['\nvar a = `\n// text\n`;\n', "\nvar a = 'x\\\n// text';\n"]) {
      expect(dropLineComments(code)).toBe(code);
    }
  });

  it('leaves every inline script of index.html the same code', () => {
    const scripts = (html: string) =>
      [...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gu)].map((m) =>
        (m[1] ?? '').replace(/^[ \t]*\/\/[^\n]*\n/gmu, ''),
      );
    expect(scripts(dropComments(indexHtml))).toEqual(scripts(indexHtml));
  });
});
