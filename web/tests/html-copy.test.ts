import { describe, expect, it } from 'vitest';

import { copy } from '../src/copy';
import { waitlistCopy } from '../src/copy-waitlist';
import { escapeHtml, pageCopy, renderHtmlCopy } from '../tools/html-copy';
import indexHtml from '../index.html?raw';
import privacyHtml from '../privacy.html?raw';

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
    const rendered = renderHtmlCopy(indexHtml, pageCopy(copy, waitlistCopy));
    expect(rendered).not.toMatch(/%copy\./);
    expect(rendered).toContain(`<title>${copy.appName}</title>`);
    expect(rendered).toContain(`content="${copy.meta.description}"`);
    expect(indexHtml).toMatch(/<title>%copy\.appName%<\/title>/);
  });

  it('fills the waitlist and its privacy page from the waitlist words', () => {
    const tree = pageCopy(copy, waitlistCopy);
    expect(renderHtmlCopy(indexHtml, tree)).toContain(`>${waitlistCopy.headline}</h1>`);
    const privacy = renderHtmlCopy(privacyHtml, tree);
    expect(privacy).not.toMatch(/%copy\./);
    expect(privacy).toContain(`<title>${waitlistCopy.privacy.title}</title>`);
  });
});

describe('pageCopy', () => {
  it('puts the waitlist words beside copy.ts and leaves copy.ts alone without them', () => {
    expect(pageCopy(copy, undefined)).toBe(copy);
    expect(renderHtmlCopy('%copy.waitlist.when%', pageCopy(copy, waitlistCopy))).toBe(
      waitlistCopy.when,
    );
  });

  it('refuses a copy tree that already has its own waitlist', () => {
    expect(() => pageCopy({ waitlist: 'x' }, waitlistCopy)).toThrow(/own "waitlist"/);
  });
});
