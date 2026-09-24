import { describe, expect, it } from 'vitest';

import { copy } from '../src/copy';
import { escapeHtml, renderHtmlCopy } from '../tools/html-copy';
import indexHtml from '../index.html?raw';

describe('renderHtmlCopy', () => {
  it('fills placeholders from the copy object', () => {
    const html = '<title>%copy.appName%</title><p>%copy.status.closed%</p>';
    expect(renderHtmlCopy(html, copy)).toBe('<title>Snowlight</title><p>Closed</p>');
  });

  it('escapes HTML-significant characters', () => {
    expect(escapeHtml(`<a href="x">Tom & Jerry's</a>`)).toBe(
      '&lt;a href=&quot;x&quot;&gt;Tom &amp; Jerry&#39;s&lt;/a&gt;',
    );
    expect(renderHtmlCopy('%copy.a%', { a: '"<b>"' })).toBe('&quot;&lt;b&gt;&quot;');
  });

  it('refuses a placeholder with no matching string', () => {
    expect(() => renderHtmlCopy('%copy.missing%', copy)).toThrow(/does not exist/);
    expect(() => renderHtmlCopy('%copy.status%', copy)).toThrow(/is not a string/);
    expect(() => renderHtmlCopy('%copy.appName.length%', copy)).toThrow(/does not exist/);
  });

  it('leaves index.html with no unfilled placeholders and no strings of its own', () => {
    const rendered = renderHtmlCopy(indexHtml, copy);
    expect(rendered).not.toMatch(/%copy\./);
    expect(rendered).toContain(`<title>${copy.appName}</title>`);
    expect(rendered).toContain(`content="${copy.meta.description}"`);
    expect(indexHtml).toMatch(/<title>%copy\.appName%<\/title>/);
  });
});
