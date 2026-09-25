#!/usr/bin/env node
// @ts-check
/**
 * The copy lint: `npm run lint:copy`, also part of `npm test`.
 *
 * Every customer-facing string lives in src/copy.ts and follows one house style:
 * short, plain, confident, sentence case, with no banned word, exclamation
 * mark, emoji or em dash. This file holds those rules once, for two callers:
 *
 * - `problems(text)` checks one string. src/copy.test.ts runs it over every
 *   string in copy.ts and over the formatters' output.
 * - `lintProject({ root })` checks everything around copy.ts:
 *   - No literal text reaches the page from src/. The components and page
 *     scripts are read as one program, and every string literal is followed
 *     wherever it can go: through constants and later assignments, objects,
 *     arrays, maps and class fields, {#each} and {#await} blocks, snippets and
 *     {@render}, functions, callbacks, actions and promises, component props
 *     and context, stores, and imports between files (JSON, ?raw files and the
 *     VITE_ variables of .env files included). What a method's arguments add to
 *     its result, or push into what it is called on, is followed whatever the
 *     method is called on: `name.concat(' more')`, `copy.x.replace('a', 'b')`,
 *     `rows.join(' and ')` and `rows.push('Other')` count even when `name`,
 *     `rows` or `copy.x` hold nothing the lint can read. A literal that reaches a place a person reads or hears is reported
 *     where it is written, with the place: markup text, text attributes
 *     (placeholder, aria-label, title, alt and the like, also spread or bound,
 *     and any attribute CSS shows with `content: attr(…)`), {@html}, CSS
 *     `content` and list markers, DOM writes (textContent, setAttribute,
 *     append, dataset, …), dialogs, notifications, the share sheet, the
 *     clipboard, speech, map popups and map labels. Only a few symbols such as
 *     the middle dot may be written in place.
 *   - Strings from copy.ts are the only text that gets through, read from
 *     copy.ts as it runs: the strings of its `copy` tree and what its
 *     formatters return. Its keys (`Object.keys(copy.status)`), its other
 *     strings (STATUS_KEYS) and copy cut or recased by a method are reported
 *     where they show. So are a caught error's words (`error.message`, {:catch},
 *     `.catch()`, <svelte:boundary>, error listeners), dates written out by
 *     JavaScript or worded by Intl (month and day names, relative times, units),
 *     and the browser's own labels (a submit button without a value, <details>
 *     without a <summary>).
 *   - Text handed to code the lint does not read (a package, a global of the
 *     page, a template tag) counts where it reads as words: `upperFirst('closed
 *     today')` is reported, `params.get('q')` is not.
 *   - The lint reads code as written; it is a guard against mistakes, not
 *     against text built on purpose to hide from it (String.fromCharCode,
 *     text fetched at run time). A file it cannot parse fails the lint.
 *   - index.html fills every visible string (title, description, Open Graph and
 *     Twitter meta, JSON-LD, text, labels) with a %copy.path% placeholder, and
 *     the filled-in page passes `problems`. Its inline scripts and CSS are read
 *     like the files in src/.
 *   - Web app manifests (public/, a `manifest` built in vite.config.ts or src/,
 *     and with --dist the built ones) carry exactly the text of copy.manifest
 *     (or another string of copy.ts) and pass `problems`. Pages served as they
 *     are (public/*.html, and with --dist the built site) pass `problems` too.
 *   - Every string in copy.ts passes `problems`.
 *
 * The one exception to the house style is the license-required map
 * attribution inside MapLibre's collapsed attribution control; it is not
 * customer copy and is never scanned.
 *
 * Usage: node scripts/check-copy.mjs [--root <web dir>] [--dist <build dir>] [--json]
 */

import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { readdir, readFile } from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath, pathToFileURL } from 'node:url';

import { renderHtmlCopy } from '../tools/html-copy.ts';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const WEB_ROOT = path.resolve(HERE, '..');

// House style --------------------------------------------------------------------------

/**
 * Banned words and phrases, matched case-insensitively as whole words. Each
 * pattern also catches the word's other forms. The first block is the spec's
 * list; the rest are the same rules under other names (hedges, apologies,
 * credits, and how the site works).
 * @type {ReadonlyArray<readonly [label: string, pattern: string]>}
 */
export const BANNED = [
  ['may', 'may'],
  ['might', 'might'],
  ['estimate', 'estimat(?:e|es|ed|ing|ion|ions)'],
  ['approximate', 'approx|approximat(?:e|es|ed|ely|ion|ions)'],
  ['disclaimer', 'disclaim(?:s|ed|er|ers)?'],
  ['beta', 'beta'],
  ['source', 'sourc(?:e|es|ed|ing)'],
  ['data provided', 'data\\s+provided'],
  ['powered by', 'powered\\s+by'],
  ['algorithm', 'algorithm(?:s|ic|ically)?'],
  ['sorry', 'sorry'],
  ['please note', 'please\\s+note'],
  ['accuracy', '(?:in)?accura(?:cy|te|tely)'],
  ['maybe', 'maybe'],
  ['perhaps', 'perhaps'],
  ['possibly', 'possibl[ey]'],
  ['probably', 'probabl[ey]'],
  ['likely', '(?:un)?likely'],
  ['roughly', 'roughly'],
  ['unfortunately', 'unfortunate(?:ly)?'],
  ['apologize', 'apolog(?:y|ies|ise|ize|ised|ized)'],
  ['oops', 'oops'],
  ['caveat', 'caveats?'],
  ['provided by', 'provided\\s+by'],
  ['courtesy of', 'courtesy\\s+of'],
  ['according to', 'according\\s+to'],
  ['data from', 'data\\s+from'],
  ['credit', 'credit(?:s|ed)?'],
  ['artificial intelligence', 'artificial\\s+intelligence'],
  ['machine learning', 'machine\\s+learning'],
  ['model', 'model(?:s|ed|ing|led|ling)?'],
  ['neural', 'neural'],
  ['LLM', 'llms?'],
  ['scrape', 'scrap(?:e|es|ed|ing|er|ers)'],
  ['crawl', 'crawl(?:s|ed|ing|er|ers)?'],
];

/**
 * Words that keep a capital letter anywhere in a sentence. Anything else
 * capitalized after a sentence's first word reads as Title Case.
 */
export const PROPER_NOUNS = new Set([
  'Snowlight',
  'US',
  'ZIP',
  'AM',
  'PM',
  'K-12',
  'I',
  ...['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August'],
  ...['September', 'October', 'November', 'December'],
  ...['Jan', 'Feb', 'Mar', 'Apr', 'Jun', 'Jul', 'Aug', 'Sep', 'Sept', 'Oct', 'Nov', 'Dec'],
  ...['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'],
  ...['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
]);

// Whole words by Unicode letters and digits, not just ASCII \b.
const BEFORE = '(?<![\\p{L}\\p{N}_])';
const AFTER = '(?![\\p{L}\\p{N}_])';

/** @type {ReadonlyArray<readonly [string, RegExp]> | undefined} */
let bannedPatterns;

/** @returns {ReadonlyArray<readonly [string, RegExp]>} */
function compiledBanned() {
  bannedPatterns ??= BANNED.map(
    ([label, pattern]) =>
      /** @type {const} */ ([label, new RegExp(`${BEFORE}(?:${pattern})${AFTER}`, 'giu')]),
  );
  return bannedPatterns;
}

const AI = new RegExp(`${BEFORE}(?:AI|A\\.I\\.)(?![\\p{L}\\p{N}_])`, 'u');
const EXCLAMATION = /[!¡‼⁉]/u;
const EMOJI = /\p{Extended_Pictographic}|\p{Regional_Indicator}|[\u{1F3FB}-\u{1F3FF}]|⃣|️/u;
const EM_DASH = /[—―⸺⸻]|--/u;
const STRAIGHT_QUOTE = /['"]/u;
const CONTROL_SPACE = /[\t\n\r\v\f]/u;
const DOUBLE_SPACE = /\s{2,}/u;
/** Ends a sentence or a part of a line; the next word may be capitalized. */
const SEGMENT_BREAK = /(?<=[.?])\s+|\s+·\s+|:\s+/u;
/** A word's edges that are not part of the word. */
const EDGE_PUNCTUATION = /^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu;

/**
 * House-style problems in one customer-facing string; empty when it is fine.
 * @param {string} text
 * @returns {string[]}
 */
export function problems(text) {
  /** @type {string[]} */
  const found = [];
  if (text.length === 0) return ['empty string'];

  for (const [label, pattern] of compiledBanned()) {
    for (const match of text.matchAll(pattern)) {
      // "May" before a day number is the month: "May 4".
      const month =
        label === 'may' &&
        match[0] === 'May' &&
        /^\s+\d/u.test(text.slice(match.index + match[0].length));
      if (!month) {
        found.push(`banned phrase "${label}"`);
        break;
      }
    }
  }
  if (AI.test(text)) found.push('banned phrase "AI"');
  if (EXCLAMATION.test(text)) found.push('exclamation mark');
  if (EMOJI.test(text)) found.push('emoji');
  if (EM_DASH.test(text)) found.push('em dash');
  if (STRAIGHT_QUOTE.test(text)) found.push('straight quote: use ’ or “ ”');
  if (text.includes('...')) found.push('three dots: use …');
  if (text !== text.trim()) found.push('leading or trailing space');
  if (CONTROL_SPACE.test(text)) found.push('tab or line break');
  else if (DOUBLE_SPACE.test(text)) found.push('double space');

  if (/^\p{Ll}/u.test(text)) found.push('starts with a lowercase letter');
  for (const segment of text.split(SEGMENT_BREAK)) {
    const words = segment
      .split(/\s+/u)
      .map((word) => word.replace(EDGE_PUNCTUATION, ''))
      .filter((word) => word.length > 0);
    words.forEach((word, index) => {
      if (PROPER_NOUNS.has(word)) return;
      if (/\p{L}/u.test(word) && word.length > 1 && word === word.toUpperCase()) {
        found.push(`all caps "${word}"`);
      } else if (index > 0 && /^\p{Lu}/u.test(word)) {
        found.push(`Title Case "${word}"`);
      }
    });
  }
  return found;
}

// Where text shows ---------------------------------------------------------------------------

/**
 * Symbols a component may write as literal text between expressions. Anything
 * else (a letter, a digit, an arrow, ©) comes from copy.ts.
 */
export const ALLOWED_SYMBOLS = new Set(['·', '•', '/', '–', '×', '%', ',', ':', '(', ')', '+']);

/**
 * Whether literal text is only whitespace and allowed symbols.
 * @param {string} text
 */
function isSymbolsOnly(text) {
  for (const char of text) {
    if (!/\s/u.test(char) && !ALLOWED_SYMBOLS.has(char)) return false;
  }
  return true;
}

/**
 * Whether text reads as words rather than a key, a class name, a path or a
 * time zone: two or more words, or one capitalized word. Used only where the
 * lint cannot see how a value is shown (a component from a package).
 * @param {string} text
 */
function looksLikeProse(text) {
  const words = text
    .split(/\s+/u)
    .map((word) => word.replace(EDGE_PUNCTUATION, ''))
    .filter((word) => /^[\p{L}’'-]+$/u.test(word));
  return words.length >= 2
    ? words.some((word) => word.length > 1)
    : /^\p{Lu}\p{Ll}+$/u.test(text.trim());
}

/** Attributes whose value a person reads or hears. */
const TEXT_ATTRIBUTES = new Set([
  'placeholder',
  'aria-label',
  'title',
  'alt',
  'label',
  'aria-description',
  'aria-roledescription',
  'aria-valuetext',
  'aria-placeholder',
  'aria-braillelabel',
  'aria-brailleroledescription',
]);

/** Component props that, by name, carry text to show. */
const TEXT_PROPS = new Set([
  ...TEXT_ATTRIBUTES,
  'ariaLabel',
  'text',
  'heading',
  'caption',
  'description',
  'message',
  'tooltip',
  'subtitle',
  'hint',
]);

/** Input types whose value shows: typed text, or a button's label. An absent type is text. */
const SHOWN_VALUE_INPUTS = new Set([
  '',
  'text',
  'search',
  'email',
  'url',
  'tel',
  'button',
  'submit',
  'reset',
]);

/** Meta tags whose content shows up in a search result, a share preview or on a home screen. */
const VISIBLE_META = new Set([
  'description',
  'application-name',
  'apple-mobile-web-app-title',
  'og:title',
  'og:description',
  'og:site_name',
  'og:image:alt',
  'twitter:title',
  'twitter:description',
  'twitter:image:alt',
]);

/** @param {string | undefined} name */
function isVisibleMeta(name) {
  return name !== undefined && VISIBLE_META.has(name.toLowerCase());
}

/**
 * Whether an attribute of an HTML element shows its value.
 * @param {string} element
 * @param {string} attribute
 * @param {string} inputType
 * @param {string | undefined} metaName
 * @param {ReadonlySet<string>} [cssShown] Attributes that CSS shows with `content: attr(…)`.
 */
function showsText(element, attribute, inputType, metaName, cssShown) {
  if (TEXT_ATTRIBUTES.has(attribute)) return true;
  if (cssShown?.has(attribute.toLowerCase()) === true) return true;
  if (attribute === 'value') {
    return element === 'textarea' || (element === 'input' && SHOWN_VALUE_INPUTS.has(inputType));
  }
  return attribute === 'content' && element === 'meta' && isVisibleMeta(metaName);
}

/**
 * Element properties that put text on screen or in the accessibility tree.
 * Generic names such as `value`, `data` and `text` are left out: they are far
 * more often fields of plain objects than of elements.
 */
const DOM_TEXT_PROPERTIES = new Set([
  'textContent',
  'innerText',
  'outerText',
  'innerHTML',
  'outerHTML',
  'nodeValue',
  'title',
  'placeholder',
  'alt',
  'label',
  'ariaLabel',
  'ariaDescription',
  'ariaRoleDescription',
  'ariaValueText',
  'ariaPlaceholder',
  'ariaBrailleLabel',
  'ariaBrailleRoleDescription',
  // A <meta>'s content: a share preview or a search result.
  'content',
]);
/** Properties among those that take HTML. */
const DOM_HTML_PROPERTIES = new Set(['innerHTML', 'outerHTML']);
/**
 * Names among those that plain objects use too. Setting one on an object of
 * the project (`state.title = …`) is not a DOM write; where that object is
 * shown, its text is followed there.
 */
const SHARED_PROPERTY_NAMES = new Set(['title', 'label', 'alt', 'placeholder', 'content']);
/** Intl formatters that always write words. */
const WORD_FORMATTERS = new Set([
  'RelativeTimeFormat',
  'ListFormat',
  'DisplayNames',
  'DurationFormat',
]);
/** Date methods that always write words (month and day names, AM and PM, zone names). */
const DATE_WORD_METHODS = new Set([
  'toLocaleDateString',
  'toLocaleTimeString',
  'toDateString',
  'toTimeString',
  'toUTCString',
  'toGMTString',
]);
/**
 * Format options that write words: month and day names, eras and zone names
 * for dates; units, long compact numbers ("1.2 thousand") and currency names
 * for numbers. Undefined: any value.
 * @type {ReadonlyMap<string, ReadonlySet<string> | undefined>}
 */
const WORD_OPTIONS = new Map([
  ['month', new Set(['short', 'long', 'narrow'])],
  ['weekday', undefined],
  ['era', undefined],
  ['timeZoneName', undefined],
  ['dayPeriod', undefined],
  ['style', new Set(['unit'])],
  ['compactDisplay', new Set(['long'])],
  ['currencyDisplay', new Set(['name'])],
]);
/** Svelte's runes: `$state.raw` is a rune even where a `state` variable exists. */
const RUNES = new Set([
  '$state',
  '$derived',
  '$effect',
  '$props',
  '$bindable',
  '$inspect',
  '$host',
]);
/** Browser dialogs, called as globals or on the window. */
const DIALOG_CALLS = new Set(['alert', 'confirm', 'prompt']);
/** Globals that stand for the window: `window.alert`. */
const WINDOW_NAMES = new Set(['window', 'globalThis', 'self']);

// Syntax trees ---------------------------------------------------------------------------------

/**
 * @typedef {object} Finding
 * @property {string} file Path relative to the project root, with forward slashes.
 * @property {number} line 1-based.
 * @property {number} column 1-based.
 * @property {string} message
 */

// Syntax trees from two parsers (Svelte, which also reads the scripts, and
// parse5) are read through these few guards rather than trusted as any.

/** @typedef {Record<string, unknown>} Fields */
/** @typedef {Fields & { type: string }} Node */

/**
 * @param {unknown} value
 * @returns {value is Fields}
 */
function isFields(value) {
  return typeof value === 'object' && value !== null;
}

/**
 * @param {unknown} value
 * @returns {value is Node}
 */
function isNode(value) {
  return isFields(value) && typeof value.type === 'string';
}

/**
 * @param {Fields | undefined} fields
 * @param {string} key
 * @returns {Node | undefined}
 */
function nodeAt(fields, key) {
  const value = fields?.[key];
  return isNode(value) ? value : undefined;
}

/**
 * @param {Fields | undefined} fields
 * @param {string} key
 * @returns {Fields[]}
 */
function listAt(fields, key) {
  const value = fields?.[key];
  return Array.isArray(value) ? value.filter(isFields) : [];
}

/**
 * @param {Fields | undefined} fields
 * @param {string} key
 * @returns {Node[]}
 */
function nodesAt(fields, key) {
  return listAt(fields, key).filter(isNode);
}

/**
 * The entries of a list with its holes kept, so positions line up.
 * @param {Fields | undefined} fields
 * @param {string} key
 * @returns {Array<Node | undefined>}
 */
function slotsAt(fields, key) {
  const value = fields?.[key];
  return Array.isArray(value) ? value.map((entry) => (isNode(entry) ? entry : undefined)) : [];
}

/**
 * @param {Fields | undefined} fields
 * @param {string} key
 * @returns {string | undefined}
 */
function stringAt(fields, key) {
  const value = fields?.[key];
  return typeof value === 'string' ? value : undefined;
}

/**
 * @param {Fields | undefined} fields
 * @param {string} key
 * @returns {number | undefined}
 */
function numberAt(fields, key) {
  const value = fields?.[key];
  return typeof value === 'number' ? value : undefined;
}

/**
 * @param {string} source
 * @returns {(offset: number) => { line: number, column: number }}
 */
function locator(source) {
  const starts = [0];
  for (let i = 0; i < source.length; i += 1) if (source[i] === '\n') starts.push(i + 1);
  return (offset) => {
    let low = 0;
    let high = starts.length - 1;
    while (low < high) {
      const middle = (low + high + 1) >> 1;
      if ((starts[middle] ?? 0) <= offset) low = middle;
      else high = middle - 1;
    }
    return { line: low + 1, column: offset - (starts[low] ?? 0) + 1 };
  };
}

/** @param {string} text */
function quote(text) {
  const flat = text.replace(/\s+/gu, ' ').trim();
  return `"${flat.length > 60 ? `${flat.slice(0, 57)}…` : flat}"`;
}

/** @param {unknown} error */
function describeError(error) {
  return error instanceof Error ? error.message : String(error);
}

/** Keys of a syntax tree node that hold no code that runs. */
const SKIP_KEYS = new Set([
  'type',
  'start',
  'end',
  'loc',
  'range',
  'metadata',
  'name_loc',
  'leadingComments',
  'trailingComments',
  'typeAnnotation',
  'returnType',
  'typeParameters',
  'typeArguments',
  'superTypeArguments',
  'superTypeParameters',
  'implements',
  'decorators',
]);

/** TypeScript nodes that hold values; every other TS node is a type and never runs. */
const TS_VALUE_NODES = new Set([
  'TSAsExpression',
  'TSSatisfiesExpression',
  'TSNonNullExpression',
  'TSTypeAssertion',
  'TSInstantiationExpression',
  'TSEnumDeclaration',
  'TSEnumBody',
  'TSEnumMember',
  'TSParameterProperty',
  'TSExportAssignment',
]);

/** Expression wrappers that stand for their inner expression: (x), a?.b, x as T, x!, x satisfies T. */
const WRAPPERS = new Set([
  'ParenthesizedExpression',
  'ChainExpression',
  'TSAsExpression',
  'TSSatisfiesExpression',
  'TSNonNullExpression',
  'TSTypeAssertion',
  'TSInstantiationExpression',
]);

const FUNCTION_TYPES = new Set([
  'FunctionDeclaration',
  'FunctionExpression',
  'ArrowFunctionExpression',
]);
const CLASS_TYPES = new Set(['ClassDeclaration', 'ClassExpression']);

/**
 * The expression a wrapper stands for.
 * @param {Node | undefined} node
 * @returns {Node | undefined}
 */
function unwrap(node) {
  let current = node;
  while (current !== undefined && WRAPPERS.has(current.type)) {
    current = nodeAt(current, 'expression');
  }
  return current;
}

/**
 * The name of a key as written: an identifier, a private name, a string or a number.
 * @param {Node | undefined} key
 * @returns {string | undefined}
 */
function keyName(key) {
  if (key?.type === 'Identifier') return stringAt(key, 'name');
  if (key?.type === 'PrivateIdentifier') {
    const name = stringAt(key, 'name');
    return name === undefined ? undefined : `#${name}`;
  }
  if (key?.type === 'Literal' && (typeof key.value === 'string' || typeof key.value === 'number')) {
    return String(key.value);
  }
  return undefined;
}

/**
 * The names a declaration introduces.
 * @param {Node | undefined} declaration
 * @returns {string[]}
 */
function declaredNames(declaration) {
  if (declaration === undefined) return [];
  if (declaration.type === 'VariableDeclaration') {
    return nodesAt(declaration, 'declarations').flatMap((declarator) =>
      patternNames(nodeAt(declarator, 'id')),
    );
  }
  const name = stringAt(nodeAt(declaration, 'id'), 'name');
  return name === undefined ? [] : [name];
}

/**
 * The names a binding pattern introduces.
 * @param {Node | undefined} pattern
 * @returns {string[]}
 */
function patternNames(pattern) {
  switch (pattern?.type) {
    case 'Identifier':
      return [stringAt(pattern, 'name') ?? ''];
    case 'ObjectPattern':
      return nodesAt(pattern, 'properties').flatMap((property) =>
        patternNames(
          property.type === 'RestElement'
            ? nodeAt(property, 'argument')
            : nodeAt(property, 'value'),
        ),
      );
    case 'ArrayPattern':
      return nodesAt(pattern, 'elements').flatMap((element) => patternNames(element));
    case 'AssignmentPattern':
      return patternNames(nodeAt(pattern, 'left'));
    case 'RestElement':
      return patternNames(nodeAt(pattern, 'argument'));
    default:
      return [];
  }
}

/**
 * Whether a node is a global name: an identifier that no scope declares.
 * @param {Project} project
 * @param {Node | undefined} node
 * @param {ReadonlySet<string> | string} names
 */
function isGlobal(project, node, names) {
  const name = node?.type === 'Identifier' ? stringAt(node, 'name') : undefined;
  if (name === undefined || node === undefined) return false;
  const known = typeof names === 'string' ? name === names : names.has(name);
  return known && project.lookup(node) === undefined;
}

// Modules and scopes -----------------------------------------------------------------------------

/**
 * @typedef {'svelte' | 'script' | 'json' | 'text'} ModuleKind
 *
 * @typedef {object} Module One file (or an inline script) read as code.
 * @property {string} file Path shown in findings.
 * @property {string} abs Absolute path, for resolving imports.
 * @property {ModuleKind} kind
 * @property {string} source The text as written.
 * @property {(offset: number) => { line: number, column: number }} at Where an offset of the parsed code is in the file.
 * @property {Node | undefined} root A component's Svelte tree.
 * @property {Node[]} programs The scripts: a component's module and instance scripts, or the file itself.
 * @property {Scope} scope The outermost scope.
 * @property {Node[]} calls Every call, for the call index.
 * @property {Node[]} writes Calls, constructions, assignments and properties that can put text on screen.
 * @property {Node[]} mutations Assignments to a member: `labels.closed = …`.
 * @property {Node[]} components Component tags in the markup.
 * @property {Node[]} actions `use:` directives, which call a function with the element and a value.
 * @property {Node[]} boundaries `<svelte:boundary>` elements, which hand an error to `failed` and `onerror`.
 * @property {{ message: string, offset: number } | undefined} error Why the file could not be read.
 *
 * @typedef {object} Scope
 * @property {Scope | undefined} parent
 * @property {'module' | 'function' | 'arrow' | 'block' | 'class'} kind
 * @property {Node | undefined} self The class whose instance `this` is, in its methods and fields.
 * @property {Map<string, Binding>} names
 * @property {Module} module
 *
 * @typedef {object} Binding A declared name and everything it can hold.
 * @property {string} name
 * @property {Scope} scope
 * @property {Alternative[]} origins
 *
 * @typedef {{ from: Origin, path: Step[] }} Alternative A value, then the destructuring steps into it.
 * @typedef {{ kind: 'expression', node: Node }
 *   | { kind: 'parameter', fn: Node, index: number, rest: boolean }
 *   | { kind: 'element', of: Node }
 *   | { kind: 'key', of: Node }
 *   | { kind: 'callable', node: Node }
 *   | { kind: 'class', node: Node }
 *   | { kind: 'import', source: string, name: string }
 *   | { kind: 'prop', name: string }
 *   | { kind: 'caught', node: Node }
 *   | { kind: 'unknown' }} Origin
 * @typedef {{ key: string | undefined } | { index: number } | { rest: true }} Step
 */

/** @type {Origin} */
const UNKNOWN = { kind: 'unknown' };
/** @type {Step} */
const REST = { rest: true };

/**
 * @param {Alternative[]} alternatives
 * @param {Step} step
 * @returns {Alternative[]}
 */
function stepInto(alternatives, step) {
  return alternatives.map(({ from, path: steps }) => ({ from, path: [...steps, step] }));
}

/**
 * @param {Scope | undefined} start
 * @param {string} name
 * @returns {Binding | undefined}
 */
function findBinding(start, name) {
  for (let scope = start; scope !== undefined; scope = scope.parent) {
    const binding = scope.names.get(name);
    if (binding !== undefined) return binding;
  }
  return undefined;
}

/** Keys under which Svelte nests a fragment of markup. */
const FRAGMENT_KEYS = [
  'fragment',
  'consequent',
  'alternate',
  'body',
  'fallback',
  'pending',
  'then',
  'catch',
];

const ELEMENT_TYPES = new Set([
  'RegularElement',
  'SvelteElement',
  'TitleElement',
  'SlotElement',
  'SvelteHead',
  'SvelteBody',
  'SvelteWindow',
  'SvelteDocument',
  'SvelteFragment',
  'SvelteBoundary',
]);
const COMPONENT_TYPES = new Set(['Component', 'SvelteComponent', 'SvelteSelf']);

/** Builds the scopes of one module and notes the calls and writes in it. */
class ScopeBuilder {
  /**
   * @param {Project} project
   * @param {Module} module
   */
  constructor(project, module) {
    this.project = project;
    this.module = module;
    /** @type {Array<{ target: Node, alternatives: Alternative[] }>} */
    this.assignments = [];
    /** Whether the walk is in a component's instance script, where `export let` declares a prop. */
    this.instance = false;
  }

  /**
   * @param {Scope | undefined} parent
   * @param {Scope['kind']} kind
   * @param {Node} [self]
   * @returns {Scope}
   */
  child(parent, kind, self) {
    return { parent, kind, self, names: new Map(), module: this.module };
  }

  /**
   * @param {Node} node
   * @param {Scope} scope
   */
  record(node, scope) {
    this.project.scopes.set(node, scope);
  }

  /**
   * @param {Scope} scope
   * @param {string} name
   * @param {Alternative[]} origins
   */
  bind(scope, name, origins) {
    const known = scope.names.get(name);
    if (known !== undefined) known.origins.push(...origins);
    else scope.names.set(name, { name, scope, origins: [...origins] });
  }

  /**
   * The scope a `var` lands in.
   * @param {Scope} scope
   */
  hoisting(scope) {
    let current = scope;
    while (current.kind === 'block' && current.parent !== undefined) current = current.parent;
    return current;
  }

  /**
   * Declares the names of a binding pattern, or adds values to names already
   * declared when `assign` is set (`[a, b] = pair`). A declaration also walks
   * the pattern's defaults and computed keys; an assignment's pattern was
   * walked with the rest of its expression.
   * @param {Scope} scope
   * @param {Node | undefined} pattern
   * @param {Alternative[]} alternatives
   * @param {boolean} [assign]
   */
  declare(scope, pattern, alternatives, assign = false) {
    if (pattern === undefined) return;
    this.record(pattern, scope);
    switch (pattern.type) {
      case 'Identifier': {
        const name = stringAt(pattern, 'name') ?? '';
        if (!assign) this.bind(scope, name, alternatives);
        else findBinding(scope, name)?.origins.push(...alternatives);
        return;
      }
      case 'ObjectPattern':
        for (const property of nodesAt(pattern, 'properties')) {
          this.record(property, scope);
          if (property.type === 'RestElement') {
            this.declare(scope, nodeAt(property, 'argument'), stepInto(alternatives, REST), assign);
            continue;
          }
          const key = nodeAt(property, 'key');
          const computed = property.computed === true;
          if (computed && !assign) this.visit(key, scope);
          this.declare(
            scope,
            nodeAt(property, 'value'),
            stepInto(alternatives, { key: computed ? undefined : keyName(key) }),
            assign,
          );
        }
        return;
      case 'ArrayPattern':
        slotsAt(pattern, 'elements').forEach((element, index) => {
          if (element === undefined) return;
          if (element.type === 'RestElement') {
            this.declare(scope, nodeAt(element, 'argument'), stepInto(alternatives, REST), assign);
          } else {
            this.declare(scope, element, stepInto(alternatives, { index }), assign);
          }
        });
        return;
      case 'AssignmentPattern': {
        const fallback = nodeAt(pattern, 'right');
        if (!assign) this.visit(fallback, scope);
        const withDefault = fallback === undefined ? [] : [expressionOrigin(fallback)];
        this.declare(scope, nodeAt(pattern, 'left'), [...alternatives, ...withDefault], assign);
        return;
      }
      case 'RestElement':
        this.declare(scope, nodeAt(pattern, 'argument'), stepInto(alternatives, REST), assign);
        return;
      case 'TSParameterProperty':
        this.declare(scope, nodeAt(pattern, 'parameter'), alternatives, assign);
        return;
      default:
        // A member target (`a.b = c`) is a mutation, read by the call index.
        if (!assign) this.visit(pattern, scope);
    }
  }

  /**
   * Walks script code: scopes, declarations, calls and writes.
   * @param {unknown} value
   * @param {Scope} scope
   */
  visit(value, scope) {
    if (Array.isArray(value)) {
      for (const item of value) this.visit(item, scope);
      return;
    }
    if (!isNode(value)) return;
    const node = value;
    if (node.type.startsWith('TS') && !TS_VALUE_NODES.has(node.type)) return;
    this.record(node, scope);
    switch (node.type) {
      case 'ImportDeclaration':
        this.importDeclaration(node, scope);
        return;
      case 'VariableDeclaration':
        this.variables(node, scope);
        return;
      case 'FunctionDeclaration': {
        const name = stringAt(nodeAt(node, 'id'), 'name');
        if (name !== undefined)
          this.bind(scope, name, [{ from: { kind: 'callable', node }, path: [] }]);
        this.fn(node, scope, undefined);
        return;
      }
      case 'FunctionExpression':
      case 'ArrowFunctionExpression':
        this.fn(node, scope, undefined);
        return;
      case 'ClassDeclaration':
      case 'ClassExpression':
        this.classBody(node, scope);
        return;
      case 'ExportNamedDeclaration': {
        this.children(node, scope);
        // Svelte 4 props: `export let label` also holds what each tag passes.
        const declaration = nodeAt(node, 'declaration');
        if (
          this.instance &&
          declaration?.type === 'VariableDeclaration' &&
          declaration.kind !== 'const'
        ) {
          for (const name of declaredNames(declaration)) {
            this.bind(scope, name, [{ from: { kind: 'prop', name }, path: [] }]);
          }
        }
        return;
      }
      case 'BlockStatement':
      case 'StaticBlock':
      case 'ForStatement':
        this.children(node, this.child(scope, 'block'));
        return;
      case 'ForInStatement':
      case 'ForOfStatement':
        this.loop(node, scope);
        return;
      case 'CatchClause': {
        const inner = this.child(scope, 'block');
        this.declare(inner, nodeAt(node, 'param'), [{ from: { kind: 'caught', node }, path: [] }]);
        this.visit(nodeAt(node, 'body'), inner);
        return;
      }
      case 'SwitchStatement':
        this.visit(nodeAt(node, 'discriminant'), scope);
        this.visit(node.cases, this.child(scope, 'block'));
        return;
      case 'TSEnumDeclaration': {
        const name = stringAt(nodeAt(node, 'id'), 'name');
        if (name !== undefined) this.bind(scope, name, [expressionOrigin(node)]);
        this.visit(node.members, scope);
        this.visit(node.body, scope);
        return;
      }
      case 'AssignmentExpression': {
        const target = nodeAt(node, 'left');
        const right = nodeAt(node, 'right');
        if (unwrap(target)?.type === 'MemberExpression') this.module.mutations.push(node);
        else if (target !== undefined && right !== undefined) {
          this.assignments.push({ target, alternatives: [expressionOrigin(right)] });
        }
        this.module.writes.push(node);
        break;
      }
      case 'CallExpression':
        this.module.calls.push(node);
        this.module.writes.push(node);
        break;
      case 'NewExpression':
        this.module.calls.push(node);
        this.module.writes.push(node);
        break;
      case 'Property': {
        const key = node.computed === true ? undefined : keyName(nodeAt(node, 'key'));
        if (key === 'text-field' || key === 'manifest') this.module.writes.push(node);
        break;
      }
      default:
        break;
    }
    this.children(node, scope);
  }

  /**
   * @param {Node} node
   * @param {Scope} scope
   */
  children(node, scope) {
    for (const [key, child] of Object.entries(node)) {
      if (!SKIP_KEYS.has(key)) this.visit(child, scope);
    }
  }

  /**
   * @param {Node} node
   * @param {Scope} scope
   */
  importDeclaration(node, scope) {
    if (node.importKind === 'type') return;
    const source = stringAt(nodeAt(node, 'source'), 'value') ?? '';
    for (const specifier of nodesAt(node, 'specifiers')) {
      this.record(specifier, scope);
      if (specifier.importKind === 'type') continue;
      const local = stringAt(nodeAt(specifier, 'local'), 'name');
      const name =
        specifier.type === 'ImportDefaultSpecifier'
          ? 'default'
          : specifier.type === 'ImportNamespaceSpecifier'
            ? '*'
            : keyName(nodeAt(specifier, 'imported'));
      if (local !== undefined && name !== undefined) {
        this.bind(scope, local, [{ from: { kind: 'import', source, name }, path: [] }]);
      }
    }
  }

  /**
   * @param {Node} node
   * @param {Scope} scope
   */
  variables(node, scope) {
    const target = node.kind === 'var' ? this.hoisting(scope) : scope;
    for (const declarator of nodesAt(node, 'declarations')) {
      this.record(declarator, scope);
      const init = nodeAt(declarator, 'init');
      this.visit(init, scope);
      this.declare(target, nodeAt(declarator, 'id'), [
        init === undefined ? { from: UNKNOWN, path: [] } : expressionOrigin(init),
      ]);
    }
  }

  /**
   * A function's own scope: its parameters, and its name inside a named function expression.
   * @param {Node} node
   * @param {Scope} scope
   * @param {Node | undefined} self The class, for a method.
   */
  fn(node, scope, self) {
    const inner = this.child(
      scope,
      node.type === 'ArrowFunctionExpression' ? 'arrow' : 'function',
      self,
    );
    const name = stringAt(nodeAt(node, 'id'), 'name');
    if (node.type === 'FunctionExpression' && name !== undefined) {
      this.bind(inner, name, [{ from: { kind: 'callable', node }, path: [] }]);
    }
    let params = nodesAt(node, 'params');
    // TypeScript's `this: T` parameter is a type, not an argument.
    if (params[0]?.type === 'Identifier' && params[0].name === 'this') params = params.slice(1);
    params.forEach((param, index) => {
      const rest = param.type === 'RestElement';
      this.declare(inner, param, [
        { from: { kind: 'parameter', fn: node, index, rest }, path: [] },
      ]);
    });
    const body = nodeAt(node, 'body');
    if (body?.type === 'BlockStatement') {
      this.record(body, inner);
      this.visit(body.body, inner);
    } else {
      this.visit(body, inner);
    }
  }

  /**
   * @param {Node} node
   * @param {Scope} scope
   */
  classBody(node, scope) {
    const name = stringAt(nodeAt(node, 'id'), 'name');
    const inner = this.child(scope, 'class', node);
    if (name !== undefined) {
      this.bind(node.type === 'ClassDeclaration' ? scope : inner, name, [
        { from: { kind: 'class', node }, path: [] },
      ]);
    }
    this.visit(nodeAt(node, 'superClass'), scope);
    for (const member of nodesAt(nodeAt(node, 'body'), 'body')) {
      this.record(member, inner);
      const key = nodeAt(member, 'key');
      if (member.computed === true) this.visit(key, inner);
      else if (key !== undefined) this.record(key, inner);
      const value = nodeAt(member, 'value');
      if (member.type === 'MethodDefinition' && value !== undefined) {
        this.record(value, inner);
        this.fn(value, inner, node);
      } else if (member.type === 'StaticBlock') {
        this.visit(member.body, this.child(inner, 'block'));
      } else {
        this.visit(value, inner);
      }
    }
  }

  /**
   * `for (const x of list)` and `for (const key in object)`.
   * @param {Node} node
   * @param {Scope} scope
   */
  loop(node, scope) {
    const inner = this.child(scope, 'block');
    const right = nodeAt(node, 'right');
    this.visit(right, scope);
    const left = nodeAt(node, 'left');
    if (right !== undefined && left !== undefined) {
      /** @type {Alternative[]} */
      const each = [
        {
          from:
            node.type === 'ForOfStatement'
              ? { kind: 'element', of: right }
              : { kind: 'key', of: right },
          path: [],
        },
      ];
      if (left.type === 'VariableDeclaration') {
        const target = left.kind === 'var' ? this.hoisting(scope) : inner;
        this.record(left, inner);
        for (const declarator of nodesAt(left, 'declarations')) {
          this.record(declarator, inner);
          this.declare(target, nodeAt(declarator, 'id'), each);
        }
      } else {
        this.visit(left, inner);
        this.assignments.push({ target: left, alternatives: each });
      }
    }
    this.visit(nodeAt(node, 'body'), inner);
  }

  /**
   * Walks a fragment of markup: its expressions, {#each} and {#snippet}
   * scopes, {@const} tags and component tags.
   * @param {Node | undefined} fragment
   * @param {Scope} scope
   * @param {Scope} [snippets] Where the fragment's snippets are declared; its own scope by default.
   */
  markup(fragment, scope, snippets) {
    if (fragment === undefined) return;
    const inner = this.child(scope, 'block');
    this.record(fragment, inner);
    const nodes = nodesAt(fragment, 'nodes');
    // A snippet can be rendered anywhere in its fragment, before or after it.
    for (const node of nodes) {
      const name = stringAt(nodeAt(node, 'expression'), 'name');
      if (node.type === 'SnippetBlock' && name !== undefined) {
        this.bind(snippets ?? inner, name, [{ from: { kind: 'callable', node }, path: [] }]);
      }
    }
    for (const node of nodes) this.markupNode(node, inner);
  }

  /**
   * @param {Node} node
   * @param {Scope} scope
   */
  markupNode(node, scope) {
    this.record(node, scope);
    switch (node.type) {
      case 'Text':
      case 'Comment':
      case 'DebugTag':
        return;
      case 'ExpressionTag':
      case 'HtmlTag':
      case 'RenderTag':
      case 'AttachTag':
        this.visit(nodeAt(node, 'expression'), scope);
        return;
      case 'ConstTag':
        this.visit(nodeAt(node, 'declaration'), scope);
        return;
      case 'EachBlock': {
        const expression = nodeAt(node, 'expression');
        this.visit(expression, scope);
        const body = this.child(scope, 'block');
        if (expression !== undefined) {
          this.declare(body, nodeAt(node, 'context'), [
            { from: { kind: 'element', of: expression }, path: [] },
          ]);
        }
        const index = stringAt(node, 'index');
        if (index !== undefined) this.bind(body, index, [{ from: UNKNOWN, path: [] }]);
        this.visit(nodeAt(node, 'key'), body);
        this.markup(nodeAt(node, 'body'), body);
        this.markup(nodeAt(node, 'fallback'), scope);
        return;
      }
      case 'AwaitBlock': {
        this.visit(nodeAt(node, 'expression'), scope);
        this.markup(nodeAt(node, 'pending'), scope);
        const then = this.child(scope, 'block');
        const awaited = nodeAt(node, 'expression');
        this.declare(then, nodeAt(node, 'value'), [
          awaited === undefined ? { from: UNKNOWN, path: [] } : expressionOrigin(awaited),
        ]);
        this.markup(nodeAt(node, 'then'), then);
        const failed = this.child(scope, 'block');
        this.declare(failed, nodeAt(node, 'error'), [{ from: { kind: 'caught', node }, path: [] }]);
        this.markup(nodeAt(node, 'catch'), failed);
        return;
      }
      case 'SnippetBlock': {
        const inner = this.child(scope, 'arrow');
        nodesAt(node, 'parameters').forEach((param, index) => {
          this.declare(inner, param, [
            { from: { kind: 'parameter', fn: node, index, rest: false }, path: [] },
          ]);
        });
        this.markup(nodeAt(node, 'body'), inner);
        return;
      }
      case 'IfBlock':
        this.visit(nodeAt(node, 'test'), scope);
        this.markup(nodeAt(node, 'consequent'), scope);
        this.markup(nodeAt(node, 'alternate'), scope);
        return;
      case 'KeyBlock':
        this.visit(nodeAt(node, 'expression'), scope);
        this.markup(nodeAt(node, 'fragment'), scope);
        return;
      default: {
        if (!ELEMENT_TYPES.has(node.type) && !COMPONENT_TYPES.has(node.type)) {
          for (const key of FRAGMENT_KEYS) this.markup(nodeAt(node, key), scope);
          return;
        }
        if (COMPONENT_TYPES.has(node.type)) this.module.components.push(node);
        if (node.type === 'SvelteBoundary') this.module.boundaries.push(node);
        // `let:` directives declare names for the element's content.
        const inner = this.child(scope, 'block');
        this.visit(nodeAt(node, 'tag'), scope);
        this.visit(nodeAt(node, 'expression'), scope);
        for (const attribute of nodesAt(node, 'attributes')) {
          this.record(attribute, scope);
          if (attribute.type === 'LetDirective') {
            const name = stringAt(attribute, 'name');
            if (name !== undefined) this.bind(inner, name, [{ from: UNKNOWN, path: [] }]);
            continue;
          }
          if (attribute.type === 'UseDirective') this.module.actions.push(attribute);
          this.visit(nodeAt(attribute, 'expression'), scope);
          const parts = attribute.value;
          for (const part of Array.isArray(parts) ? parts : [parts]) {
            if (!isNode(part)) continue;
            this.record(part, scope);
            this.visit(nodeAt(part, 'expression'), scope);
          }
        }
        this.markup(nodeAt(node, 'fragment'), inner);
      }
    }
  }

  /** Adds the values of later assignments to the names they assign. */
  finish() {
    for (const { target, alternatives } of this.assignments) {
      const scope = this.project.scopes.get(target);
      if (scope !== undefined) this.declare(scope, unwrap(target), alternatives, true);
    }
  }
}

/**
 * @param {Node} node
 * @returns {Alternative}
 */
function expressionOrigin(node) {
  return { from: { kind: 'expression', node }, path: [] };
}

const SCRIPT_OPEN = '<script lang="ts">';
const SCRIPT_CLOSE = '</script>';

/**
 * @typedef {(source: string, options: { modern: true, filename: string }) => unknown} SvelteParse
 * @typedef {{ parse: (html: string, options: { sourceCodeLocationInfo: boolean }) => unknown, parseFragment: (html: string) => unknown }} Parse5
 * @typedef {{ file: string, abs: string, kind: ModuleKind, text: string, locate: (offset: number) => { line: number, column: number } }} ModuleSpec
 */

/** All the code the lint reads: files, their scopes and the imports between them. */
class Project {
  /**
   * @param {string} root
   * @param {SvelteParse} parse
   * @param {Parse5} html
   */
  constructor(root, parse, html) {
    this.root = root;
    this.parse = parse;
    this.html = html;
    this.copyFile = path.join(root, 'src', 'copy.ts');
    /** @type {Module[]} */
    this.modules = [];
    /** @type {Module[]} Modules the lint reports on. */
    this.scanned = [];
    /** @type {Map<string, Module>} */
    this.byPath = new Map();
    /** @type {WeakMap<object, Scope>} */
    this.scopes = new WeakMap();
    /** @type {Map<string, Module | undefined>} */
    this.resolved = new Map();
    /** @type {Array<{ name: string, text: TextValue }> | undefined} */
    this.env = undefined;
    /**
     * copy.ts as it runs: its exports, and the strings of its `copy` tree,
     * which are the text that may show. Unset when copy.ts cannot be loaded;
     * then whatever it exports counts as copy.
     * @type {CopyRuntime | undefined}
     */
    this.copyRuntime = undefined;
    /** @type {Set<string>} Attributes whose value CSS shows with `content: attr(…)`. */
    this.cssAttributes = new Set();
  }

  /**
   * Loads copy.ts as it runs, so values taken from it can be told apart:
   * strings of the copy tree, and keys or codes that are not meant to show.
   * @param {string} [copyFile]
   */
  async loadCopy(copyFile = this.copyFile) {
    if (!existsSync(copyFile)) return;
    /** @type {unknown} */
    const loaded = await import(pathToFileURL(copyFile).href);
    if (!isFields(loaded)) return;
    const exports = /** @type {Record<string, unknown>} */ ({ ...loaded });
    this.copyRuntime = {
      exports,
      leaves: new Set(copyLeaves(exports.copy).map(([, text]) => text)),
    };
  }

  /** @param {string} root */
  static async create(root) {
    const { parse } = await import('svelte/compiler');
    return new Project(root, /** @type {SvelteParse} */ (parse), await loadParse5());
  }

  /** @param {string} abs */
  relative(abs) {
    return path.relative(this.root, abs).split(path.sep).join('/');
  }

  /**
   * Reads, parses and scopes a file, once.
   * @param {string} abs
   * @param {ModuleKind} kind
   * @returns {Module}
   */
  load(abs, kind) {
    const known = this.byPath.get(abs);
    if (known !== undefined) return known;
    const text = readFileSync(abs, 'utf8');
    const module = this.build({ file: this.relative(abs), abs, kind, text, locate: locator(text) });
    this.byPath.set(abs, module);
    return module;
  }

  /**
   * A file the lint reports on.
   * @param {string} abs
   * @param {ModuleKind} kind
   */
  scan(abs, kind) {
    const module = this.load(abs, kind);
    if (!this.scanned.includes(module)) this.scanned.push(module);
    return module;
  }

  /**
   * Code that is not a file of its own, such as an inline script, to report on.
   * @param {ModuleSpec} spec
   */
  scanEmbedded(spec) {
    const module = this.build(spec);
    this.scanned.push(module);
    return module;
  }

  /**
   * Parses a module and builds its scopes. Scripts are parsed as the instance
   * script of a Svelte component, so every file shares one parser and one tree.
   * @param {ModuleSpec} spec
   * @returns {Module}
   */
  build({ file, abs, kind, text, locate }) {
    const open =
      kind === 'script' ? SCRIPT_OPEN : kind === 'json' ? `${SCRIPT_OPEN}export default ` : '';
    // A module and its outer scope point at each other; `scope` is set right below.
    const module = /** @type {Module} */ (
      /** @type {unknown} */ ({
        file,
        abs,
        kind,
        source: text,
        at: (/** @type {number} */ offset) => locate(Math.max(0, offset - open.length)),
        root: undefined,
        programs: [],
        calls: [],
        writes: [],
        mutations: [],
        components: [],
        actions: [],
        boundaries: [],
        error: undefined,
      })
    );
    const builder = new ScopeBuilder(this, module);
    module.scope = builder.child(undefined, 'module');
    if (kind === 'text') return module;

    // `</script` inside a script would end it early; `</Script` has the same length.
    const parsed =
      kind === 'svelte' ? text : `${open}${text.replaceAll('</script', '</Script')}${SCRIPT_CLOSE}`;
    /** @type {unknown} */
    let root;
    try {
      root = this.parse(parsed, { modern: true, filename: file });
    } catch (error) {
      /** @type {unknown} */
      const position = isFields(error) && Array.isArray(error.position) ? error.position[0] : 0;
      module.error = {
        message: describeError(error).split('\n')[0] ?? 'parse error',
        offset: typeof position === 'number' ? position : 0,
      };
      return module;
    }
    if (!isNode(root)) {
      module.error = { message: 'the parser returned no tree', offset: 0 };
      return module;
    }
    this.modules.push(module);
    if (kind === 'svelte') {
      module.root = root;
      const moduleScript = nodeAt(nodeAt(root, 'module'), 'content');
      const instance = nodeAt(nodeAt(root, 'instance'), 'content');
      const instanceScope = builder.child(module.scope, 'module');
      if (moduleScript !== undefined) {
        module.programs.push(moduleScript);
        builder.visit(moduleScript, module.scope);
      }
      if (instance !== undefined) {
        module.programs.push(instance);
        builder.instance = true;
        builder.visit(instance, instanceScope);
        builder.instance = false;
      }
      // Snippets at the top of the markup are visible to the script too.
      builder.markup(nodeAt(root, 'fragment'), instanceScope, instanceScope);
    } else {
      const program = nodeAt(nodeAt(root, 'instance'), 'content');
      if (program !== undefined) {
        module.programs.push(program);
        builder.visit(program, module.scope);
      }
    }
    builder.finish();
    return module;
  }

  /**
   * The module an import names, or undefined for a package, copy.ts (whose
   * strings are the ones allowed) or anything that is not code or text.
   * @param {Module} from
   * @param {string} source
   * @returns {Module | undefined}
   */
  resolve(from, source) {
    const key = `${path.dirname(from.abs)}\u0000${source}`;
    if (!this.resolved.has(key)) this.resolved.set(key, this.find(from, source));
    return this.resolved.get(key);
  }

  /**
   * @param {Module} from
   * @param {string} source
   * @returns {Module | undefined}
   */
  find(from, source) {
    const { file, query } = this.locate(from, source);
    const inside = file !== undefined && !path.relative(this.root, file).startsWith('..');
    if (file === undefined || !inside || file === this.copyFile) return undefined;
    if (file.split(path.sep).includes('node_modules')) return undefined;
    if (query === 'raw') return this.load(file, 'text');
    if (query !== undefined) return undefined;
    if (file.endsWith('.svelte')) return this.load(file, 'svelte');
    if (file.endsWith('.json')) return this.load(file, 'json');
    if (/\.(?:[cm]?[jt]s)$/u.test(file)) return this.load(file, 'script');
    return undefined;
  }

  /**
   * The file a relative or root import names, and its query (`?raw`).
   * @param {Module} from
   * @param {string} source
   * @returns {{ file: string | undefined, query: string | undefined }}
   */
  locate(from, source) {
    if (!source.startsWith('.') && !source.startsWith('/')) {
      return { file: undefined, query: undefined };
    }
    const [bare = '', query] = source.split('?', 2);
    const base = source.startsWith('/')
      ? path.join(this.root, bare)
      : path.resolve(path.dirname(from.abs), bare);
    const candidates = [
      base,
      base.replace(/\.js$/u, '.ts'),
      base.replace(/\.mjs$/u, '.mts'),
      `${base}.ts`,
      `${base}.js`,
      `${base}.svelte.ts`,
      `${base}.svelte.js`,
      `${base}.json`,
      path.join(base, 'index.ts'),
      path.join(base, 'index.js'),
    ];
    const file = candidates.find(
      (candidate) => existsSync(candidate) && statSync(candidate).isFile(),
    );
    return { file, query };
  }

  /**
   * Whether an import names copy.ts itself.
   * @param {Module} from
   * @param {string} source
   */
  importsCopy(from, source) {
    const { file, query } = this.locate(from, source);
    return file === this.copyFile && query === undefined;
  }

  /**
   * Whether an import names a package (or a virtual module): code the lint does not read.
   * @param {string} source
   */
  static isPackage(source) {
    return !source.startsWith('.') && !source.startsWith('/');
  }

  /**
   * The variables of the .env files that Vite gives the page (VITE_ ones), as text.
   * @returns {Array<{ name: string, text: TextValue }>}
   */
  envVariables() {
    if (this.env !== undefined) return this.env;
    /** @type {Array<{ name: string, text: TextValue }>} */
    const variables = [];
    const files = existsSync(this.root)
      ? readdirSync(this.root)
          .filter((name) => /^\.env(?:\..+)?$/u.test(name))
          .sort()
      : [];
    for (const name of files) {
      const abs = path.join(this.root, name);
      if (!statSync(abs).isFile()) continue;
      const module = this.load(abs, 'text');
      let offset = 0;
      for (const line of module.source.split('\n')) {
        const match = /^(\s*(?:export\s+)?(VITE_\w*)\s*=\s*)(.*?)\s*$/u.exec(line);
        const value = match?.[3] ?? '';
        if (match?.[2] !== undefined) {
          const quoted = /^(["'`])(.*)\1$/u.exec(value);
          const text = quoted?.[2] ?? value.replace(/\s+#.*$/u, '');
          const start = offset + (match[1]?.length ?? 0) + (quoted === null ? 0 : 1);
          variables.push({ name: match[2], text: { t: 'text', text, module, offset: start } });
        }
        offset += line.length + 1;
      }
    }
    this.env = variables;
    return variables;
  }

  /**
   * What an identifier refers to, by the scope it appears in.
   * @param {Node} identifier
   */
  lookup(identifier) {
    const name = stringAt(identifier, 'name');
    return name === undefined ? undefined : this.lookupName(identifier, name);
  }

  /**
   * What a name refers to at a node.
   * @param {Node} node
   * @param {string} name
   */
  lookupName(node, name) {
    return findBinding(this.scopes.get(node), name);
  }

  /** @param {Node} node */
  moduleOf(node) {
    return this.scopes.get(node)?.module;
  }

  /**
   * The class `this` is an instance of at a node, if any.
   * @param {Node} node
   */
  thisClass(node) {
    for (let scope = this.scopes.get(node); scope !== undefined; scope = scope.parent) {
      if (scope.self !== undefined) return scope.self;
      if (scope.kind === 'function' || scope.kind === 'module') return undefined;
    }
    return undefined;
  }
}

/** @type {Parse5 | undefined} */
let parse5;

/** @returns {Promise<Parse5>} */
async function loadParse5() {
  parse5 ??= /** @type {Parse5} */ (/** @type {unknown} */ (await import('parse5')));
  return parse5;
}

// Values -------------------------------------------------------------------------------------------

/**
 * What the lint knows about a value: only what matters for text.
 *
 * @typedef {{ t: 'text', text: string, module: Module, offset: number, loose?: boolean }} TextValue
 *   A string literal and where it is written. A `loose` one was handed to code
 *   the lint cannot read (a package), and counts only where it reads as words.
 * @typedef {{ t: 'copy', value: unknown }} CopyValue A value of copy.ts as it runs; FORMATTED for what its formatters return.
 * @typedef {{ t: 'code', text: string, what: string, fix: string }} CodeValue
 *   A string that shows but is not copy: a key of copy.ts, a string of copy.ts
 *   outside its copy tree, or copy a method cut or changed. `what` says which
 *   (`%s` stands for the quoted text), and `fix` how to mend it.
 * @typedef {{ t: 'caught', module: Module, offset: number, made?: boolean }} CaughtValue
 *   An error, and where it is caught; or, `made`, where it is made (`new Error(…)`).
 * @typedef {{ t: 'foreign' }} ForeignValue A value from a package, whose code the lint does not read.
 * @typedef {TextValue | CodeValue | CaughtValue | CopyValue} StringValue What a place can show as text.
 * @typedef {{ exports: Record<string, unknown>, leaves: Set<string> }} CopyRuntime
 * @typedef {{ t: 'object', node: Node | undefined, entries: () => Entry[] }} ObjectValue
 * @typedef {{ key: string | undefined, name: StringValue | undefined, value: Thunk }} Entry An undefined key can be any key; `name` is the key as text.
 * @typedef {{ t: 'array', node: Node | undefined, exact: boolean, items: () => Thunk[] }} ArrayValue `exact` when positions line up with indexes.
 * @typedef {{ t: 'map', node: Node, pairs: Thunk }} MapValue
 * @typedef {{ t: 'store', node: Node, value: Thunk }} StoreValue
 * @typedef {{ t: 'function', node: Node, env: Env | undefined }} FunctionValue
 * @typedef {{ t: 'class', node: Node, env: Env | undefined }} ClassValue
 * @typedef {{ t: 'component', module: Module }} ComponentValue
 * @typedef {{ t: 'instance', name: string }} InstanceValue An object made by a constructor the lint does not read.
 * @typedef {TextValue | ObjectValue | ArrayValue | MapValue | StoreValue | FunctionValue | ClassValue | ComponentValue | InstanceValue | CopyValue | CodeValue | CaughtValue | ForeignValue} Value
 * @typedef {() => Value[]} Thunk
 * @typedef {{ fn: Node, args: Thunk[], more: Thunk | undefined, parent: Env | undefined }} Env A call in progress.
 * @typedef {{ args: Thunk[], more: Thunk | undefined }} Site The arguments of one call; `more` stands for any after a spread.
 * @typedef {'text' | 'html' | 'css' | 'map' | 'prose'} Reading How a place reads a string.
 * @typedef {{ module: Module, offset: number, where: string, verb: string }} Sink A place text shows.
 */

/** @type {Thunk} */
const NOTHING = () => [];
/**
 * Evaluation steps per place checked, and how deep reading may nest. Past
 * either the lint reports the place rather than guessing; 300 levels stay well
 * inside Node's default stack (a chain of 600 aliases fits in it).
 */
const STEP_LIMIT = 250_000;
const DEPTH_LIMIT = 300;
/** Rounds of the call index; each round sees the calls the one before found. */
const INDEX_ROUNDS = 8;

/** String methods whose result shows the string they are called on. */
const TEXT_METHODS = new Set([
  'concat',
  'toUpperCase',
  'toLowerCase',
  'toLocaleUpperCase',
  'toLocaleLowerCase',
  'trim',
  'trimStart',
  'trimEnd',
  'padStart',
  'padEnd',
  'repeat',
  'replace',
  'replaceAll',
  'slice',
  'substring',
  'substr',
  'at',
  'charAt',
  'normalize',
  'toString',
  'valueOf',
  'toLocaleString',
  'toWellFormed',
]);
/**
 * Among those, the ones that keep a string's words as they are. The others
 * cut a string or change its case, so copy put through them is no longer the
 * text copy.ts holds.
 */
const KEEPS_WORDS = new Set([
  'concat',
  'trim',
  'trimStart',
  'trimEnd',
  'padStart',
  'padEnd',
  'replace',
  'replaceAll',
  'normalize',
  'toString',
  'valueOf',
  'toLocaleString',
  'toWellFormed',
]);
/** Keys of an error, or of an error event, that hold its text. */
const ERROR_TEXT_KEYS = new Set([
  'message',
  'stack',
  'name',
  'reason',
  'error',
  'cause',
  'errors',
  'description',
  'detail',
  'statusText',
  'toString',
]);
/** Built-in errors: what `new Error(…)` holds is the code's own words. */
const ERROR_CLASSES = new Set([
  'Error',
  'TypeError',
  'RangeError',
  'SyntaxError',
  'ReferenceError',
  'EvalError',
  'URIError',
  'AggregateError',
  'DOMException',
]);
/** Events whose listeners are handed an error. */
const ERROR_EVENTS = new Set(['error', 'unhandledrejection', 'messageerror']);
/** Handler properties that are handed an error: `window.onerror = …`. */
const ERROR_HANDLERS = new Set(['onerror', 'onunhandledrejection', 'onmessageerror']);
/** Stands for copy.ts text the lint cannot see into: a formatter's output, or copy.ts not loaded. */
const COPY_OPAQUE = Symbol('copy.ts text');
/** @type {ForeignValue} */
const FOREIGN = { t: 'foreign' };
/** A Date shown as it is: "Fri Sep 25 2026 09:42:00 GMT-0400 (Eastern Daylight Time)". */
const DATE_TEXT = /** @type {CodeValue} */ ({
  t: 'code',
  text: '',
  what: 'a date written out by JavaScript, in English words,',
  fix: 'format it with a formatter of copy.ts',
});
/** Replacement patterns of String.prototype.replace, which insert what was matched. */
const REPLACEMENT_PATTERN = /\$(?:\$|&|`|'|\d{1,2}|<[^>]*>)/gu;
/** Svelte's reactive classes that work like built-in ones. */
const REACTIVE_BUILT_INS = new Map([
  ['SvelteMap', 'Map'],
  ['SvelteSet', 'Set'],
]);
/** Array methods that hand each item to a callback. */
const CALLBACK_METHODS = new Set([
  'forEach',
  'map',
  'flatMap',
  'filter',
  'find',
  'findLast',
  'findIndex',
  'findLastIndex',
  'some',
  'every',
  'reduce',
  'reduceRight',
]);
/** Array methods whose result holds the same items. */
const SAME_ITEMS = new Set([
  'slice',
  'filter',
  'toSorted',
  'toReversed',
  'reverse',
  'sort',
  'splice',
  'values',
  'fill',
  'copyWithin',
]);
/** Array methods whose result is one of the items. */
const ONE_ITEM = new Set(['at', 'find', 'findLast', 'pop', 'shift']);
/** MapLibre expression operators whose arguments name data, not text. */
const MAP_LOOKUPS = new Set([
  'get',
  'has',
  'in',
  'feature-state',
  'global-state',
  'var',
  'zoom',
  'id',
  'geometry-type',
  'properties',
  'line-progress',
  'heatmap-density',
  'accumulated',
  'image',
  'number-format',
  'collator',
  'resolved-locale',
  'is-supported-script',
  'typeof',
  'length',
  'index-of',
  'within',
  'distance',
  'config',
  'to-boolean',
  'to-number',
  'to-color',
]);

/**
 * Values without repeats: the same literal, or the same object read in the
 * same call, once. Without this, `b = a + a; c = b + b; …` doubles at each step.
 * @param {Value[]} values
 * @returns {Value[]}
 */
function distinct(values) {
  if (values.length < 2) return values;
  /** @type {Set<string>} */
  const texts = new Set();
  /** @type {Map<unknown, Set<Env | undefined>>} */
  const nodes = new Map();
  return values.filter((value) => {
    const key = plainKey(value);
    if (key !== undefined) {
      if (texts.has(key)) return false;
      texts.add(key);
      return true;
    }
    const node =
      value.t === 'component'
        ? value.module
        : value.t === 'copy'
          ? value.value
          : 'node' in value
            ? value.node
            : undefined;
    if (node === undefined) return true;
    const env = 'env' in value ? value.env : undefined;
    let envs = nodes.get(node);
    if (envs === undefined) {
      envs = new Set();
      nodes.set(node, envs);
    }
    if (envs.has(env)) return false;
    envs.add(env);
    return true;
  });
}

/**
 * @param {unknown} value A value of copy.ts as it runs.
 * @returns {CopyValue}
 */
function copyValue(value) {
  return { t: 'copy', value };
}

/**
 * @param {string} text
 * @param {string} what
 * @param {string} fix
 * @returns {CodeValue}
 */
function code(text, what, fix) {
  return { t: 'code', text, what, fix };
}

/**
 * Reads keys of a copy.ts value as it runs. Keys undefined: any key.
 * @param {CopyValue} value
 * @param {string[] | undefined} keys
 * @returns {Array<CopyValue | CodeValue>}
 */
function copyProperty(value, keys) {
  const inner = value.value;
  if (inner === COPY_OPAQUE) return [value];
  if (typeof inner === 'string') {
    // `copy.status.closed[0]` shows one letter of it.
    const cut = keys === undefined || keys.some((key) => /^\d+$/u.test(key));
    return cut
      ? [code(inner, 'copy.ts text %s cut by an index', 'put the text as it shows in copy.ts')]
      : [];
  }
  if (typeof inner !== 'object' || inner === null) return [];
  const record = /** @type {Record<string, unknown>} */ (inner);
  if (keys === undefined) return Object.values(record).map(copyValue);
  return keys.filter((key) => Object.hasOwn(record, key)).map((key) => copyValue(record[key]));
}

/**
 * The entries of a copy.ts object as it runs. Its keys name strings; they are
 * not copy themselves (`Object.keys(copy.status)` is "closed", not "Closed").
 * @param {CopyValue} value
 * @returns {Entry[]}
 */
function copyEntries(value) {
  const inner = value.value;
  if (inner === COPY_OPAQUE) {
    return [{ key: undefined, name: undefined, value: () => [value] }];
  }
  if (typeof inner !== 'object' || inner === null) return [];
  const record = /** @type {Record<string, unknown>} */ (inner);
  return Object.keys(record).map((key) => ({
    key,
    name: Array.isArray(inner)
      ? undefined
      : code(key, 'the copy.ts key %s', 'show the string it names, not its key'),
    value: () => [copyValue(record[key])],
  }));
}

/**
 * Whether a value is a list of items: an array, or an array of copy.ts.
 * @param {Value} value
 */
function isList(value) {
  return value.t === 'array' || (value.t === 'copy' && Array.isArray(value.value));
}

/**
 * A key that tells a value from the others when the value is plain data
 * rather than a node read in some call; undefined for the rest.
 * @param {Value} value
 * @returns {string | undefined}
 */
function plainKey(value) {
  switch (value.t) {
    case 'text':
      return `t\u0000${value.module.file}\u0000${String(value.offset)}\u0000${value.text}\u0000${value.loose === true ? 'loose' : ''}`;
    case 'code':
      return `c\u0000${value.what}\u0000${value.text}`;
    case 'caught':
      return `e\u0000${value.module.file}\u0000${String(value.offset)}\u0000${value.made === true ? 'made' : ''}`;
    case 'foreign':
      return 'f';
    case 'instance':
      return `i\u0000${value.name}`;
    case 'copy': {
      // Strings and numbers by value; objects, functions and COPY_OPAQUE by identity.
      const inner = value.value;
      if (typeof inner === 'string') return `k\u0000${inner}`;
      if (
        typeof inner === 'number' ||
        typeof inner === 'boolean' ||
        inner === null ||
        inner === undefined
      ) {
        return `n\u0000${String(inner)}`;
      }
      return undefined;
    }
    default:
      return undefined;
  }
}

/**
 * @template K, V
 * @param {Map<K, V[]>} map
 * @param {K} key
 * @param {V} value
 */
function pushTo(map, key, value) {
  const list = map.get(key);
  if (list === undefined) map.set(key, [value]);
  else list.push(value);
}

/**
 * Follows string literals from where they are written to where they show,
 * and reports each one that reaches the page.
 */
class Flow {
  /** @param {Project} project */
  constructor(project) {
    this.project = project;
    /** @type {Map<Node, Site[]>} Every call of each function, snippet and callback. */
    this.sites = new Map();
    /** @type {Map<Module, Array<() => Entry[]>>} The props each component is given. */
    this.uses = new Map();
    /** @type {Map<string | undefined, Thunk[]>} Values given to setContext, by key; undefined is any key. */
    this.contexts = new Map();
    /** @type {Map<Node, Map<Node, () => Entry[]>>} Properties set later: `labels.closed = …`. */
    this.addedEntries = new Map();
    /** @type {Map<Node, Map<Node, () => Thunk[]>>} Items added later: `list.push(…)`, `store.set(…)`. */
    this.addedItems = new Map();
    /**
     * Values written into a name by member path, whatever it holds: `rows.push(…)`
     * and `data.title = …` count even when `rows` and `data` come from a fetch.
     * @type {Map<Binding, Map<string, Map<Node, Thunk>>>}
     */
    this.addedAtPath = new Map();
    /** @type {WeakMap<Node, { binding: Binding, path: string } | null>} */
    this.paths = new WeakMap();
    /** @type {Map<Binding, Set<Env | undefined>>} */
    this.active = new Map();
    /** @type {Map<unknown, Set<Env | undefined>>} Objects and arrays being read. */
    this.reading = new Map();
    /** @type {Map<Binding, Value[]>} Names read outside any call, until the call index changes. */
    this.cache = new Map();
    /** How many times a cycle was cut short; a result read across a cut is not cached. */
    this.cuts = 0;
    /** @type {Set<string>} */
    this.activeExports = new Set();
    /** @type {WeakMap<Node, Node[]>} */
    this.returnCache = new WeakMap();
    /** @type {Map<Node, number>} Functions being called, and how many times over. */
    this.calling = new Map();
    this.depth = 0;
    this.steps = 0;
    this.exhausted = false;
    /** @type {Finding[]} */
    this.findings = [];
    /**
     * @type {Map<string, { finding: Finding, message: string, places: Set<string> }>}
     * One finding per literal, and the places it shows.
     */
    this.reported = new Map();
    /** @type {Set<string>} Places already reported as too deep to follow. */
    this.tooDeep = new Set();
  }

  // Expressions --------------------------------------------------------------------------------

  /**
   * The values an expression can have, as far as text goes.
   * @param {Node | undefined} node
   * @param {Env | undefined} env
   * @returns {Value[]}
   */
  evaluate(node, env) {
    if (node === undefined) return [];
    this.steps += 1;
    if (this.steps > STEP_LIMIT || this.depth > DEPTH_LIMIT) {
      this.exhausted = true;
      this.cuts += 1;
      return [];
    }
    this.depth += 1;
    try {
      return distinct(this.evaluateNode(node, env));
    } finally {
      this.depth -= 1;
    }
  }

  /**
   * @param {Node} node
   * @param {Env | undefined} env
   * @returns {Value[]}
   */
  evaluateNode(node, env) {
    switch (node.type) {
      case 'Literal':
        return typeof node.value === 'string' ? [this.text(node, node.value)] : [];
      case 'TemplateLiteral':
        return this.template(node, env, false);
      case 'TaggedTemplateExpression':
        return this.taggedTemplate(node, env);
      case 'ConditionalExpression':
        return [
          ...this.evaluate(nodeAt(node, 'consequent'), env),
          ...this.evaluate(nodeAt(node, 'alternate'), env),
        ];
      case 'LogicalExpression':
        return [
          ...this.evaluate(nodeAt(node, 'left'), env),
          ...this.evaluate(nodeAt(node, 'right'), env),
        ];
      case 'BinaryExpression':
        return node.operator === '+'
          ? [
              ...this.strings(this.evaluate(nodeAt(node, 'left'), env)),
              ...this.strings(this.evaluate(nodeAt(node, 'right'), env)),
            ]
          : [];
      case 'SequenceExpression':
        return this.evaluate(nodesAt(node, 'expressions').at(-1), env);
      case 'AssignmentExpression': {
        const right = this.evaluate(nodeAt(node, 'right'), env);
        if (node.operator === '=') return right;
        const left = this.evaluate(nodeAt(node, 'left'), env);
        return node.operator === '+='
          ? [...this.strings(left), ...this.strings(right)]
          : [...left, ...right];
      }
      case 'AwaitExpression':
        return this.evaluate(nodeAt(node, 'argument'), env);
      case 'ArrayExpression':
        return [this.arrayLiteral(node, env)];
      case 'ObjectExpression':
        return [this.objectLiteral(node, env)];
      case 'Identifier':
        return [...this.identifier(node, env), ...this.pathValues(node)];
      case 'ThisExpression': {
        const self = this.project.thisClass(node);
        return self === undefined ? [] : [this.instance(self, env)];
      }
      case 'MemberExpression':
        if (
          unwrap(nodeAt(node, 'object'))?.type === 'MetaProperty' &&
          this.memberName(node) === 'env'
        ) {
          return [this.envObject()];
        }
        return [
          ...this.property(this.evaluate(nodeAt(node, 'object'), env), this.memberKeys(node)),
          ...this.pathValues(node),
        ];
      case 'CallExpression':
        return this.call(node, env);
      case 'NewExpression':
        return this.construct(node, env);
      case 'FunctionExpression':
      case 'ArrowFunctionExpression':
        return [{ t: 'function', node, env }];
      case 'ClassExpression':
        return [{ t: 'class', node, env }];
      case 'TSEnumDeclaration':
        return [this.enumObject(node, env)];
      default:
        return WRAPPERS.has(node.type) ? this.evaluate(nodeAt(node, 'expression'), env) : [];
    }
  }

  /** Starts a fresh budget for one question: a place text shows, or one call of the index. */
  fresh() {
    this.steps = 0;
    this.exhausted = false;
  }

  /**
   * Reads the parts of an object or array unless the same one is already
   * being read in the same call: a value that holds itself is read once.
   * Counts toward the step and depth limits, since reads happen lazily.
   * @template T
   * @param {unknown} key
   * @param {Env | undefined} env
   * @param {() => T[]} produce
   * @returns {T[]}
   */
  once(key, env, produce) {
    let envs = this.reading.get(key);
    if (envs?.has(env) === true) {
      this.cuts += 1;
      return [];
    }
    this.steps += 1;
    if (this.steps > STEP_LIMIT || this.depth > DEPTH_LIMIT) {
      this.exhausted = true;
      this.cuts += 1;
      return [];
    }
    if (envs === undefined) {
      envs = new Set();
      this.reading.set(key, envs);
    }
    envs.add(env);
    this.depth += 1;
    try {
      return produce();
    } finally {
      envs.delete(env);
      this.depth -= 1;
    }
  }

  /**
   * A string literal's value and where it is written.
   * @param {Node} node
   * @param {string} value
   * @returns {TextValue}
   */
  text(node, value) {
    const module = this.project.moduleOf(node);
    if (module === undefined) throw new Error(`check-copy: lost the file of ${quote(value)}`);
    return { t: 'text', text: value, module, offset: numberAt(node, 'start') ?? 0 };
  }

  /**
   * @param {Node | undefined} node
   * @param {Env | undefined} env
   * @param {boolean} raw
   * @returns {Value[]}
   */
  template(node, env, raw) {
    /** @type {Value[]} */
    const texts = [];
    for (const quasi of nodesAt(node, 'quasis')) {
      const value = isFields(quasi.value) ? quasi.value : {};
      const text = raw
        ? stringAt(value, 'raw')
        : (stringAt(value, 'cooked') ?? stringAt(value, 'raw'));
      if (text !== undefined && text !== '') texts.push(this.text(quasi, text));
    }
    for (const expression of nodesAt(node, 'expressions')) {
      texts.push(...this.strings(this.evaluate(expression, env)));
    }
    return texts;
  }

  /**
   * A tagged template: `String.raw` writes its text as is; a tag of the
   * project is called with the template's strings and values; any other tag
   * (a package's) is handed text it will most likely show.
   * @param {Node} node
   * @param {Env | undefined} env
   * @returns {Value[]}
   */
  taggedTemplate(node, env) {
    const tag = unwrap(nodeAt(node, 'tag'));
    const quasi = nodeAt(node, 'quasi');
    if (
      tag?.type === 'MemberExpression' &&
      isGlobal(this.project, nodeAt(tag, 'object'), 'String') &&
      this.memberName(tag) === 'raw'
    ) {
      return this.template(quasi, env, true);
    }
    /** @type {Thunk[]} */
    const parts = nodesAt(quasi, 'quasis').map((part) => () => {
      const value = isFields(part.value) ? part.value : {};
      const text = stringAt(value, 'cooked') ?? stringAt(value, 'raw') ?? '';
      return text === '' ? [] : [this.text(part, text)];
    });
    /** @type {Site} */
    const site = {
      args: [
        () => [this.list(() => parts, true)],
        ...nodesAt(quasi, 'expressions').map((expression) => () => this.evaluate(expression, env)),
      ],
      more: undefined,
    };
    const tags = this.evaluate(tag, env);
    const read = this.functionsIn(tags).length > 0 || tags.some((value) => value.t === 'copy');
    return read ? this.invoke(tags, site) : [FOREIGN, ...this.loose(site)];
  }

  /**
   * What a place shows of each value: text (a literal, copy, a code, a
   * caught error), or an array's items. Objects and functions show nothing
   * the lint can judge.
   * @param {Value[]} values
   * @param {number} [depth]
   * @returns {StringValue[]}
   */
  strings(values, depth = 0) {
    /** @type {StringValue[]} */
    const texts = [];
    for (const value of values) {
      if (value.t === 'text' || value.t === 'code' || value.t === 'caught') texts.push(value);
      else if (value.t === 'copy') texts.push(...this.copyStrings(value, depth));
      else if (value.t === 'instance' && value.name === 'Date') texts.push(DATE_TEXT);
      else if (value.t === 'array' && depth < 6) {
        for (const item of value.items()) texts.push(...this.strings(item(), depth + 1));
      }
    }
    return depth === 0 ? /** @type {StringValue[]} */ (distinct(texts)) : texts;
  }

  /**
   * The string literals among what a value shows: for keys and names.
   * @param {Value[]} values
   * @returns {TextValue[]}
   */
  literals(values) {
    /** @type {TextValue[]} */
    const found = [];
    for (const value of this.strings(values)) if (value.t === 'text') found.push(value);
    return found;
  }

  /**
   * What a value of copy.ts shows: a string of its copy tree (or a
   * formatter's output) stands as it is; any other string of copy.ts is a
   * key or a code, not copy.
   * @param {CopyValue} value
   * @param {number} depth
   * @returns {StringValue[]}
   */
  copyStrings(value, depth) {
    const inner = value.value;
    const runtime = this.project.copyRuntime;
    if (inner === COPY_OPAQUE) return [value];
    if (typeof inner === 'string') {
      return runtime === undefined || runtime.leaves.has(inner)
        ? [value]
        : [code(inner, 'the copy.ts code %s', 'show a string of the copy tree, not a code')];
    }
    if (Array.isArray(inner) && depth < 6) {
      return inner.flatMap((item) => this.copyStrings(copyValue(item), depth + 1));
    }
    return [];
  }

  /**
   * Every value inside objects and arrays, at any depth.
   * @param {Value[]} values
   * @param {number} [depth]
   * @returns {Value[]}
   */
  nested(values, depth = 0) {
    /** @type {Value[]} */
    const found = [];
    for (const value of values) {
      found.push(value);
      if (depth >= 4) continue;
      if (value.t === 'object') {
        for (const entry of value.entries()) found.push(...this.nested(entry.value(), depth + 1));
      } else if (value.t === 'array') {
        for (const item of value.items()) found.push(...this.nested(item(), depth + 1));
      }
    }
    return found;
  }

  /**
   * The values held under text keys (label, title, text, …) inside objects and arrays.
   * @param {Value[]} values
   * @param {number} [depth]
   * @returns {Value[]}
   */
  textKeyed(values, depth = 0) {
    /** @type {Value[]} */
    const found = [];
    if (depth >= 4) return found;
    for (const value of values) {
      if (value.t === 'object') {
        for (const entry of value.entries()) {
          const inner = entry.value();
          if (entry.key !== undefined && TEXT_PROPS.has(entry.key)) found.push(...inner);
          found.push(...this.textKeyed(inner, depth + 1));
        }
      } else if (value.t === 'array') {
        for (const item of value.items()) found.push(...this.textKeyed(item(), depth + 1));
      }
    }
    return found;
  }

  /**
   * @param {Node} node
   * @param {Env | undefined} env
   * @returns {Value[]}
   */
  identifier(node, env) {
    const name = stringAt(node, 'name') ?? '';
    if (name === 'undefined') return [];
    const binding = this.project.lookup(node);
    if (binding !== undefined) return this.bindingValues(binding, env);
    // `$name` reads the Svelte store `name`.
    if (name.length > 1 && name.startsWith('$') && !RUNES.has(name)) {
      const store = this.project.lookupName(node, name.slice(1));
      if (store !== undefined) return this.storeValues(this.bindingValues(store, env));
    }
    return [];
  }

  /**
   * The keys a member expression can read; undefined when it can be any key.
   * @param {Node} member
   * @returns {string[] | undefined}
   */
  memberKeys(member) {
    const property = nodeAt(member, 'property');
    if (member.computed !== true) {
      const name = keyName(property);
      return name === undefined ? undefined : [name];
    }
    const key = unwrap(property);
    if (
      key?.type === 'Literal' &&
      (typeof key.value === 'string' || typeof key.value === 'number')
    ) {
      return [String(key.value)];
    }
    return undefined;
  }

  /**
   * A member expression's one static key.
   * @param {Node} member
   */
  memberName(member) {
    const keys = this.memberKeys(member);
    return keys?.length === 1 ? keys[0] : undefined;
  }

  /**
   * @param {Node} node
   * @param {Env | undefined} env
   * @returns {ArrayValue}
   */
  arrayLiteral(node, env) {
    const slots = slotsAt(node, 'elements');
    const exact = slots.every((slot) => slot !== undefined && slot.type !== 'SpreadElement');
    return {
      t: 'array',
      node,
      exact,
      items: () =>
        this.once(node, env, () => [
          ...slots.flatMap((slot) => {
            if (slot === undefined) return [];
            if (slot.type === 'SpreadElement') {
              return this.iterate(this.evaluate(nodeAt(slot, 'argument'), env));
            }
            return [() => this.evaluate(slot, env)];
          }),
          ...this.addedItemsOf(node),
        ]),
    };
  }

  /**
   * @param {Node} node
   * @param {Env | undefined} env
   * @returns {ObjectValue}
   */
  objectLiteral(node, env) {
    return {
      t: 'object',
      node,
      entries: () =>
        this.once(node, env, () => [
          ...nodesAt(node, 'properties').flatMap((property) => this.propertyEntries(property, env)),
          ...this.addedEntriesOf(node),
        ]),
    };
  }

  /**
   * @param {Node} property
   * @param {Env | undefined} env
   * @returns {Entry[]}
   */
  propertyEntries(property, env) {
    if (property.type === 'SpreadElement') {
      return this.entriesOf(this.evaluate(nodeAt(property, 'argument'), env));
    }
    if (property.type !== 'Property') return [];
    const keyNode = nodeAt(property, 'key');
    const computed = property.computed === true;
    const value = nodeAt(property, 'value');
    const kind = stringAt(property, 'kind');
    /** @type {Thunk} */
    const read =
      kind === 'get' && value !== undefined
        ? () => this.callFunction({ t: 'function', node: value, env }, [], undefined)
        : kind === 'set'
          ? NOTHING
          : () => this.evaluate(value, env);
    return this.keyedEntries(keyNode, computed, env, read);
  }

  /**
   * Entries for a key as written, and its name as text for Object.keys.
   * @param {Node | undefined} keyNode
   * @param {boolean} computed
   * @param {Env | undefined} env
   * @param {Thunk} read
   * @returns {Entry[]}
   */
  keyedEntries(keyNode, computed, env, read) {
    if (computed) {
      const key = unwrap(keyNode);
      const literal =
        key?.type === 'Literal' && (typeof key.value === 'string' || typeof key.value === 'number');
      const names = this.strings(this.evaluate(keyNode, env));
      return [
        {
          key: literal ? String(key.value) : undefined,
          name: names[0],
          value: read,
        },
      ];
    }
    const key = keyName(keyNode);
    const name =
      keyNode !== undefined && key !== undefined && keyNode.type !== 'PrivateIdentifier'
        ? typeof keyNode.value === 'number'
          ? undefined
          : this.text(keyNode, key)
        : undefined;
    return [{ key, name, value: read }];
  }

  /**
   * @param {Node | undefined} node
   * @returns {Entry[]}
   */
  addedEntriesOf(node) {
    const added = node === undefined ? undefined : this.addedEntries.get(node);
    return added === undefined ? [] : [...added.values()].flatMap((entries) => entries());
  }

  /**
   * @param {Node | undefined} node
   * @returns {Thunk[]}
   */
  addedItemsOf(node) {
    const added = node === undefined ? undefined : this.addedItems.get(node);
    return added === undefined ? [] : [...added.values()].flatMap((items) => items());
  }

  /**
   * Reads a property of each value. Keys undefined: any key.
   * @param {Value[]} values
   * @param {string[] | undefined} keys
   * @returns {Value[]}
   */
  property(values, keys) {
    /** @type {Value[]} */
    const found = [];
    for (const value of values) {
      if (value.t === 'object') {
        for (const entry of value.entries()) {
          if (keys === undefined || entry.key === undefined || keys.includes(entry.key)) {
            found.push(...entry.value());
          }
        }
      } else if (value.t === 'class') {
        for (const entry of this.classEntries(value.node, value.env, true)) {
          if (keys === undefined || entry.key === undefined || keys.includes(entry.key)) {
            found.push(...entry.value());
          }
        }
      } else if (value.t === 'array') {
        if (keys === undefined) {
          found.push(...this.itemsOf([value]));
          continue;
        }
        for (const key of keys) {
          if (/^(?:0|[1-9]\d*)$/u.test(key)) found.push(...this.element([value], Number(key)));
        }
      } else if (value.t === 'copy') {
        found.push(...copyProperty(value, keys));
      } else if (value.t === 'caught') {
        // `error.message`, `event.reason`: the error's own words.
        if (keys === undefined || keys.some((key) => ERROR_TEXT_KEYS.has(key))) found.push(value);
      } else if (value.t === 'foreign') {
        found.push(value);
      }
    }
    return found;
  }

  /**
   * The item at a position of each array, or every item when positions are not known.
   * @param {Value[]} values
   * @param {number} index
   * @returns {Value[]}
   */
  element(values, index) {
    /** @type {Value[]} */
    const found = [];
    for (const value of values) {
      if (value.t === 'copy') {
        found.push(...copyProperty(value, [String(index)]));
        continue;
      }
      if (value.t !== 'array') continue;
      const items = value.items();
      if (value.exact && this.addedItemsOf(value.node).length === 0) {
        found.push(...(items[index] ?? NOTHING)());
      } else {
        for (const item of items) found.push(...item());
      }
    }
    return found;
  }

  /**
   * What iterating each value yields, item by item.
   * @param {Value[]} values
   * @returns {Thunk[]}
   */
  iterate(values) {
    /** @type {Thunk[]} */
    const items = [];
    for (const value of values) {
      if (value.t === 'array') items.push(...value.items());
      else if (value.t === 'map') items.push(value.pairs);
      else if (value.t === 'text' || value.t === 'code' || value.t === 'caught') {
        items.push(() => [value]);
      } else if (value.t === 'copy') {
        const inner = value.value;
        if (Array.isArray(inner)) items.push(...inner.map((item) => () => [copyValue(item)]));
        else if (typeof inner === 'string' || inner === COPY_OPAQUE) items.push(() => [value]);
      }
    }
    return items;
  }

  /**
   * @param {Value[]} values
   * @returns {Value[]}
   */
  itemsOf(values) {
    return this.iterate(values).flatMap((item) => item());
  }

  /**
   * @param {Value[]} values
   * @returns {Entry[]}
   */
  entriesOf(values) {
    /** @type {Entry[]} */
    const entries = [];
    for (const value of values) {
      if (value.t === 'object') entries.push(...value.entries());
      else if (value.t === 'copy') entries.push(...copyEntries(value));
    }
    return entries;
  }

  /**
   * @param {Value[]} values
   * @returns {FunctionValue[]}
   */
  functionsIn(values) {
    /** @type {FunctionValue[]} */
    const found = [];
    for (const value of values) if (value.t === 'function') found.push(value);
    return found;
  }

  /**
   * @param {Value[]} values
   * @returns {Module[]}
   */
  componentsIn(values) {
    /** @type {Module[]} */
    const found = [];
    for (const value of values) if (value.t === 'component') found.push(value.module);
    return found;
  }

  /**
   * @param {Value[]} values
   * @returns {Value[]}
   */
  storeValues(values) {
    /** @type {Value[]} */
    const found = [];
    for (const value of values) if (value.t === 'store') found.push(...value.value());
    return found;
  }

  /**
   * An array of values not written as a literal.
   * @param {() => Thunk[]} items
   * @param {boolean} [exact]
   * @returns {ArrayValue}
   */
  list(items, exact = false) {
    return { t: 'array', node: undefined, exact, items };
  }

  // Names ----------------------------------------------------------------------------------------

  /**
   * Everything a name can hold.
   * @param {Binding} binding
   * @param {Env | undefined} env
   * @returns {Value[]}
   */
  bindingValues(binding, env) {
    const cached = env === undefined ? this.cache.get(binding) : undefined;
    if (cached !== undefined) return cached;
    let envs = this.active.get(binding);
    if (envs?.has(env) === true) {
      this.cuts += 1;
      return [];
    }
    if (envs === undefined) {
      envs = new Set();
      this.active.set(binding, envs);
    }
    const cuts = this.cuts;
    envs.add(env);
    try {
      const values = distinct(
        binding.origins.flatMap(({ from, path: steps }) =>
          this.follow(this.origin(from, binding, env), steps),
        ),
      );
      if (env === undefined && cuts === this.cuts && !this.exhausted) {
        this.cache.set(binding, values);
      }
      return values;
    } finally {
      envs.delete(env);
    }
  }

  /**
   * @param {Origin} from
   * @param {Binding} binding
   * @param {Env | undefined} env
   * @returns {Value[]}
   */
  origin(from, binding, env) {
    switch (from.kind) {
      case 'expression':
        return this.evaluate(from.node, env);
      case 'parameter':
        return this.parameter(from.fn, from.index, from.rest, env);
      case 'element':
        return this.itemsOf(this.evaluate(from.of, env));
      case 'key':
        return this.entriesOf(this.evaluate(from.of, env)).flatMap((entry) =>
          entry.name === undefined ? [] : [entry.name],
        );
      case 'callable':
        return [{ t: 'function', node: from.node, env }];
      case 'class':
        return [{ t: 'class', node: from.node, env }];
      case 'import':
        return this.imported(binding.scope.module, from.source, from.name);
      case 'prop':
        return this.property([this.propsObject(binding.scope.module)], [from.name]);
      case 'caught':
        return [this.caughtAt(from.node)];
      default:
        return [];
    }
  }

  /**
   * What an import (or a re-export) brings in: a value of copy.ts as it runs,
   * a value of a package, or what a module of the project exports.
   * @param {Module} module The importing module.
   * @param {string} source
   * @param {string} name 'default', '*' or an exported name.
   * @returns {Value[]}
   */
  imported(module, source, name) {
    if (this.project.importsCopy(module, source)) return [this.copyExport(name)];
    if (Project.isPackage(source)) return [FOREIGN];
    const target = this.project.resolve(module, source);
    return target === undefined ? [] : this.exported(target, name);
  }

  /**
   * An export of copy.ts, as it runs.
   * @param {string} name
   * @returns {CopyValue}
   */
  copyExport(name) {
    const exports = this.project.copyRuntime?.exports;
    if (exports === undefined) return copyValue(COPY_OPAQUE);
    if (name === '*') return copyValue(exports);
    return copyValue(Object.hasOwn(exports, name) ? exports[name] : COPY_OPAQUE);
  }

  /**
   * An error caught at a node: a catch clause, {:catch}, a `.catch()` call, a
   * boundary or an error listener.
   * @param {Node} node
   * @returns {CaughtValue}
   */
  caughtAt(node) {
    const module = this.project.moduleOf(node);
    if (module === undefined) throw new Error('check-copy: lost the file of a caught error');
    return { t: 'caught', module, offset: numberAt(node, 'start') ?? 0 };
  }

  /**
   * A parameter: the argument of the call in progress, or of every call the
   * project makes when no call is in progress.
   * @param {Node} fn
   * @param {number} index
   * @param {boolean} rest
   * @param {Env | undefined} env
   * @returns {Value[]}
   */
  parameter(fn, index, rest, env) {
    /** @param {Site} site */
    const pick = (site) =>
      rest
        ? [this.list(() => [...site.args.slice(index), ...(site.more ? [site.more] : [])])]
        : (site.args[index] ?? site.more ?? NOTHING)();
    for (let frame = env; frame !== undefined; frame = frame.parent) {
      if (frame.fn === fn) return pick(frame);
    }
    return (this.sites.get(fn) ?? []).flatMap(pick);
  }

  /**
   * Applies destructuring steps.
   * @param {Value[]} values
   * @param {Step[]} steps
   * @returns {Value[]}
   */
  follow(values, steps) {
    let current = values;
    for (const step of steps) {
      if ('key' in step) {
        current = this.property(current, step.key === undefined ? undefined : [step.key]);
      } else if ('index' in step) {
        current = this.element(current, step.index);
      }
    }
    return current;
  }

  // Calls ----------------------------------------------------------------------------------------

  /**
   * The arguments of a call, as thunks by position.
   * @param {Node} call
   * @param {Env | undefined} env
   * @returns {Site}
   */
  argumentsOf(call, env) {
    /** @type {Thunk[]} */
    const args = [];
    /** @type {Thunk[]} */
    const spread = [];
    for (const argument of nodesAt(call, 'arguments')) {
      if (argument.type === 'SpreadElement') {
        spread.push(() => this.itemsOf(this.evaluate(nodeAt(argument, 'argument'), env)));
      } else if (spread.length > 0) {
        spread.push(() => this.evaluate(argument, env));
      } else {
        args.push(() => this.evaluate(argument, env));
      }
    }
    return {
      args,
      more: spread.length === 0 ? undefined : () => spread.flatMap((thunk) => thunk()),
    };
  }

  /**
   * @param {Node} node
   * @param {Env | undefined} env
   * @returns {Value[]}
   */
  call(node, env) {
    const callee = unwrap(nodeAt(node, 'callee'));
    if (callee === undefined) return [];
    const site = this.argumentsOf(node, env);
    if (callee.type === 'Identifier') {
      const binding = this.project.lookup(callee);
      if (binding === undefined) {
        return this.globalCall(stringAt(callee, 'name') ?? '', node, env, site);
      }
      const imported = packageImport(binding);
      const handled = imported === undefined ? undefined : this.packageCall(imported, node, env);
      return handled ?? this.invoke(this.bindingValues(binding, env), site);
    }
    if (callee.type === 'MemberExpression') {
      const object = unwrap(nodeAt(callee, 'object'));
      const method = this.memberName(callee);
      if (
        object?.type === 'Identifier' &&
        this.project.lookup(object) === undefined &&
        !this.isStoreReference(object)
      ) {
        return this.globalMethod(stringAt(object, 'name') ?? '', method, node, env, site);
      }
      const receivers = this.evaluate(object, env);
      return [
        ...this.methodCall(receivers, method, node, site, env),
        ...this.invoke(this.property(receivers, this.memberKeys(callee)), site),
        ...this.borrowed(object, method, site),
      ];
    }
    return this.invoke(this.evaluate(callee, env), site);
  }

  /**
   * A built-in method borrowed with call or apply:
   * `String.prototype.concat.call(name, ' more')` adds what `name.concat(' more')` adds.
   * @param {Node | undefined} object What `call` or `apply` is called on.
   * @param {string | undefined} method
   * @param {Site} site
   * @returns {Value[]}
   */
  borrowed(object, method, site) {
    if (object?.type !== 'MemberExpression' || (method !== 'call' && method !== 'apply')) {
      return [];
    }
    const inner = this.memberName(object);
    if (inner === undefined) return [];
    const [self = NOTHING, listed = NOTHING] = site.args;
    /** @type {Site} */
    const lent =
      method === 'call'
        ? { args: site.args.slice(1), more: site.more }
        : { args: [], more: () => this.itemsOf(listed()) };
    return [...this.carried(inner, lent), ...(TEXT_METHODS.has(inner) ? this.strings(self()) : [])];
  }

  /**
   * Calls to names no scope declares. One the lint does not know (a global
   * of the page, such as a translation function) is handed text it may show.
   * @param {string} name
   * @param {Node} node
   * @param {Env | undefined} env
   * @param {Site} site
   * @returns {Value[]}
   */
  globalCall(name, node, env, site) {
    const [first] = nodesAt(node, 'arguments');
    switch (name) {
      case '$state':
      case '$derived':
      case '$bindable':
      case 'structuredClone':
        return this.evaluate(first, env);
      case '$props': {
        const module = this.project.moduleOf(node);
        return module === undefined ? [] : [this.propsObject(module)];
      }
      case 'String':
        return this.strings(this.evaluate(first, env));
      case 'Date':
        return [DATE_TEXT];
      case 'Error':
      case 'TypeError':
      case 'RangeError':
        return [{ ...this.caughtAt(node), made: true }];
      case 'Array':
        return [this.list(() => this.argumentsOf(node, env).args)];
      default:
        return [FOREIGN, ...this.loose(site)];
    }
  }

  /**
   * Methods of globals: runes, Object, Array, JSON, Promise. Any other is
   * code the lint does not read, handed text it may show.
   * @param {string} namespace
   * @param {string | undefined} method
   * @param {Node} node
   * @param {Env | undefined} env
   * @param {Site} site
   * @returns {Value[]}
   */
  globalMethod(namespace, method, node, env, site) {
    const args = nodesAt(node, 'arguments');
    const [first, second] = args;
    const values = () => this.evaluate(first, env);
    switch (`${namespace}.${method ?? ''}`) {
      case '$state.raw':
      case '$state.snapshot':
      case 'Object.freeze':
      case 'Object.seal':
      case 'Object.preventExtensions':
      case 'Promise.resolve':
      case 'Promise.all':
      case 'Promise.allSettled':
      case 'Promise.any':
      case 'Promise.race':
        return values();
      case '$derived.by':
        return this.invoke(values(), { args: [], more: undefined });
      case 'Object.assign':
        return args.flatMap((argument) => this.evaluate(argument, env));
      case 'Object.values':
        return [
          this.list(() => [
            ...this.entriesOf(values()).map((entry) => entry.value),
            ...this.iterate(values().filter((value) => value.t === 'array')),
          ]),
        ];
      case 'Object.keys':
      case 'Object.getOwnPropertyNames':
      case 'Reflect.ownKeys':
        return [
          this.list(() =>
            this.entriesOf(values()).flatMap((entry) => {
              const name = entry.name;
              return name === undefined ? [] : [() => [name]];
            }),
          ),
        ];
      case 'Object.entries':
        return [
          this.list(() =>
            this.entriesOf(values()).map((entry) => () => {
              const name = entry.name;
              return [
                this.list(() => [name === undefined ? NOTHING : () => [name], entry.value], true),
              ];
            }),
          ),
        ];
      case 'Object.fromEntries':
        return [
          {
            t: 'object',
            node: undefined,
            entries: () =>
              this.iterate(values()).map((pair) => ({
                key: undefined,
                name: undefined,
                value: () => this.element(pair(), 1),
              })),
          },
        ];
      case 'Array.from': {
        if (second === undefined) return [this.list(() => this.iterate(values()))];
        const callbacks = this.functionsIn(this.evaluate(second, env));
        /** @param {Thunk} item @returns {Thunk} */
        const mapped = (item) => () =>
          callbacks.flatMap((callback) => this.callFunction(callback, [item, NOTHING], undefined));
        // Whatever the items (none known, say), each callback's own text is in the result.
        return [this.list(() => [...this.iterate(values()).map(mapped), mapped(NOTHING)])];
      }
      case 'Array.of':
        return [this.list(() => this.argumentsOf(node, env).args, true)];
      case 'JSON.stringify': {
        const nested = this.nested(values());
        return this.strings([
          ...nested,
          ...this.entriesOf(nested).flatMap((entry) =>
            entry.name === undefined ? [] : [entry.name],
          ),
        ]);
      }
      default:
        return [
          FOREIGN,
          ...this.loose(site),
          ...(method === undefined ? [] : this.carried(method, site)),
        ];
    }
  }

  /**
   * Whether an identifier reads a Svelte store the code declares: `$labels`.
   * @param {Node} identifier
   */
  isStoreReference(identifier) {
    const name = stringAt(identifier, 'name') ?? '';
    return (
      name.length > 1 &&
      name.startsWith('$') &&
      !RUNES.has(name) &&
      this.project.lookupName(identifier, name.slice(1)) !== undefined
    );
  }

  /**
   * Calls of functions imported from a package that the lint knows: Svelte's
   * context, stores and `untrack`. Undefined for any other, which is read as
   * code the lint does not see into.
   * @param {{ source: string, name: string }} imported
   * @param {Node} node
   * @param {Env | undefined} env
   * @returns {Value[] | undefined}
   */
  packageCall(imported, node, env) {
    const [first, second] = nodesAt(node, 'arguments');
    if (imported.source === 'svelte' && ['untrack', 'flushSync'].includes(imported.name)) {
      return this.invoke(this.evaluate(first, env), { args: [], more: undefined });
    }
    if (imported.source === 'svelte' && imported.name === 'getContext') {
      const keys = this.literals(this.evaluate(first, env)).map((text) => text.text);
      /** @type {Value[]} */
      const found = [];
      for (const [key, values] of this.contexts) {
        if (key === undefined || keys.length === 0 || keys.includes(key)) {
          for (const value of values) found.push(...value());
        }
      }
      return found;
    }
    if (imported.source !== 'svelte/store') return undefined;
    switch (imported.name) {
      case 'writable':
      case 'readable':
        return [
          {
            t: 'store',
            node,
            value: () =>
              this.once(node, env, () => [
                ...this.evaluate(first, env),
                ...this.addedItemsOf(node).flatMap((item) => item()),
              ]),
          },
        ];
      case 'derived': {
        const inputs = () => {
          const given = this.evaluate(first, env);
          return [...this.storeValues(given), ...this.storeValues(this.itemsOf(given))];
        };
        const callbacks = this.functionsIn(this.evaluate(second, env));
        return [
          {
            t: 'store',
            node,
            value: () =>
              this.once(node, env, () =>
                callbacks.flatMap((callback) => this.callFunction(callback, [inputs], undefined)),
              ),
          },
        ];
      }
      case 'get':
        return this.storeValues(this.evaluate(first, env));
      case 'readonly':
        return this.evaluate(first, env);
      default:
        return undefined;
    }
  }

  /**
   * Built-in methods of strings, arrays, maps, functions and promises.
   *
   * What a method's arguments put into its result is followed whatever the
   * receiver is: a literal, copy, a prop, data the lint cannot see into.
   * `name.concat(' more')` shows " more" even when `name` comes from a fetch.
   * @param {Value[]} receivers
   * @param {string | undefined} method
   * @param {Node} node
   * @param {Site} site
   * @param {Env | undefined} env
   * @returns {Value[]}
   */
  methodCall(receivers, method, node, site, env) {
    if (method === undefined) return [];
    const args = nodesAt(node, 'arguments');
    const [onValue = NOTHING, onError = NOTHING] = site.args;
    /** @type {Thunk} */
    const caught = () => [this.caughtAt(node)];
    // A promise is read as the value it settles to: `then` hands it on, and
    // `catch` (or then's second callback) is handed an error.
    if (method === 'then') {
      return [
        ...this.invoke(onValue(), { args: [() => receivers], more: undefined }),
        ...this.invoke(onError(), { args: [caught], more: undefined }),
      ];
    }
    if (method === 'catch') {
      return [...receivers, ...this.invoke(onValue(), { args: [caught], more: undefined })];
    }
    if (method === 'finally') return receivers;
    /** @type {Value[]} */
    const found = this.carried(method, site);
    for (const receiver of receivers) {
      switch (receiver.t) {
        case 'text':
        case 'code':
        case 'caught':
          found.push(...this.textMethod(receiver, method));
          break;
        case 'copy':
          found.push(...this.copyMethod(receiver, method, args, env));
          break;
        case 'array':
          found.push(...this.arrayMethod(receiver, method, args, env));
          break;
        case 'map':
          found.push(...this.mapMethod(receiver, method));
          break;
        case 'function':
          if (method === 'call') {
            found.push(...this.callFunction(receiver, site.args.slice(1), site.more));
          } else if (method === 'apply') {
            const listed = args[1];
            found.push(
              ...this.callFunction(receiver, [], () => this.itemsOf(this.evaluate(listed, env))),
            );
          } else if (method === 'bind') {
            found.push(receiver);
          }
          break;
        default:
          break;
      }
    }
    return found;
  }

  /**
   * What a method's arguments put into its result, whatever it is called on:
   * the text a string method adds, the items an array method adds, and what
   * the callbacks of map and reduce return.
   * @param {string} method
   * @param {Site} site
   * @returns {Value[]}
   */
  carried(method, site) {
    /** @param {number} index @returns {Thunk} */
    const arg = (index) => site.args[index] ?? site.more ?? NOTHING;
    /** @param {number} index @returns {Thunk[]} */
    const from = (index) => [
      ...site.args.slice(index),
      ...(site.more === undefined ? [] : [site.more]),
    ];
    /** @returns {Value[]} What each callback returns, called with values the lint does not know. */
    const returned = () =>
      this.functionsIn(arg(0)()).flatMap((callback) =>
        this.callFunction(callback, [NOTHING, NOTHING, NOTHING, NOTHING], undefined),
      );
    switch (method) {
      case 'concat':
        // A string adds each argument's text; an array adds each one's items.
        return [
          ...this.strings(from(0).flatMap((thunk) => thunk())),
          this.list(() => this.flatten(from(0))),
        ];
      case 'padStart':
      case 'padEnd':
        // Padding with digits (`padStart(2, '0')`) writes a number, not words.
        return this.strings(arg(1)()).filter(
          (value) => value.t !== 'text' || !/^[\d\s]*$/u.test(value.text),
        );
      case 'replace':
      case 'replaceAll': {
        const replacement = arg(1)();
        return [
          // `$1` and `$&` put back what was matched, which is not written here.
          ...this.strings(replacement).map((value) =>
            value.t === 'text'
              ? {
                  ...value,
                  text: value.text.replace(REPLACEMENT_PATTERN, (found) =>
                    found === '$$' ? '$' : ' ',
                  ),
                }
              : value,
          ),
          ...this.strings(this.invoke(replacement, { args: [], more: NOTHING })),
        ];
      }
      case 'join':
        return this.strings(arg(0)());
      case 'with':
        return [this.list(() => [arg(1)])];
      case 'toSpliced':
        return [this.list(() => from(2))];
      case 'fill':
        return [this.list(() => [arg(0)])];
      case 'map':
        return [this.list(() => [returned])];
      case 'flatMap':
        return [this.list(() => this.flatten([returned]))];
      case 'reduce':
      case 'reduceRight':
        return [...arg(1)(), ...returned()];
      default:
        return [];
    }
  }

  /**
   * A string method on text: the text it shows is the receiver's (split, a
   * list of its parts). What the arguments add is in `carried`.
   * @param {TextValue | CodeValue | CaughtValue} receiver
   * @param {string} method
   * @returns {Value[]}
   */
  textMethod(receiver, method) {
    if (method === 'split') return [this.list(() => [() => [receiver]])];
    return TEXT_METHODS.has(method) ? [receiver] : [];
  }

  /**
   * A method on a value of copy.ts. Its arrays are read like arrays, its
   * formatters return copy, and its strings stay copy through methods that keep
   * their words; a method that cuts them or changes their case shows text that
   * copy.ts does not hold.
   * @param {CopyValue} receiver
   * @param {string} method
   * @param {Node[]} args
   * @param {Env | undefined} env
   * @returns {Value[]}
   */
  copyMethod(receiver, method, args, env) {
    const inner = receiver.value;
    if (Array.isArray(inner)) {
      const items = inner.map((item) => () => [copyValue(item)]);
      return this.arrayMethod(
        this.list(() => items, true),
        method,
        args,
        env,
      );
    }
    if (typeof inner === 'function' && ['call', 'apply'].includes(method)) {
      return [copyValue(COPY_OPAQUE)];
    }
    if (typeof inner === 'function' && method === 'bind') return [receiver];
    if (typeof inner !== 'string' && inner !== COPY_OPAQUE) return [];
    if (method !== 'split' && !TEXT_METHODS.has(method)) return [];
    if (KEEPS_WORDS.has(method)) return [receiver];
    const changed = code(
      typeof inner === 'string' ? inner : '',
      typeof inner === 'string'
        ? `copy.ts text %s put through ${method}()`
        : `copy.ts text put through ${method}()`,
      'put the text as it shows in copy.ts',
    );
    return method === 'split' ? [this.list(() => [() => [changed]])] : [changed];
  }

  /**
   * @param {ArrayValue} receiver
   * @param {string} method
   * @param {Node[]} args
   * @param {Env | undefined} env
   * @returns {Value[]}
   */
  arrayMethod(receiver, method, args, env) {
    const [first, second] = args;
    const items = () => receiver.items();
    const callbacks = () => this.functionsIn(this.evaluate(first, env));
    if (SAME_ITEMS.has(method)) return [this.list(items)];
    if (ONE_ITEM.has(method)) return this.itemsOf([receiver]);
    switch (method) {
      case 'join':
      case 'toString':
      case 'toLocaleString':
        return this.strings(this.itemsOf([receiver]));
      // What the arguments add to these is in `carried`.
      case 'with':
      case 'toSpliced':
      case 'concat':
        return [this.list(items)];
      case 'flat':
        return [this.list(() => this.flatten(items()))];
      case 'map':
      case 'flatMap': {
        const mapped = this.list(
          () =>
            items().map(
              (item) => () =>
                callbacks().flatMap((callback) =>
                  this.callFunction(callback, [item, NOTHING, () => [receiver]], undefined),
                ),
            ),
          method === 'map' && receiver.exact,
        );
        return method === 'map' ? [mapped] : [this.list(() => this.flatten(mapped.items()))];
      }
      case 'reduce':
      case 'reduceRight': {
        /** @type {Thunk} */
        const initial = second === undefined ? NOTHING : () => this.evaluate(second, env);
        /** @type {Thunk} */
        const each = () => this.itemsOf([receiver]);
        return [
          ...initial(),
          ...callbacks().flatMap((callback) =>
            this.callFunction(callback, [initial, each], undefined),
          ),
        ];
      }
      case 'entries':
        return [
          this.list(() => items().map((item) => () => [this.list(() => [NOTHING, item], true)])),
        ];
      default:
        return [];
    }
  }

  /**
   * One level of nested arrays laid flat.
   * @param {Thunk[]} items
   * @returns {Thunk[]}
   */
  flatten(items) {
    return items.flatMap((item) => {
      const values = item();
      return [
        ...this.iterate(values.filter(isList)),
        () => values.filter((value) => !isList(value)),
      ];
    });
  }

  /**
   * @param {MapValue} receiver
   * @param {string} method
   * @returns {Value[]}
   */
  mapMethod(receiver, method) {
    switch (method) {
      case 'get':
        return this.element(receiver.pairs(), 1);
      case 'values':
        return [this.list(() => [() => this.element(receiver.pairs(), 1)])];
      case 'keys':
        return [this.list(() => [() => this.element(receiver.pairs(), 0)])];
      case 'entries':
        return [this.list(() => [receiver.pairs])];
      default:
        return [];
    }
  }

  /**
   * `new X(…)`.
   * @param {Node} node
   * @param {Env | undefined} env
   * @returns {Value[]}
   */
  construct(node, env) {
    const callee = unwrap(nodeAt(node, 'callee'));
    if (callee === undefined) return [];
    const [first] = nodesAt(node, 'arguments');
    const binding = callee.type === 'Identifier' ? this.project.lookup(callee) : undefined;
    const imported = binding === undefined ? undefined : packageImport(binding);
    const name =
      callee.type === 'Identifier'
        ? (stringAt(callee, 'name') ?? '')
        : callee.type === 'MemberExpression'
          ? (this.memberName(callee) ?? '')
          : '';
    // A global, or Svelte's reactive Map and Set, which work like the built-in ones.
    const builtIn =
      callee.type === 'Identifier' && binding === undefined
        ? name
        : imported?.source === 'svelte/reactivity'
          ? REACTIVE_BUILT_INS.get(imported.name)
          : undefined;
    switch (builtIn) {
      case undefined:
        break;
      case 'String':
        return this.strings(this.evaluate(first, env));
      case 'Map':
        return [
          {
            t: 'map',
            node,
            pairs: () =>
              this.once(node, env, () => [
                ...this.itemsOf(this.evaluate(first, env)),
                ...this.addedItemsOf(node).flatMap((item) => item()),
              ]),
          },
        ];
      case 'Set':
        return [
          {
            t: 'array',
            node,
            exact: false,
            items: () =>
              this.once(node, env, () => [
                ...this.iterate(this.evaluate(first, env)),
                ...this.addedItemsOf(node),
              ]),
          },
        ];
      default:
        return ERROR_CLASSES.has(builtIn)
          ? [{ ...this.caughtAt(node), made: true }]
          : [{ t: 'instance', name: builtIn }];
    }
    /** @type {Value[]} */
    const made = [];
    for (const value of this.evaluate(callee, env)) {
      if (value.t === 'class') {
        made.push(this.instance(value.node, value.env));
        // An error of the project's own kind says what its code wrote.
        if (this.extendsError(value, 0)) made.push({ ...this.caughtAt(node), made: true });
      }
      // A class from a package is handed text it may show.
      else if (value.t === 'foreign')
        made.push(FOREIGN, ...this.loose(this.argumentsOf(node, env)));
    }
    return made.length > 0 ? made : [{ t: 'instance', name }];
  }

  /**
   * Whether a class extends Error, directly or through classes of the project.
   * @param {ClassValue} value
   * @param {number} depth
   * @returns {boolean}
   */
  extendsError(value, depth) {
    const parent = unwrap(nodeAt(value.node, 'superClass'));
    if (parent === undefined || depth > 8) return false;
    if (isGlobal(this.project, parent, ERROR_CLASSES)) return true;
    return this.evaluate(parent, value.env).some(
      (found) => found.t === 'class' && this.extendsError(found, depth + 1),
    );
  }

  /**
   * An instance of a class the lint reads: its fields, getters and methods,
   * and whatever is later set on it (`this.label = …`).
   * @param {Node} classNode
   * @param {Env | undefined} env
   * @returns {ObjectValue}
   */
  instance(classNode, env) {
    return {
      t: 'object',
      node: classNode,
      entries: () =>
        this.once(classNode, env, () => [
          ...this.classEntries(classNode, env, false),
          ...this.addedEntriesOf(classNode),
        ]),
    };
  }

  /**
   * @param {Node} classNode
   * @param {Env | undefined} env
   * @param {boolean} statics
   * @returns {Entry[]}
   */
  classEntries(classNode, env, statics) {
    /** @type {Entry[]} */
    const entries = [];
    for (const member of nodesAt(nodeAt(classNode, 'body'), 'body')) {
      if ((member.static === true) !== statics) continue;
      const value = nodeAt(member, 'value');
      const kind = stringAt(member, 'kind');
      /** @type {Thunk} */
      let read;
      if (member.type === 'PropertyDefinition') {
        read = () => this.evaluate(value, env);
      } else if (member.type === 'MethodDefinition' && value !== undefined && kind === 'get') {
        read = () => this.callFunction({ t: 'function', node: value, env }, [], undefined);
      } else if (member.type === 'MethodDefinition' && value !== undefined && kind === 'method') {
        read = () => [{ t: 'function', node: value, env }];
      } else if (member.type === 'MethodDefinition' && value !== undefined && !statics) {
        // `constructor(private label: string)` makes a field of each parameter property.
        for (const param of nodesAt(value, 'params')) {
          if (param.type !== 'TSParameterProperty') continue;
          for (const name of patternNames(nodeAt(param, 'parameter'))) {
            const binding = this.project.lookupName(param, name);
            if (binding === undefined) continue;
            entries.push({
              key: name,
              name: undefined,
              value: () => this.bindingValues(binding, env),
            });
          }
        }
        continue;
      } else {
        continue;
      }
      entries.push(
        ...this.keyedEntries(nodeAt(member, 'key'), member.computed === true, env, read),
      );
    }
    // What a class inherits comes after its own members.
    for (const parent of this.evaluate(nodeAt(classNode, 'superClass'), env)) {
      if (parent.t === 'class')
        entries.push(...this.classEntries(parent.node, parent.env, statics));
    }
    return entries;
  }

  /**
   * @param {Node} node
   * @param {Env | undefined} env
   * @returns {ObjectValue}
   */
  enumObject(node, env) {
    const members = [...nodesAt(node, 'members'), ...nodesAt(nodeAt(node, 'body'), 'members')];
    return {
      t: 'object',
      node,
      entries: () =>
        this.once(node, env, () => members).map((member) => ({
          key: keyName(nodeAt(member, 'id')),
          name: undefined,
          value: () => this.evaluate(nodeAt(member, 'initializer'), env),
        })),
    };
  }

  /**
   * Calls each function among the values.
   * @param {Value[]} values
   * @param {Site} site
   * @returns {Value[]}
   */
  invoke(values, site) {
    /** @type {Value[]} */
    const found = [];
    let foreign = false;
    for (const value of values) {
      if (value.t === 'function') found.push(...this.callFunction(value, site.args, site.more));
      // A formatter of copy.ts returns copy.
      else if (
        value.t === 'copy' &&
        (typeof value.value === 'function' || value.value === COPY_OPAQUE)
      ) {
        found.push(copyValue(COPY_OPAQUE));
      } else if (value.t === 'foreign') foreign = true;
    }
    if (foreign) found.push(FOREIGN, ...this.loose(site));
    return found;
  }

  /**
   * Literal text handed to code the lint does not read (a package, a global
   * of the page): it may well show, so it counts where it reads as words.
   * Functions handed along count by what they return.
   * @param {Site} site
   * @returns {Value[]}
   */
  loose(site) {
    const all = [...site.args, ...(site.more === undefined ? [] : [site.more])];
    return all.flatMap((thunk) => {
      const values = thunk();
      return [
        ...this.strings(this.nested(values)),
        ...this.strings(this.invoke(values, { args: [], more: NOTHING })),
      ].flatMap(
        /** @returns {Value[]} */
        (value) => {
          if (value.t === 'text') return [{ ...value, loose: true }];
          // A key handed to a package is most likely looked up, not shown.
          return value.t === 'caught' ? [value] : [];
        },
      );
    });
  }

  /**
   * What a function returns when called with these arguments.
   * @param {FunctionValue} fn
   * @param {Thunk[]} args
   * @param {Thunk | undefined} more
   * @returns {Value[]}
   */
  callFunction(fn, args, more) {
    const node = fn.node;
    const body = nodeAt(node, 'body');
    if (!FUNCTION_TYPES.has(node.type) || node.generator === true || body === undefined) return [];
    // Recursion, direct or through other functions and files: two levels
    // show every path a literal can take.
    const calls = this.calling.get(node) ?? 0;
    if (calls >= 2) {
      this.cuts += 1;
      return [];
    }
    /** @type {Env} */
    const frame = { fn: node, args, more, parent: fn.env };
    this.calling.set(node, calls + 1);
    try {
      if (body.type !== 'BlockStatement') return this.evaluate(body, frame);
      return this.returns(node).flatMap((argument) => this.evaluate(argument, frame));
    } finally {
      this.calling.set(node, calls);
    }
  }

  /**
   * The expressions a function returns, not counting nested functions.
   * @param {Node} fn
   * @returns {Node[]}
   */
  returns(fn) {
    let found = this.returnCache.get(fn);
    if (found === undefined) {
      /** @type {Node[]} */
      const collected = [];
      /** @param {unknown} value */
      const visit = (value) => {
        if (Array.isArray(value)) {
          for (const item of value) visit(item);
          return;
        }
        if (!isNode(value) || FUNCTION_TYPES.has(value.type) || CLASS_TYPES.has(value.type)) {
          return;
        }
        if (value.type === 'ReturnStatement') {
          const argument = nodeAt(value, 'argument');
          if (argument !== undefined) collected.push(argument);
          return;
        }
        for (const [key, child] of Object.entries(value)) if (!SKIP_KEYS.has(key)) visit(child);
      };
      visit(nodeAt(fn, 'body'));
      found = collected;
      this.returnCache.set(fn, found);
    }
    return found;
  }

  // Modules ---------------------------------------------------------------------------------------

  /**
   * What a module exports under a name ('default', or '*' for all of it).
   * @param {Module} module
   * @param {string} name
   * @returns {Value[]}
   */
  exported(module, name) {
    const key = `${module.abs}\u0000${module.file}\u0000${name}`;
    if (this.activeExports.has(key)) {
      this.cuts += 1;
      return [];
    }
    this.activeExports.add(key);
    try {
      return this.exportedValues(module, name);
    } finally {
      this.activeExports.delete(key);
    }
  }

  /**
   * @param {Module} module
   * @param {string} name
   * @returns {Value[]}
   */
  exportedValues(module, name) {
    if (module.kind === 'text') {
      return name === 'default' ? [{ t: 'text', text: module.source, module, offset: 0 }] : [];
    }
    if (name === '*') return [this.namespace(module)];
    if (module.kind === 'svelte' && name === 'default') return [{ t: 'component', module }];
    if (module.kind === 'json' && name !== 'default') {
      return this.property(this.exported(module, 'default'), [name]);
    }
    for (const program of module.programs) {
      for (const statement of nodesAt(program, 'body')) {
        const found = this.exportStatement(module, statement, name);
        if (found !== undefined) return found;
      }
    }
    return [];
  }

  /**
   * What one export statement exports under a name; undefined when it exports no such name.
   * @param {Module} module
   * @param {Node} statement
   * @param {string} name
   * @returns {Value[] | undefined}
   */
  exportStatement(module, statement, name) {
    const source = stringAt(nodeAt(statement, 'source'), 'value');
    switch (statement.type) {
      case 'ExportNamedDeclaration': {
        const declaration = nodeAt(statement, 'declaration');
        if (declaration !== undefined) {
          if (!declaredNames(declaration).includes(name)) return undefined;
          const binding = this.project.lookupName(declaration, name);
          return binding === undefined ? [] : this.bindingValues(binding, undefined);
        }
        for (const specifier of nodesAt(statement, 'specifiers')) {
          if (keyName(nodeAt(specifier, 'exported')) !== name) continue;
          const local = keyName(nodeAt(specifier, 'local')) ?? name;
          if (source !== undefined) return this.imported(module, source, local);
          const binding = this.project.lookupName(statement, local);
          return binding === undefined ? [] : this.bindingValues(binding, undefined);
        }
        return undefined;
      }
      case 'ExportDefaultDeclaration': {
        if (name !== 'default') return undefined;
        const declaration = nodeAt(statement, 'declaration');
        if (declaration?.type === 'FunctionDeclaration') {
          return [{ t: 'function', node: declaration, env: undefined }];
        }
        if (declaration?.type === 'ClassDeclaration') {
          return [{ t: 'class', node: declaration, env: undefined }];
        }
        return this.evaluate(declaration, undefined);
      }
      case 'ExportAllDeclaration': {
        if (source === undefined) return undefined;
        const alias = nodeAt(statement, 'exported');
        if (alias !== undefined) {
          if (keyName(alias) !== name) return undefined;
          return this.imported(module, source, '*');
        }
        if (name === 'default') return undefined;
        if (this.project.importsCopy(module, source)) {
          return Object.hasOwn(this.project.copyRuntime?.exports ?? {}, name)
            ? [this.copyExport(name)]
            : undefined;
        }
        if (Project.isPackage(source)) return undefined;
        const target = this.project.resolve(module, source);
        if (target === undefined) return undefined;
        const found = this.exported(target, name);
        return found.length > 0 ? found : undefined;
      }
      default:
        return undefined;
    }
  }

  /**
   * The names a module exports.
   * @param {Module} module
   * @param {Set<Module>} [seen]
   * @returns {string[]}
   */
  exportNames(module, seen = new Set()) {
    if (seen.has(module)) return [];
    seen.add(module);
    if (module.kind === 'text' || module.kind === 'json') return ['default'];
    /** @type {string[]} */
    const names = [];
    for (const program of module.programs) {
      for (const statement of nodesAt(program, 'body')) {
        if (statement.type === 'ExportDefaultDeclaration') names.push('default');
        if (statement.type === 'ExportNamedDeclaration') {
          names.push(...declaredNames(nodeAt(statement, 'declaration')));
          for (const specifier of nodesAt(statement, 'specifiers')) {
            const exported = keyName(nodeAt(specifier, 'exported'));
            if (exported !== undefined) names.push(exported);
          }
        }
        if (statement.type === 'ExportAllDeclaration') {
          const alias = keyName(nodeAt(statement, 'exported'));
          const source = stringAt(nodeAt(statement, 'source'), 'value');
          const target = source === undefined ? undefined : this.project.resolve(module, source);
          if (alias !== undefined) names.push(alias);
          else if (target !== undefined) names.push(...this.exportNames(target, seen));
          else if (source !== undefined && this.project.importsCopy(module, source)) {
            names.push(...Object.keys(this.project.copyRuntime?.exports ?? {}));
          }
        }
      }
    }
    return names;
  }

  /**
   * `import * as labels from './labels'`.
   * @param {Module} module
   * @returns {ObjectValue}
   */
  namespace(module) {
    return {
      t: 'object',
      node: undefined,
      entries: () =>
        this.once(`exports ${module.abs} ${module.file}`, undefined, () =>
          this.exportNames(module).map((name) => ({
            key: name,
            name: undefined,
            value: () => this.exported(module, name),
          })),
        ),
    };
  }

  /**
   * `import.meta.env`: the VITE_ variables of the project's .env files.
   * @returns {ObjectValue}
   */
  envObject() {
    return {
      t: 'object',
      node: undefined,
      entries: () =>
        this.project.envVariables().map(({ name, text }) => ({
          key: name,
          name: undefined,
          value: () => [text],
        })),
    };
  }

  /**
   * A component's props: whatever every tag and mount() call that uses it passes.
   * @param {Module} module
   * @returns {ObjectValue}
   */
  propsObject(module) {
    return {
      t: 'object',
      node: undefined,
      entries: () =>
        this.once(`props ${module.abs} ${module.file}`, undefined, () =>
          (this.uses.get(module) ?? []).flatMap((use) => use()),
        ),
    };
  }

  /**
   * The components a component tag stands for.
   * @param {Node} tag
   * @returns {Module[]}
   */
  componentTargets(tag) {
    switch (tag.type) {
      case 'Component': {
        const [first = '', ...rest] = (stringAt(tag, 'name') ?? '').split('.');
        const binding = this.project.lookupName(tag, first);
        let values = binding === undefined ? [] : this.bindingValues(binding, undefined);
        for (const part of rest) values = this.property(values, [part]);
        return this.componentsIn(values);
      }
      case 'SvelteComponent':
        return this.componentsIn(this.evaluate(nodeAt(tag, 'expression'), undefined));
      case 'SvelteSelf': {
        const module = this.project.moduleOf(tag);
        return module === undefined ? [] : [module];
      }
      default:
        return [];
    }
  }

  /**
   * The props a component tag passes: attributes, spreads, bindings and snippets.
   * @param {Node} tag
   * @returns {Entry[]}
   */
  tagProps(tag) {
    /** @type {Entry[]} */
    const entries = [];
    for (const attribute of nodesAt(tag, 'attributes')) {
      const key = stringAt(attribute, 'name');
      if (attribute.type === 'Attribute') {
        entries.push({ key, name: undefined, value: () => this.attributeValues(attribute) });
      } else if (attribute.type === 'BindDirective') {
        const expression = nodeAt(attribute, 'expression');
        entries.push({ key, name: undefined, value: () => this.evaluate(expression, undefined) });
      } else if (attribute.type === 'SpreadAttribute') {
        entries.push(...this.entriesOf(this.evaluate(nodeAt(attribute, 'expression'), undefined)));
      }
    }
    for (const child of nodesAt(nodeAt(tag, 'fragment'), 'nodes')) {
      if (child.type !== 'SnippetBlock') continue;
      entries.push({
        key: stringAt(nodeAt(child, 'expression'), 'name'),
        name: undefined,
        value: () => [{ t: 'function', node: child, env: undefined }],
      });
    }
    return entries;
  }

  /**
   * What an attribute's value is: text, an expression, or both joined.
   * @param {Node} attribute
   * @returns {Value[]}
   */
  attributeValues(attribute) {
    const value = attribute.value;
    if (isNode(value)) return this.evaluate(nodeAt(value, 'expression'), undefined);
    if (!Array.isArray(value)) return [];
    const parts = value.filter(isNode);
    if (parts.length === 1 && parts[0]?.type === 'ExpressionTag') {
      return this.evaluate(nodeAt(parts[0], 'expression'), undefined);
    }
    /** @type {Value[]} */
    const texts = [];
    for (const part of parts) {
      const data = stringAt(part, 'data');
      if (part.type === 'Text' && data !== undefined && data !== '') {
        texts.push(this.text(part, data));
      } else if (part.type === 'ExpressionTag') {
        texts.push(...this.strings(this.evaluate(nodeAt(part, 'expression'), undefined)));
      }
    }
    return texts;
  }

  // The call index ----------------------------------------------------------------------------------

  /**
   * Finds every call of every function, snippet and callback, the props every
   * component is given, and every later write to an object, array, map or
   * store, over as many rounds as it takes to settle.
   */
  index() {
    let before = -1;
    for (let round = 0; round < INDEX_ROUNDS; round += 1) {
      /** @type {Map<Node, Site[]>} */
      const sites = new Map();
      /** @type {Map<Module, Array<() => Entry[]>>} */
      const uses = new Map();
      /** @type {Map<string | undefined, Thunk[]>} */
      const contexts = new Map();
      for (const module of [...this.project.modules]) {
        for (const call of module.calls) this.indexCall(call, sites, uses, contexts);
        for (const tag of module.components) {
          this.fresh();
          for (const target of this.componentTargets(tag))
            pushTo(uses, target, () => this.tagProps(tag));
        }
        for (const action of module.actions) this.indexAction(action, sites);
        for (const boundary of module.boundaries) this.indexBoundary(boundary, sites);
        for (const assignment of module.mutations) this.indexAssignment(assignment, sites);
      }
      this.sites = sites;
      this.uses = uses;
      this.contexts = contexts;
      this.cache.clear();
      let after = 0;
      for (const list of sites.values()) after += list.length;
      for (const list of uses.values()) after += list.length;
      for (const list of contexts.values()) after += list.length;
      for (const added of this.addedEntries.values()) after += added.size;
      for (const added of this.addedItems.values()) after += added.size;
      for (const paths of this.addedAtPath.values()) {
        for (const writers of paths.values()) after += writers.size;
      }
      if (after === before) break;
      before = after;
    }
  }

  /**
   * @param {Node} call A call or a `new`.
   * @param {Map<Node, Site[]>} sites
   * @param {Map<Module, Array<() => Entry[]>>} uses
   * @param {Map<string | undefined, Thunk[]>} contexts
   */
  indexCall(call, sites, uses, contexts) {
    this.fresh();
    const callee = unwrap(nodeAt(call, 'callee'));
    const site = this.argumentsOf(call, undefined);
    const called = this.evaluate(callee, undefined);
    for (const fn of this.functionsIn(called)) pushTo(sites, fn.node, site);
    const [first, second] = nodesAt(call, 'arguments');
    if (call.type === 'NewExpression') {
      // `new Store(…)` calls the constructor.
      for (const value of called) {
        if (value.t !== 'class') continue;
        const constructor = nodesAt(nodeAt(value.node, 'body'), 'body').find(
          (member) => member.type === 'MethodDefinition' && member.kind === 'constructor',
        );
        const fn = nodeAt(constructor, 'value');
        if (fn !== undefined) pushTo(sites, fn, site);
      }
      return;
    }

    if (callee?.type === 'Identifier') {
      // mount(App, { props }) and hydrate(App, { props }).
      const binding = this.project.lookup(callee);
      const imported = binding === undefined ? undefined : packageImport(binding);
      if (imported?.source === 'svelte' && ['mount', 'hydrate'].includes(imported.name)) {
        for (const target of this.componentsIn(this.evaluate(first, undefined))) {
          pushTo(uses, target, () =>
            this.entriesOf(this.property(this.evaluate(second, undefined), ['props'])),
          );
        }
      }
      if (imported?.source === 'svelte' && imported.name === 'setContext') {
        const keys = this.literals(this.evaluate(first, undefined)).map((text) => text.text);
        for (const key of keys.length > 0 ? keys : [undefined]) {
          pushTo(contexts, key, () => this.evaluate(second, undefined));
        }
      }
      return;
    }
    if (callee?.type !== 'MemberExpression') return;
    const method = this.memberName(callee);
    if (method === undefined) return;
    const object = nodeAt(callee, 'object');

    if (isGlobal(this.project, unwrap(object), 'Object') && method === 'assign') {
      const sources = nodesAt(call, 'arguments').slice(1);
      for (const target of this.evaluate(first, undefined)) {
        if (target.t === 'object' && target.node !== undefined) {
          this.addEntries(target.node, call, () =>
            sources.flatMap((source) => this.entriesOf(this.evaluate(source, undefined))),
          );
        }
      }
      return;
    }

    const receivers = this.evaluate(object, undefined);
    /** @type {Site} An error, as `catch` and error listeners are handed one. */
    const failed = { args: [() => [this.caughtAt(call)]], more: undefined };
    /** @param {Node | undefined} argument @param {Site} handed */
    const hand = (argument, handed) => {
      for (const callback of this.functionsIn(this.evaluate(argument, undefined))) {
        pushTo(sites, callback.node, handed);
      }
    };
    if (method === 'then') {
      hand(first, { args: [() => receivers], more: undefined });
      hand(second, failed);
    }
    if (method === 'catch') hand(first, failed);
    if (
      method === 'addEventListener' &&
      this.literals(this.evaluate(first, undefined)).some((type) => ERROR_EVENTS.has(type.text))
    ) {
      hand(second, failed);
    }
    if (CALLBACK_METHODS.has(method)) {
      /** @type {Thunk} */
      const items = () => this.itemsOf(receivers);
      const reduce = method === 'reduce' || method === 'reduceRight';
      /** @type {Site} */
      const handed = reduce
        ? { args: [() => this.evaluate(second, undefined), items], more: undefined }
        : { args: [items, NOTHING, () => receivers], more: undefined };
      for (const callback of this.functionsIn(this.evaluate(first, undefined))) {
        pushTo(sites, callback.node, handed);
      }
    }
    this.indexWrite(call, method, receivers, site);
  }

  /**
   * `use:tooltip={value}` calls `tooltip(element, value)`.
   * @param {Node} action
   * @param {Map<Node, Site[]>} sites
   */
  indexAction(action, sites) {
    this.fresh();
    const [first = '', ...rest] = (stringAt(action, 'name') ?? '').split('.');
    const binding = this.project.lookupName(action, first);
    let values = binding === undefined ? [] : this.bindingValues(binding, undefined);
    for (const part of rest) values = this.property(values, [part]);
    const expression = nodeAt(action, 'expression');
    /** @type {Site} */
    const site = { args: [NOTHING, () => this.evaluate(expression, undefined)], more: undefined };
    for (const fn of this.functionsIn(values)) pushTo(sites, fn.node, site);
  }

  /**
   * `<svelte:boundary>` hands the error it caught to its `failed` snippet and
   * its `onerror` handler.
   * @param {Node} boundary
   * @param {Map<Node, Site[]>} sites
   */
  indexBoundary(boundary, sites) {
    this.fresh();
    /** @type {Site} */
    const failed = { args: [() => [this.caughtAt(boundary)], NOTHING], more: undefined };
    for (const child of nodesAt(nodeAt(boundary, 'fragment'), 'nodes')) {
      if (
        child.type === 'SnippetBlock' &&
        stringAt(nodeAt(child, 'expression'), 'name') === 'failed'
      ) {
        pushTo(sites, child, failed);
      }
    }
    for (const attribute of nodesAt(boundary, 'attributes')) {
      const name = stringAt(attribute, 'name');
      if (attribute.type !== 'Attribute' || (name !== 'failed' && name !== 'onerror')) continue;
      for (const fn of this.functionsIn(this.attributeValues(attribute)))
        pushTo(sites, fn.node, failed);
    }
  }

  /**
   * Items added to an array, set, map or store by a method call.
   * @param {Node} call
   * @param {string} method
   * @param {Value[]} receivers
   * @param {Site} site
   */
  indexWrite(call, method, receivers, site) {
    const all = () => [...site.args, ...(site.more === undefined ? [] : [site.more])];
    // Whatever the receiver holds, what is added shows wherever it is read.
    const object = nodeAt(unwrap(nodeAt(call, 'callee')), 'object');
    if (['push', 'unshift', 'add'].includes(method)) {
      this.addAtPath(object, call, () => [this.list(all)]);
    } else if (method === 'splice') {
      this.addAtPath(object, call, () => [this.list(() => all().slice(2))]);
    } else if (method === 'set' && site.args.length >= 2) {
      this.addAtPath(object, call, () => [
        {
          t: 'map',
          node: call,
          pairs: () => [this.list(() => [site.args[0] ?? NOTHING, site.args[1] ?? NOTHING], true)],
        },
      ]);
    }
    for (const receiver of receivers) {
      if (receiver.t === 'array' && receiver.node !== undefined) {
        if (['push', 'unshift', 'add'].includes(method)) this.addItems(receiver.node, call, all);
        if (method === 'splice') this.addItems(receiver.node, call, () => all().slice(2));
        if (method === 'fill') this.addItems(receiver.node, call, () => all().slice(0, 1));
      } else if (receiver.t === 'map' && method === 'set') {
        this.addItems(receiver.node, call, () => [
          () => [this.list(() => [site.args[0] ?? NOTHING, site.args[1] ?? NOTHING], true)],
        ]);
      } else if (receiver.t === 'store' && (method === 'set' || method === 'update')) {
        const [given = NOTHING] = site.args;
        this.addItems(receiver.node, call, () => [
          method === 'set'
            ? given
            : () => this.invoke(given(), { args: [receiver.value], more: undefined }),
        ]);
      }
    }
  }

  /**
   * `target.key = value` and `list[i] = value`; `window.onerror = handler`
   * hands the handler an error.
   * @param {Node} assignment
   * @param {Map<Node, Site[]>} sites
   */
  indexAssignment(assignment, sites) {
    this.fresh();
    const left = unwrap(nodeAt(assignment, 'left'));
    if (left?.type !== 'MemberExpression') return;
    const right = nodeAt(assignment, 'right');
    const keys = this.memberKeys(left);
    if (keys?.some((key) => ERROR_HANDLERS.has(key)) === true) {
      /** @type {Site} */
      const failed = { args: [() => [this.caughtAt(assignment)]], more: undefined };
      for (const fn of this.functionsIn(this.evaluate(right, undefined))) {
        pushTo(sites, fn.node, failed);
      }
    }
    /** @type {Thunk} */
    const read = () => this.evaluate(right, undefined);
    this.addAtPath(left, assignment, read);
    for (const target of this.evaluate(nodeAt(left, 'object'), undefined)) {
      if (target.t === 'object' && target.node !== undefined) {
        this.addEntries(target.node, assignment, () =>
          (keys ?? [undefined]).map((key) => ({ key, name: undefined, value: read })),
        );
      } else if (target.t === 'array' && target.node !== undefined) {
        this.addItems(target.node, assignment, () => [read]);
      }
    }
  }

  /**
   * The name and member path an expression reads, when it is written out:
   * `data.rows` is `data` and ".rows". Undefined for anything computed.
   * @param {Node | undefined} node
   * @returns {{ binding: Binding, path: string } | undefined}
   */
  staticPath(node) {
    if (node === undefined) return undefined;
    const known = this.paths.get(node);
    if (known !== undefined) return known ?? undefined;
    /** @type {{ binding: Binding, path: string } | null} */
    let found = null;
    const target = unwrap(node);
    if (target?.type === 'Identifier') {
      const binding = this.project.lookup(target);
      if (binding !== undefined) found = { binding, path: '' };
    } else if (target?.type === 'MemberExpression') {
      const key = this.memberName(target);
      const inner = key === undefined ? undefined : this.staticPath(nodeAt(target, 'object'));
      if (inner !== undefined && key !== undefined) {
        found = { binding: inner.binding, path: `${inner.path}.${key}` };
      }
    }
    this.paths.set(node, found);
    return found ?? undefined;
  }

  /**
   * Notes values written at a name's member path.
   * @param {Node | undefined} target
   * @param {Node} writer
   * @param {Thunk} values
   */
  addAtPath(target, writer, values) {
    const at = this.staticPath(target);
    if (at === undefined) return;
    let paths = this.addedAtPath.get(at.binding);
    if (paths === undefined) {
      paths = new Map();
      this.addedAtPath.set(at.binding, paths);
    }
    let writers = paths.get(at.path);
    if (writers === undefined) {
      writers = new Map();
      paths.set(at.path, writers);
    }
    if (!writers.has(writer)) writers.set(writer, values);
  }

  /**
   * What was written at the member path an expression reads.
   * @param {Node} node
   * @returns {Value[]}
   */
  pathValues(node) {
    if (this.addedAtPath.size === 0) return [];
    const at = this.staticPath(node);
    const writers = at === undefined ? undefined : this.addedAtPath.get(at.binding)?.get(at.path);
    if (writers === undefined) return [];
    return [...writers].flatMap(([writer, values]) => this.once(writer, undefined, values));
  }

  /**
   * @param {Node} target
   * @param {Node} writer
   * @param {() => Entry[]} entries
   */
  addEntries(target, writer, entries) {
    let added = this.addedEntries.get(target);
    if (added === undefined) {
      added = new Map();
      this.addedEntries.set(target, added);
    }
    if (!added.has(writer)) added.set(writer, entries);
  }

  /**
   * @param {Node} target
   * @param {Node} writer
   * @param {() => Thunk[]} items
   */
  addItems(target, writer, items) {
    let added = this.addedItems.get(target);
    if (added === undefined) {
      added = new Map();
      this.addedItems.set(target, added);
    }
    if (!added.has(writer)) added.set(writer, items);
  }

  // Places text shows ----------------------------------------------------------------------------------

  /**
   * Reports every module the project scans.
   * @returns {Finding[]}
   */
  check() {
    for (const module of this.project.scanned) {
      if (module.error !== undefined) {
        this.findings.push({
          file: module.file,
          ...module.at(module.error.offset),
          message: `cannot read this file, so its text cannot be checked: ${module.error.message}`,
        });
        continue;
      }
      if (module.kind === 'svelte') this.checkMarkup(module);
      this.checkWrites(module);
    }
    return this.findings;
  }

  /**
   * @param {Module} module
   * @param {Node | undefined} node
   * @param {string} where
   * @param {string} [verb]
   * @returns {Sink}
   */
  sink(module, node, where, verb = 'in') {
    return { module, offset: numberAt(node, 'start') ?? 0, where, verb };
  }

  /**
   * Reports the literal text that reaches one place.
   * @param {Sink} sink
   * @param {Reading} reading
   * @param {() => Value[]} produce
   */
  examine(sink, reading, produce) {
    this.fresh();
    for (const shown of this.strings(produce())) {
      switch (shown.t) {
        case 'text':
          this.reportText(shown, sink, reading);
          break;
        case 'code':
          // A symbol from copy.ts (a middle dot) may show like one written in place.
          if (shown.text !== '' && isSymbolsOnly(shown.text)) break;
          if (reading !== 'prose' || looksLikeProse(shown.text)) {
            const what = shown.what.replace('%s', () => quote(shown.text));
            this.reportAtSink(sink, `${what} ${sink.verb} ${sink.where}; ${shown.fix}`);
          }
          break;
        case 'caught': {
          const at = `${shown.module.file}:${String(shown.module.at(shown.offset).line)}`;
          const what =
            shown.made === true
              ? `an error's text (made at ${at})`
              : `a caught error's text (caught at ${at})`;
          this.reportAtSink(sink, `${what} ${sink.verb} ${sink.where}; show a string from copy.ts`);
          break;
        }
        default:
          // Copy itself.
          break;
      }
    }
    const key = `steps:${sink.module.file}:${String(sink.offset)}`;
    if (this.exhausted && !this.tooDeep.has(key)) {
      this.tooDeep.add(key);
      this.findings.push({
        file: sink.module.file,
        ...sink.module.at(sink.offset),
        message: `text reaches ${sink.where} through more steps than the copy lint follows; build it more simply`,
      });
    }
  }

  /**
   * Reports text that is not a literal, where it shows, once per place.
   * @param {Sink} sink
   * @param {string} message
   */
  reportAtSink(sink, message) {
    const key = `sink:${sink.module.file}:${String(sink.offset)}:${message}`;
    if (this.reported.has(key)) return;
    /** @type {Finding} */
    const finding = { file: sink.module.file, ...sink.module.at(sink.offset), message };
    this.findings.push(finding);
    this.reported.set(key, { finding, message, places: new Set() });
  }

  /**
   * @param {TextValue} text
   * @param {Sink} sink
   * @param {Reading} reading
   */
  reportText(text, sink, reading) {
    for (const piece of this.pieces(text.text, reading)) {
      if (isSymbolsOnly(piece)) continue;
      if ((reading === 'prose' || text.loose === true) && !looksLikeProse(piece)) continue;
      const key = `${text.module.file}:${String(text.offset)}:${piece}`;
      const shown = sink.module.at(sink.offset);
      const place = `${sink.module.file}:${String(shown.line)} ${sink.where}`;
      const known = this.reported.get(key);
      if (known !== undefined) {
        // One finding per literal: the first place it shows, and how many more.
        if (known.places.has(place)) continue;
        known.places.add(place);
        const more = known.places.size - 1;
        known.finding.message = `${known.message}, and ${String(more)} more ${more === 1 ? 'place' : 'places'}; take it from copy.ts`;
        continue;
      }
      const written = text.module.at(text.offset);
      const here = text.module.file === sink.module.file && written.line === shown.line;
      const elsewhere = here ? '' : ` at ${sink.module.file}:${String(shown.line)}`;
      const message = `literal text ${quote(piece)} ${sink.verb} ${sink.where}${elsewhere}`;
      /** @type {Finding} */
      const finding = {
        file: text.module.file,
        ...written,
        message: `${message}; take it from copy.ts`,
      };
      this.findings.push(finding);
      this.reported.set(key, { finding, message, places: new Set([place]) });
    }
  }

  /**
   * The parts of a string a place shows: HTML's text, CSS `content` strings,
   * a map label without its {field} tokens, or the string itself.
   * @param {string} text
   * @param {Reading} reading
   * @returns {string[]}
   */
  pieces(text, reading) {
    switch (reading) {
      case 'html':
        return htmlFragmentText(this.project.html, text, this.project.cssAttributes);
      case 'css':
        return cssStrings(text).map((found) => found.text);
      case 'map':
        return [text.replace(/\{[^{}]*\}/gu, ' ')];
      default:
        return [text];
    }
  }

  /**
   * Markup: text, expressions, attributes, {@html}, {@render} and styles.
   * @param {Module} module
   */
  checkMarkup(module) {
    /**
     * @param {Node | undefined} fragment
     * @param {string} parent
     */
    const walk = (fragment, parent) => {
      const where = parent === '' ? 'the markup' : `<${parent}>`;
      for (const node of nodesAt(fragment, 'nodes')) {
        const expression = nodeAt(node, 'expression');
        switch (node.type) {
          case 'Text':
            if (parent !== 'style' && parent !== 'script') this.markupText(module, node, where);
            break;
          case 'ExpressionTag':
            this.examine(this.sink(module, expression, where), 'text', () =>
              this.evaluate(expression, undefined),
            );
            break;
          case 'HtmlTag':
            this.examine(this.sink(module, expression, where), 'html', () =>
              this.evaluate(expression, undefined),
            );
            break;
          case 'RenderTag':
            this.renderTag(module, node, where);
            break;
          default:
            if (ELEMENT_TYPES.has(node.type) || COMPONENT_TYPES.has(node.type)) {
              const name = stringAt(node, 'name') ?? node.type;
              this.checkAttributes(module, node, name);
              if (node.type === 'RegularElement') this.browserWords(module, node, name);
              walk(nodeAt(node, 'fragment'), name);
            } else {
              for (const key of FRAGMENT_KEYS) walk(nodeAt(node, key), parent);
            }
        }
      }
    };
    walk(nodeAt(module.root, 'fragment'), '');

    const content = nodeAt(module.root, 'css')?.content;
    const styles = isFields(content) ? stringAt(content, 'styles') : undefined;
    const start = isFields(content) ? (numberAt(content, 'start') ?? 0) : 0;
    if (styles !== undefined) this.checkCss(module, styles, start, 'CSS content in <style>');
  }

  /**
   * Elements the browser labels in its own words when the page gives none:
   * a submit or reset button without a value ("Submit"), and <details>
   * without a <summary> ("Details").
   * @param {Module} module
   * @param {Node} element
   * @param {string} name
   */
  browserWords(module, element, name) {
    const attributes = nodesAt(element, 'attributes');
    const given = (/** @type {string} */ attribute) =>
      attributes.some(
        (entry) =>
          entry.type === 'SpreadAttribute' ||
          ((entry.type === 'Attribute' || entry.type === 'BindDirective') &&
            entry.name === attribute),
      );
    const type = (staticAttribute(attributes, 'type') ?? '').toLowerCase();
    /** @param {string} what */
    const report = (what) => {
      this.findings.push({
        file: module.file,
        ...module.at(numberAt(element, 'start') ?? 0),
        message: `${what} shows the browser's own words; give it text from copy.ts`,
      });
    };
    if (name === 'input' && (type === 'submit' || type === 'reset') && !given('value')) {
      report(`<input type="${type}"> without a value`);
    }
    if (name === 'details') {
      const children = nodesAt(nodeAt(element, 'fragment'), 'nodes');
      const summary = children.some(
        (child) =>
          (child.type === 'RegularElement' && child.name === 'summary') ||
          !['RegularElement', 'Text', 'Comment'].includes(child.type),
      );
      if (!summary) report('<details> without a <summary>');
    }
  }

  /**
   * Text written straight into the markup.
   * @param {Module} module
   * @param {Node} node
   * @param {string} where
   */
  markupText(module, node, where) {
    const data = stringAt(node, 'data') ?? '';
    if (isSymbolsOnly(data)) return;
    // Point at the first visible character, counted in the source as written.
    const raw = stringAt(node, 'raw') ?? data;
    const offset = (numberAt(node, 'start') ?? 0) + raw.length - raw.trimStart().length;
    this.reportText(
      { t: 'text', text: data, module, offset },
      this.sink(module, node, where),
      'text',
    );
  }

  /**
   * CSS `content` strings, which show on screen.
   * @param {Module} module
   * @param {string} css
   * @param {number} start
   * @param {string} where
   */
  checkCss(module, css, start, where) {
    for (const found of cssStrings(css)) {
      const offset = start + found.offset;
      this.reportText(
        { t: 'text', text: found.text, module, offset },
        { module, offset, where, verb: 'in' },
        'text',
      );
    }
  }

  /**
   * `{@render row(…)}`: a snippet of this project shows its arguments in its
   * own markup, which is checked with them; arguments to any other snippet
   * are reported here.
   * @param {Module} module
   * @param {Node} node
   * @param {string} where
   */
  renderTag(module, node, where) {
    const call = unwrap(nodeAt(node, 'expression'));
    const callee = unwrap(nodeAt(call, 'callee'));
    this.fresh();
    const snippets = this.functionsIn(this.evaluate(callee, undefined));
    if (snippets.some((snippet) => snippet.node.type === 'SnippetBlock')) return;
    for (const argument of nodesAt(call, 'arguments')) {
      const sink = this.sink(module, argument, `{@render} in ${where}`, 'passed to');
      this.examine(sink, 'text', () => {
        const values = this.evaluate(argument, undefined);
        return [...values, ...this.textKeyed(values)];
      });
      this.examine(sink, 'prose', () => this.nested(this.evaluate(argument, undefined)));
    }
  }

  /**
   * An element's or component's attributes.
   * @param {Module} module
   * @param {Node} element
   * @param {string} name
   */
  checkAttributes(module, element, name) {
    const component = COMPONENT_TYPES.has(element.type);
    this.fresh();
    // A component of this project shows its props in its own markup, which is
    // checked with the values given here. One from a package is judged here.
    const foreign = component && this.componentTargets(element).length === 0;
    const attributes = nodesAt(element, 'attributes');
    const inputType = (staticAttribute(attributes, 'type') ?? '').toLowerCase();
    const metaName = staticAttribute(attributes, 'name') ?? staticAttribute(attributes, 'property');
    /** @param {string} attribute */
    const shows = (attribute) =>
      component
        ? TEXT_PROPS.has(attribute)
        : showsText(name, attribute, inputType, metaName, this.project.cssAttributes);

    for (const attribute of attributes) {
      const attributeName = stringAt(attribute, 'name') ?? '';
      const expression = nodeAt(attribute, 'expression');
      const where = `${attributeName}="…" on <${name}>`;
      switch (attribute.type) {
        case 'Attribute':
          if (shows(attributeName)) {
            this.examine(this.sink(module, attribute, where), 'text', () =>
              this.attributeValues(attribute),
            );
          } else if (attributeName === 'style' && !component) {
            this.checkStyleAttribute(module, attribute, name);
          } else if (foreign) {
            this.foreignProp(module, attribute, where, () => this.attributeValues(attribute));
          }
          break;
        case 'BindDirective':
          // bind:textContent and bind:innerHTML write their value into the element.
          if (shows(attributeName) || (!component && DOM_TEXT_PROPERTIES.has(attributeName))) {
            this.examine(
              this.sink(module, attribute, `bind:${where}`),
              DOM_HTML_PROPERTIES.has(attributeName) ? 'html' : 'text',
              () => this.evaluate(expression, undefined),
            );
          }
          break;
        case 'SpreadAttribute': {
          const sink = this.sink(module, attribute, `a spread on <${name}>`);
          const entries = () => this.entriesOf(this.evaluate(expression, undefined));
          this.examine(sink, 'text', () =>
            entries()
              .filter((entry) => entry.key === undefined || shows(entry.key))
              .flatMap((entry) => entry.value()),
          );
          if (foreign) {
            this.foreignProp(module, attribute, `a spread on <${name}>`, () =>
              entries()
                .filter((entry) => entry.key !== undefined && !shows(entry.key))
                .flatMap((entry) => entry.value()),
            );
          }
          break;
        }
        case 'StyleDirective':
          if (attributeName === 'content') {
            this.examine(this.sink(module, attribute, `style:content on <${name}>`), 'css', () =>
              this.attributeValues(attribute).map((value) =>
                value.t === 'text' ? { ...value, text: `content: ${value.text}` } : value,
              ),
            );
          }
          break;
        default:
          break;
      }
    }
  }

  /**
   * A prop of a component the lint cannot read: text under a text key, and
   * anything that reads as words.
   * @param {Module} module
   * @param {Node} attribute
   * @param {string} where
   * @param {() => Value[]} produce
   */
  foreignProp(module, attribute, where, produce) {
    const sink = this.sink(module, attribute, where, 'passed to');
    this.examine(sink, 'text', () => this.textKeyed(produce()));
    this.examine(sink, 'prose', () => this.nested(produce()));
  }

  /**
   * `style="content: '…'"`. An expression right after `content:` is the
   * declaration's value; any other expression is read as declarations.
   * @param {Module} module
   * @param {Node} attribute
   * @param {string} name
   */
  checkStyleAttribute(module, attribute, name) {
    const where = `style="…" on <${name}>`;
    const value = attribute.value;
    let written = '';
    for (const part of Array.isArray(value) ? value.filter(isNode) : isNode(value) ? [value] : []) {
      const data = stringAt(part, 'data');
      if (part.type === 'Text' && data !== undefined) {
        this.checkCss(module, data, numberAt(part, 'start') ?? 0, where);
        written += data;
      } else if (part.type === 'ExpressionTag') {
        const expression = nodeAt(part, 'expression');
        const isValue = /(?<![\w-])content\s*:\s*$/iu.test(written);
        this.examine(this.sink(module, part, where), 'css', () =>
          this.strings(this.evaluate(expression, undefined)).map((text) =>
            isValue && text.t === 'text' ? { ...text, text: `content: ${text.text}` } : text,
          ),
        );
        written += ' x';
      }
    }
  }

  /**
   * DOM writes, dialogs, notifications, the share sheet, map popups and
   * labels, and manifests built in code.
   * @param {Module} module
   */
  checkWrites(module) {
    for (const node of module.writes) {
      switch (node.type) {
        case 'AssignmentExpression':
          this.assignmentWrite(module, node);
          break;
        case 'CallExpression':
          this.callWrite(module, node);
          this.intlWords(module, node);
          break;
        case 'NewExpression':
          this.constructWrite(module, node);
          this.intlWords(module, node);
          break;
        case 'Property':
          this.propertyWrite(module, node);
          break;
        default:
          break;
      }
    }
  }

  /**
   * `el.textContent = …`.
   * @param {Module} module
   * @param {Node} node
   */
  assignmentWrite(module, node) {
    const left = unwrap(nodeAt(node, 'left'));
    if (left?.type !== 'MemberExpression') return;
    this.fresh();
    // `el[key] = …` with `key` a constant counts as much as `el.textContent = …`.
    const keys =
      this.memberKeys(left) ??
      this.literals(this.evaluate(nodeAt(left, 'property'), undefined)).map((text) => text.text);
    const right = nodeAt(node, 'right');
    // `el.dataset.label = …` sets data-label, which CSS may show with attr().
    const holder = unwrap(nodeAt(left, 'object'));
    if (holder?.type === 'MemberExpression' && this.memberName(holder) === 'dataset') {
      const attribute = keys
        .map((key) => `data-${key.replace(/\p{Lu}/gu, (letter) => `-${letter.toLowerCase()}`)}`)
        .find((name) => this.project.cssAttributes.has(name));
      if (attribute !== undefined) {
        this.examine(
          this.sink(module, node, `the ${attribute} attribute`, 'written to'),
          'text',
          () => this.evaluate(right, undefined),
        );
      }
      return;
    }
    const property = keys.find((key) => DOM_TEXT_PROPERTIES.has(key) || key === 'cssText');
    if (property === undefined) return;
    if (SHARED_PROPERTY_NAMES.has(property)) {
      const targets = this.evaluate(nodeAt(left, 'object'), undefined);
      const own = targets.length > 0 && targets.every((target) => target.t === 'object');
      if (own) return;
    }
    this.examine(
      this.sink(module, node, `.${property}`, 'written to'),
      property === 'cssText' ? 'css' : DOM_HTML_PROPERTIES.has(property) ? 'html' : 'text',
      () => this.evaluate(right, undefined),
    );
  }

  /**
   * @param {Module} module
   * @param {Node} node
   */
  callWrite(module, node) {
    const callee = unwrap(nodeAt(node, 'callee'));
    const receiver =
      callee?.type === 'MemberExpression' ? unwrap(nodeAt(callee, 'object')) : undefined;
    const name =
      callee?.type === 'Identifier'
        ? stringAt(callee, 'name')
        : callee?.type === 'MemberExpression'
          ? this.memberName(callee)
          : undefined;
    if (name === undefined || callee === undefined) return;
    const args = nodesAt(node, 'arguments');
    /**
     * @param {Node | undefined} argument
     * @param {string} where
     * @param {Reading} [reading]
     */
    const show = (argument, where, reading = 'text') => {
      if (argument !== undefined) {
        this.examine(this.sink(module, node, where, 'written to'), reading, () =>
          this.evaluate(argument, undefined),
        );
      }
    };
    /**
     * @param {Node | undefined} argument
     * @param {string[]} keys
     * @param {string} where
     */
    const showKeys = (argument, keys, where) => {
      if (argument !== undefined) {
        this.examine(this.sink(module, node, where, 'written to'), 'text', () =>
          this.property(this.evaluate(argument, undefined), keys),
        );
      }
    };
    const windowCall =
      callee.type === 'Identifier'
        ? this.project.lookup(callee) === undefined
        : isGlobal(this.project, receiver, WINDOW_NAMES);
    if (DIALOG_CALLS.has(name)) {
      if (windowCall) for (const argument of args) show(argument, `${name}()`);
      return;
    }
    // The rest are methods of the DOM or of MapLibre: `el.append(…)`, not a
    // function of this project that happens to share the name.
    if (callee.type !== 'MemberExpression') return;
    this.fresh();
    if (this.functionsIn(this.property(this.evaluate(receiver, undefined), [name])).length > 0) {
      return;
    }

    switch (name) {
      case 'setAttribute':
      case 'setAttributeNS': {
        const [attribute, value] = name === 'setAttribute' ? args : args.slice(1);
        this.fresh();
        const shown = this.literals(this.evaluate(attribute, undefined))
          .map((text) => text.text.toLowerCase())
          .find(
            (text) =>
              TEXT_ATTRIBUTES.has(text) ||
              text === 'content' ||
              this.project.cssAttributes.has(text),
          );
        if (shown !== undefined) show(value, `the ${shown} attribute`);
        break;
      }
      case 'append':
      case 'prepend':
        if (!this.isQueryData(receiver)) for (const argument of args) show(argument, `${name}()`);
        break;
      case 'replaceChildren':
      case 'before':
      case 'after':
      case 'replaceWith':
        for (const argument of args) show(argument, `${name}()`);
        break;
      case 'createTextNode':
        show(args[0], 'createTextNode()');
        break;
      case 'insertAdjacentText':
        show(args[1], 'insertAdjacentText()');
        break;
      case 'insertAdjacentHTML':
        show(args[1], 'insertAdjacentHTML()', 'html');
        break;
      case 'setHTMLUnsafe':
        show(args[0], 'setHTMLUnsafe()', 'html');
        break;
      case 'write':
      case 'writeln':
        if (isGlobal(this.project, receiver, 'document')) {
          for (const argument of args) show(argument, `document.${name}()`, 'html');
        }
        break;
      case 'setCustomValidity':
        show(args[0], 'setCustomValidity()');
        break;
      case 'setText':
        show(args[0], 'setText()');
        break;
      case 'setHTML':
        show(args[0], 'setHTML()', 'html');
        break;
      // CSS written from code: its `content` strings show.
      case 'insertRule':
      case 'replaceSync':
        show(args[0], `${name}()`, 'css');
        break;
      case 'setProperty': {
        this.fresh();
        const names = this.literals(this.evaluate(args[0], undefined)).map((text) => text.text);
        if (names.includes('content')) {
          this.examine(this.sink(module, node, 'setProperty()', 'written to'), 'css', () =>
            this.strings(this.evaluate(args[1], undefined)).map((text) =>
              text.t === 'text' ? { ...text, text: `content: ${text.text}` } : text,
            ),
          );
        }
        break;
      }
      case 'showNotification':
        show(args[0], 'a notification');
        showKeys(args[1], ['body', 'title'], 'a notification');
        break;
      case 'share':
        if (
          isGlobal(this.project, receiver, 'navigator') ||
          (receiver?.type === 'MemberExpression' &&
            this.memberName(receiver) === 'navigator' &&
            isGlobal(this.project, unwrap(nodeAt(receiver, 'object')), WINDOW_NAMES))
        ) {
          showKeys(args[0], ['title', 'text'], 'the share sheet');
        }
        break;
      case 'writeText':
        // What a person pastes: a link, usually, so only words count.
        if (receiver?.type === 'MemberExpression' && this.memberName(receiver) === 'clipboard') {
          show(args[0], 'the clipboard', 'prose');
        }
        break;
      case 'setLayoutProperty': {
        this.fresh();
        const keys = this.literals(this.evaluate(args[1], undefined)).map((text) => text.text);
        if (keys.includes('text-field')) this.mapLabel(module, node, args[2]);
        break;
      }
      case 'assign':
        if (isGlobal(this.project, receiver, 'Object')) {
          for (const source of args.slice(1)) {
            this.examine(this.sink(module, node, 'Object.assign()', 'written to'), 'text', () =>
              this.entriesOf(this.evaluate(source, undefined))
                .filter((entry) => entry.key === undefined || DOM_TEXT_PROPERTIES.has(entry.key))
                .flatMap((entry) => entry.value()),
            );
          }
        }
        break;
      default:
        break;
    }
  }

  /**
   * Whether `x.append(…)` adds a field to query or form data, not text to the page.
   * @param {Node | undefined} receiver
   */
  isQueryData(receiver) {
    if (receiver === undefined) return false;
    this.fresh();
    const made = this.evaluate(receiver, undefined).some(
      (value) =>
        value.t === 'instance' && ['URLSearchParams', 'FormData', 'Headers'].includes(value.name),
    );
    const name =
      receiver.type === 'Identifier'
        ? stringAt(receiver, 'name')
        : receiver.type === 'MemberExpression'
          ? this.memberName(receiver)
          : undefined;
    return made || /(?:params|headers|formdata)$/iu.test(name ?? '');
  }

  /**
   * Dates, lists and relative times worded by Intl belong in copy.ts, with the
   * rest of the words: `toLocaleDateString()`, `Intl.RelativeTimeFormat`, and
   * `Intl.DateTimeFormat` or `toLocaleString()` asked for month or day names.
   * @param {Module} module
   * @param {Node} node A call or a `new`.
   */
  intlWords(module, node) {
    const callee = unwrap(nodeAt(node, 'callee'));
    if (callee?.type !== 'MemberExpression') return;
    const name = this.memberName(callee);
    const object = unwrap(nodeAt(callee, 'object'));
    const args = nodesAt(node, 'arguments');
    const intl = isGlobal(this.project, object, 'Intl');
    /** @param {Node | undefined} options */
    const asksForWords = (options) => {
      this.fresh();
      const given = this.evaluate(options, undefined);
      return [...WORD_OPTIONS].some(([key, wordy]) =>
        this.literals(this.property(given, [key])).some(
          (text) => wordy === undefined || wordy.has(text.text),
        ),
      );
    };
    let words = false;
    if (intl && name !== undefined && WORD_FORMATTERS.has(name)) words = true;
    else if (intl && (name === 'DateTimeFormat' || name === 'NumberFormat')) {
      words = asksForWords(args[1]);
    } else if (!intl && name !== undefined && DATE_WORD_METHODS.has(name)) words = true;
    else if (!intl && name === 'toLocaleString') words = asksForWords(args[1]);
    if (!words) return;
    const what = intl ? `Intl.${name ?? ''}` : `${name ?? ''}()`;
    this.findings.push({
      file: module.file,
      ...module.at(numberAt(node, 'start') ?? 0),
      message: `${what} writes words outside copy.ts; add a formatter to copy.ts and use it`,
    });
  }

  /**
   * `new Notification(…)`, `new Option(…)`, `new Text(…)`, `new SpeechSynthesisUtterance(…)`.
   * @param {Module} module
   * @param {Node} node
   */
  constructWrite(module, node) {
    const callee = unwrap(nodeAt(node, 'callee'));
    const [first, second] = nodesAt(node, 'arguments');
    /**
     * @param {string} where
     * @param {() => Value[]} produce
     */
    const show = (where, produce) => {
      this.examine(this.sink(module, node, where, 'written to'), 'text', produce);
    };
    if (isGlobal(this.project, callee, 'Notification')) {
      show('a notification', () => [
        ...this.evaluate(first, undefined),
        ...this.property(this.evaluate(second, undefined), ['body']),
      ]);
    } else if (isGlobal(this.project, callee, new Set(['Option', 'Text']))) {
      show(`new ${stringAt(callee, 'name') ?? ''}()`, () => this.evaluate(first, undefined));
    } else if (isGlobal(this.project, callee, 'SpeechSynthesisUtterance')) {
      // Read aloud.
      show('speech', () => this.evaluate(first, undefined));
    }
  }

  /**
   * A `text-field` layout property, or a web app `manifest` built in code.
   * @param {Module} module
   * @param {Node} node
   */
  propertyWrite(module, node) {
    const key = keyName(nodeAt(node, 'key'));
    const value = nodeAt(node, 'value');
    if (key === 'text-field') {
      this.mapLabel(module, node, value);
      return;
    }
    if (key !== 'manifest') return;
    const manifest = () => this.evaluate(value, undefined);
    /**
     * @param {() => Value[]} holder
     * @param {string[]} keys
     * @param {string} where
     */
    const show = (holder, keys, where) => {
      for (const field of keys) {
        this.examine(this.sink(module, node, `manifest ${where}${field}`), 'text', () =>
          this.property(holder(), [field]),
        );
      }
    };
    show(manifest, ['name', 'short_name', 'description'], '');
    show(
      () => this.itemsOf(this.property(manifest(), ['shortcuts'])),
      ['name', 'short_name', 'description'],
      'shortcut ',
    );
    show(() => this.itemsOf(this.property(manifest(), ['screenshots'])), ['label'], 'screenshot ');
  }

  /**
   * A MapLibre `text-field`: a string, or an expression whose output
   * positions are strings. Property names (`['get', 'name']`) are data.
   * @param {Module} module
   * @param {Node} node
   * @param {Node | undefined} value
   */
  mapLabel(module, node, value) {
    this.examine(this.sink(module, node, 'a map label'), 'map', () =>
      this.mapOutputs(this.evaluate(value, undefined), 0),
    );
  }

  /**
   * @param {Value[]} values
   * @param {number} depth
   * @returns {Value[]}
   */
  mapOutputs(values, depth) {
    /** @type {Value[]} */
    const found = [];
    if (depth > 8) return found;
    for (const value of values) {
      if (value.t !== 'array') {
        // Text, copy or a code: `strings` reads it where it shows.
        found.push(value);
        continue;
      }
      const items = value.items();
      const operator = this.literals((items[0] ?? NOTHING)()).map((text) => text.text);
      if (operator.length === 1 && MAP_LOOKUPS.has(operator[0] ?? '')) continue;
      const positions =
        value.exact && operator.length === 1
          ? mapOutputPositions(operator[0] ?? '', items.length)
          : items.map((_, index) => index).slice(1);
      for (const position of positions) {
        found.push(...this.mapOutputs((items[position] ?? NOTHING)(), depth + 1));
      }
    }
    return found;
  }
}

/**
 * Where a MapLibre expression's output values are, by operator.
 * @param {string} operator
 * @param {number} length
 * @returns {number[]}
 */
function mapOutputPositions(operator, length) {
  const from = (/** @type {number} */ start, /** @type {number} */ step) => {
    /** @type {number[]} */
    const positions = [];
    for (let i = start; i < length; i += step) positions.push(i);
    return positions;
  };
  switch (operator) {
    case 'case':
      return [...from(2, 2), length - 1];
    case 'match':
      return [...from(3, 2), length - 1];
    case 'step':
      return from(2, 2);
    case 'let':
      return [length - 1];
    default:
      return from(1, 1);
  }
}

/**
 * The package and name a binding is imported from, when it is one import from a package.
 * @param {Binding} binding
 * @returns {{ source: string, name: string } | undefined}
 */
function packageImport(binding) {
  const [only] = binding.origins;
  if (binding.origins.length !== 1 || only === undefined || only.path.length > 0) return undefined;
  const from = only.from;
  if (from.kind !== 'import' || from.source.startsWith('.') || from.source.startsWith('/')) {
    return undefined;
  }
  return { source: from.source, name: from.name };
}

/**
 * The static text of an attribute, when it is plain text.
 * @param {Node[]} attributes
 * @param {string} name
 * @returns {string | undefined}
 */
function staticAttribute(attributes, name) {
  const attribute = attributes.find((entry) => entry.type === 'Attribute' && entry.name === name);
  const value = attribute?.value;
  const [first] = Array.isArray(value) ? value.filter(isNode) : [];
  return first?.type === 'Text' ? stringAt(first, 'data') : undefined;
}

// CSS and HTML strings -------------------------------------------------------------------------------

/**
 * The strings CSS shows, decoded, with their offsets: in `content`, and in
 * list markers.
 * @param {string} css
 * @returns {Array<{ text: string, offset: number }>}
 */
function cssStrings(css) {
  // Comments become spaces so offsets stay put.
  const clean = css.replace(/\/\*[\s\S]*?\*\//gu, (comment) => ' '.repeat(comment.length));
  /** @type {Array<{ text: string, offset: number }>} */
  const found = [];
  // `content`, and a list marker written as a string: `list-style: '→ '`.
  for (const declaration of clean.matchAll(
    /(?<![\w-])(?:content|list-style|list-style-type)\s*:([^;{}]*)/giu,
  )) {
    const value = declaration[1] ?? '';
    const valueStart = declaration.index + declaration[0].length - value.length;
    for (const string of value.matchAll(/(["'])((?:\\[\s\S]|(?!\1)[^\\\n])*)\1/gu)) {
      found.push({ text: decodeCss(string[2] ?? ''), offset: valueStart + string.index });
    }
  }
  return found;
}

/**
 * The attributes a stylesheet shows with `content: attr(name)`: their values
 * reach the screen as text.
 * @param {string} css
 * @returns {string[]}
 */
function cssAttributes(css) {
  const clean = css.replace(/\/\*[\s\S]*?\*\//gu, ' ');
  /** @type {string[]} */
  const names = [];
  for (const declaration of clean.matchAll(/(?<![\w-])content\s*:([^;{}]*)/giu)) {
    for (const found of (declaration[1] ?? '').matchAll(/attr\(\s*(?:[\w-]*\|)?([\w-]+)/giu)) {
      if (found[1] !== undefined) names.push(found[1].toLowerCase());
    }
  }
  return names;
}

/**
 * The CSS a component writes: its <style>, and its static `style` attributes
 * and `style:content` directives.
 * @param {Node | undefined} root
 * @returns {string[]}
 */
function componentCss(root) {
  /** @type {string[]} */
  const found = [];
  const content = nodeAt(root, 'css')?.content;
  const styles = isFields(content) ? stringAt(content, 'styles') : undefined;
  if (styles !== undefined) found.push(styles);
  /** @param {unknown} value */
  const visit = (value) => {
    if (Array.isArray(value)) {
      value.forEach(visit);
      return;
    }
    if (!isNode(value)) return;
    const name = stringAt(value, 'name');
    const inline =
      (value.type === 'Attribute' && name === 'style') ||
      (value.type === 'StyleDirective' && name === 'content');
    if (inline) {
      const parts = Array.isArray(value.value) ? value.value.filter(isNode) : [];
      const text = parts.map((part) => stringAt(part, 'data') ?? ' ').join('');
      found.push(value.type === 'StyleDirective' ? `content: ${text}` : text);
    }
    for (const [key, child] of Object.entries(value)) {
      if (!SKIP_KEYS.has(key) && key !== 'css') visit(child);
    }
  };
  visit(nodeAt(root, 'fragment'));
  return found;
}

/**
 * Decodes CSS string escapes: `\2022` is a bullet.
 * @param {string} text
 */
function decodeCss(text) {
  return text.replace(/\\(?:([0-9a-f]{1,6})\s?|(\n)|([\s\S]))/giu, (_, hex, newline, char) => {
    if (typeof hex === 'string') {
      const code = Number.parseInt(hex, 16);
      return code === 0 || code > 0x10ffff ? '�' : String.fromCodePoint(code);
    }
    return typeof newline === 'string' ? '' : String(char);
  });
}

/** Elements whose content never shows. A <template>'s content is meant to be shown, so it counts. */
const HIDDEN_ELEMENTS = new Set(['script', 'style']);
/** JSON-LD fields a search result can show. */
const JSON_LD_TEXT = new Set([
  'name',
  'alternateName',
  'headline',
  'description',
  'disambiguatingDescription',
  'caption',
  'text',
  'slogan',
]);

/**
 * @typedef {object} HtmlString
 * @property {string} text
 * @property {number} line
 * @property {number} column
 * @property {string} where
 */

/**
 * Every visible string in a parse5 tree, in document order: text, text
 * attributes, visible meta content and JSON-LD fields.
 * @param {unknown} tree
 * @param {ReadonlySet<string>} [cssShown] Attributes that CSS shows with `content: attr(…)`.
 * @returns {HtmlString[]}
 */
function htmlStrings(tree, cssShown) {
  /** @type {HtmlString[]} */
  const strings = [];
  /** @param {unknown} location @param {string} text @param {string} where */
  const push = (location, text, where) => {
    const line = isFields(location) ? (numberAt(location, 'startLine') ?? 1) : 1;
    const column = isFields(location) ? (numberAt(location, 'startCol') ?? 1) : 1;
    strings.push({ text, line, column, where });
  };
  /** @param {Fields} node @param {boolean} hidden */
  const visit = (node, hidden) => {
    const location = isFields(node.sourceCodeLocation) ? node.sourceCodeLocation : undefined;
    const value = stringAt(node, 'value');
    if (node.nodeName === '#text') {
      if (!hidden && value !== undefined && value.trim() !== '') {
        push(location, value.trim(), 'text');
      }
      return;
    }
    const tag = stringAt(node, 'tagName') ?? '';
    const attributes = listAt(node, 'attrs');
    /** @param {string} name */
    const attribute = (name) =>
      stringAt(
        attributes.find((entry) => entry.name === name),
        'value',
      );
    const locations = isFields(location?.attrs) ? location.attrs : {};
    for (const entry of attributes) {
      const name = stringAt(entry, 'name') ?? '';
      const text = stringAt(entry, 'value') ?? '';
      const shown = showsText(
        tag,
        name,
        attribute('type')?.toLowerCase() ?? '',
        attribute('name') ?? attribute('property'),
        cssShown,
      );
      if (shown && text.trim() !== '') {
        push(locations[name] ?? location, text.trim(), `${name}="…" on <${tag}>`);
      }
    }
    if (tag === 'script' && attribute('type')?.toLowerCase() === 'application/ld+json') {
      const [child] = listAt(node, 'childNodes');
      const childLocation = isFields(child?.sourceCodeLocation)
        ? child.sourceCodeLocation
        : location;
      jsonLdStrings(stringAt(child, 'value') ?? '', (text, key) => {
        push(childLocation, text, `"${key}" in JSON-LD`);
      });
    }
    const childHidden = hidden || HIDDEN_ELEMENTS.has(tag);
    for (const child of listAt(node, 'childNodes')) visit(child, childHidden);
    if (isFields(node.content)) visit(node.content, childHidden);
  };
  if (isFields(tree)) visit(tree, false);
  return strings;
}

/**
 * Calls back with each text field of a JSON-LD block.
 * @param {string} json
 * @param {(text: string, key: string) => void} found
 */
function jsonLdStrings(json, found) {
  /** @type {unknown} */
  let data;
  try {
    data = JSON.parse(json);
  } catch {
    return;
  }
  /** @param {unknown} value */
  const visit = (value) => {
    if (Array.isArray(value)) {
      value.forEach(visit);
    } else if (isFields(value)) {
      for (const [key, inner] of Object.entries(value)) {
        if (typeof inner === 'string' && JSON_LD_TEXT.has(key)) found(inner, key);
        else visit(inner);
      }
    }
  };
  visit(data);
}

/**
 * The visible text of an HTML string: its text and text attributes.
 * @param {Parse5} html
 * @param {string} text
 * @param {ReadonlySet<string>} cssShown Attributes that CSS shows with `content: attr(…)`.
 * @returns {string[]}
 */
function htmlFragmentText(html, text, cssShown) {
  return htmlStrings(html.parseFragment(text), cssShown).map((found) => found.text);
}

/**
 * Inline scripts and CSS of an HTML page, with their offsets in it.
 * @param {unknown} tree
 * @returns {{ scripts: Array<{ text: string, offset: number }>, styles: Array<{ text: string, offset: number, where: string }> }}
 */
function htmlCode(tree) {
  /** @type {Array<{ text: string, offset: number }>} */
  const scripts = [];
  /** @type {Array<{ text: string, offset: number, where: string }>} */
  const styles = [];
  const scriptTypes = new Set(['', 'module', 'text/javascript', 'application/javascript']);
  /** @param {Fields} node */
  const visit = (node) => {
    const tag = stringAt(node, 'tagName') ?? '';
    const attributes = listAt(node, 'attrs');
    /** @param {string} name */
    const attribute = (name) =>
      stringAt(
        attributes.find((entry) => entry.name === name),
        'value',
      );
    const [child] = listAt(node, 'childNodes');
    const text = stringAt(child, 'value');
    const location = isFields(child?.sourceCodeLocation) ? child.sourceCodeLocation : undefined;
    const offset = numberAt(location, 'startOffset') ?? 0;
    if (tag === 'script' && attribute('src') === undefined && text !== undefined) {
      if (scriptTypes.has((attribute('type') ?? '').toLowerCase())) scripts.push({ text, offset });
    }
    if (tag === 'style' && text !== undefined)
      styles.push({ text, offset, where: 'CSS content in <style>' });
    const style = attribute('style');
    const own = isFields(node.sourceCodeLocation) ? node.sourceCodeLocation : undefined;
    const styleAt = isFields(own?.attrs) ? own.attrs.style : undefined;
    if (style !== undefined && isFields(styleAt)) {
      // The value starts after `style="`.
      const start = (numberAt(styleAt, 'startOffset') ?? 0) + 'style="'.length;
      styles.push({ text: style, offset: start, where: `style="…" on <${tag}>` });
    }
    for (const inner of listAt(node, 'childNodes')) visit(inner);
    if (isFields(node.content)) visit(node.content);
  };
  if (isFields(tree)) visit(tree);
  return { scripts, styles };
}

// index.html and manifests ---------------------------------------------------------------------

const PLACEHOLDER = /%copy\.[A-Za-z0-9_.]+%/gu;
const MANIFEST_FILE = /(?:\.webmanifest|(?:^|[/\\])manifest\.json)$/u;

/**
 * The value at a dotted path of the copy tree, or undefined.
 * @param {unknown} tree
 * @param {string} dotted
 * @returns {unknown}
 */
function lookup(tree, dotted) {
  /** @type {unknown} */
  let node = tree;
  for (const key of dotted.split('.')) {
    if (!isFields(node) || !Object.hasOwn(node, key)) return undefined;
    node = node[key];
  }
  return node;
}

/**
 * index.html: every visible string is a %copy.path% placeholder, every
 * placeholder names a string in copy.ts, the filled-in page passes the house
 * style, and no CSS `content` writes text.
 * @param {string} html
 * @param {unknown} copyTree
 * @param {string} file
 * @param {ReadonlySet<string>} [cssShown] Attributes the project's CSS shows with `content: attr(…)`.
 * @returns {Promise<Finding[]>}
 */
export async function scanIndexHtml(html, copyTree, file, cssShown = new Set()) {
  const { parse } = await loadParse5();
  /** @type {Finding[]} */
  const findings = [];
  const tree = parse(html, { sourceCodeLocationInfo: true });
  const { styles } = htmlCode(tree);
  const shownAttributes = new Set([
    ...cssShown,
    ...styles.flatMap((style) => cssAttributes(style.text)),
  ]);
  const raw = htmlStrings(tree, shownAttributes);
  let complete = true;
  for (const { text, line, column, where } of raw) {
    const literal = text.replace(PLACEHOLDER, '');
    if (!isSymbolsOnly(literal)) {
      findings.push({
        file,
        line,
        column,
        message: `literal text ${quote(literal)} in ${where}; fill it with %copy.path%`,
      });
    }
    for (const token of text.match(PLACEHOLDER) ?? []) {
      if (typeof lookup(copyTree, token.slice('%copy.'.length, -1)) !== 'string') {
        findings.push({
          file,
          line,
          column,
          message: `${token} in ${where} is not a string in copy.ts`,
        });
        complete = false;
      }
    }
  }
  const at = locator(html);
  for (const { text, offset, where } of styles) {
    for (const found of cssStrings(text)) {
      if (isSymbolsOnly(found.text)) continue;
      findings.push({
        file,
        ...at(offset + found.offset),
        message: `literal text ${quote(found.text)} in ${where}; take it from copy.ts`,
      });
    }
  }
  if (!complete) return findings;

  /** @type {string} */
  let rendered;
  try {
    rendered = renderHtmlCopy(html, copyTree);
  } catch (error) {
    findings.push({ file, line: 1, column: 1, message: describeError(error) });
    return findings;
  }
  // Filling placeholders never adds or removes a visible string, so the two lists line up.
  const shown = htmlStrings(parse(rendered, { sourceCodeLocationInfo: true }), shownAttributes);
  shown.forEach(({ text, line, column, where }, index) => {
    const origin = raw[index] ?? { line, column };
    for (const problem of problems(text)) {
      findings.push({
        file,
        line: origin.line,
        column: origin.column,
        message: `${problem} in ${where}: ${quote(text)}`,
      });
    }
  });
  return findings;
}

/**
 * The text fields of a web app manifest.
 * @param {unknown} manifest
 * @returns {Array<{ key: string, field: string, text: string }>}
 */
function manifestStrings(manifest) {
  /** @type {Array<{ key: string, field: string, text: string }>} */
  const strings = [];
  /** @param {Fields | undefined} object @param {string} prefix @param {string[]} keys */
  const take = (object, prefix, keys) => {
    for (const key of keys) {
      const text = stringAt(object, key);
      if (text !== undefined) strings.push({ key: `${prefix}${key}`, field: key, text });
    }
  };
  const root = isFields(manifest) ? manifest : undefined;
  take(root, '', ['name', 'short_name', 'description']);
  listAt(root, 'shortcuts').forEach((shortcut, i) => {
    take(shortcut, `shortcuts[${String(i)}].`, ['name', 'short_name', 'description']);
  });
  listAt(root, 'screenshots').forEach((screenshot, i) => {
    take(screenshot, `screenshots[${String(i)}].`, ['label']);
  });
  return strings;
}

/** Where each top-level manifest field comes from in copy.ts. */
const MANIFEST_COPY = new Map([
  ['name', 'manifest.name'],
  ['short_name', 'manifest.shortName'],
  ['description', 'manifest.description'],
]);

/**
 * A web app manifest file: its text is the text of copy.ts (copy.manifest for
 * its name, short name and description) and passes the house style.
 * @param {string} json
 * @param {string} file
 * @param {unknown} copyTree
 * @returns {Finding[]}
 */
export function scanManifest(json, file, copyTree) {
  /** @type {unknown} */
  let manifest;
  try {
    manifest = JSON.parse(json);
  } catch (error) {
    return [{ file, line: 1, column: 1, message: `not valid JSON: ${describeError(error)}` }];
  }
  const at = locator(json);
  const known = new Set(copyLeaves(copyTree).map(([, text]) => text));
  /** @type {Finding[]} */
  const findings = [];
  for (const { key, field, text } of manifestStrings(manifest)) {
    const offset = Math.max(0, json.indexOf(JSON.stringify(text)));
    /** @param {string} message */
    const report = (message) => findings.push({ file, ...at(offset), message });
    const dotted = key === field ? MANIFEST_COPY.get(field) : undefined;
    const expected = dotted === undefined ? undefined : lookup(copyTree, dotted);
    if (typeof expected === 'string') {
      if (text !== expected)
        report(`${key} ${quote(text)} is not copy.${dotted ?? ''} ${quote(expected)}`);
    } else if (!known.has(text)) {
      report(`${key} ${quote(text)} is not a string in copy.ts`);
    }
    for (const problem of problems(text)) report(`${problem} in ${key}: ${quote(text)}`);
  }
  return findings;
}

// The project ----------------------------------------------------------------------------------

/**
 * Every string leaf of a copy tree, keyed by its dotted path.
 * @param {unknown} node
 * @param {string} [prefix]
 * @returns {Array<[string, string]>}
 */
export function copyLeaves(node, prefix = 'copy') {
  if (typeof node === 'string') return [[prefix, node]];
  if (!isFields(node)) return [];
  return Object.entries(node).flatMap(([key, value]) => copyLeaves(value, `${prefix}.${key}`));
}

/**
 * Every file below `directory`, sorted, skipping node_modules and dot folders.
 * @param {string} directory
 * @returns {Promise<string[]>}
 */
async function filesBelow(directory) {
  if (!existsSync(directory)) return [];
  const entries = await readdir(directory, { withFileTypes: true });
  const nested = await Promise.all(
    entries.map(async (entry) => {
      const full = path.join(directory, entry.name);
      if (entry.isDirectory()) {
        return entry.name === 'node_modules' || entry.name.startsWith('.') ? [] : filesBelow(full);
      }
      return entry.isFile() ? [full] : [];
    }),
  );
  return nested.flat().sort();
}

/**
 * Script under src/ that runs in the page: not a test, a declaration, generated
 * types or the strings file itself.
 * @param {string} relative
 */
function isPageScript(relative) {
  return (
    /\.(?:ts|mts|js|mjs)$/u.test(relative) &&
    !/\.d\.[cm]?ts$/u.test(relative) &&
    !/\.(?:test|spec)\.[cm]?[jt]s$/u.test(relative) &&
    !/(?:^|\/)(?:tests?|__tests__|generated)\//u.test(relative) &&
    relative !== 'src/copy.ts'
  );
}

/**
 * Literal text in one component, read on its own (its imports are followed).
 * @param {string} source
 * @param {string} file Path relative to the web root.
 * @returns {Promise<Finding[]>}
 */
export async function scanSvelte(source, file) {
  return scanOne(source, file, 'svelte');
}

/**
 * Literal text one page script writes into the DOM, read on its own.
 * @param {string} source
 * @param {string} file Path relative to the web root.
 * @returns {Promise<Finding[]>}
 */
export async function scanScript(source, file) {
  return scanOne(source, file, 'script');
}

/**
 * @param {string} source
 * @param {string} file
 * @param {ModuleKind} kind
 */
async function scanOne(source, file, kind) {
  const project = await Project.create(WEB_ROOT);
  await project.loadCopy();
  const abs = path.resolve(WEB_ROOT, file);
  const module = project.scanEmbedded({ file, abs, kind, text: source, locate: locator(source) });
  project.byPath.set(abs, module);
  for (const css of componentCss(module.root)) {
    for (const attribute of cssAttributes(css)) project.cssAttributes.add(attribute);
  }
  const flow = new Flow(project);
  flow.index();
  return flow.check();
}

/**
 * @typedef {object} LintResult
 * @property {Finding[]} findings
 * @property {{ strings: number, svelte: number, scripts: number, styles: number, html: number, manifests: number }} scanned
 */

/**
 * Runs every check over one web project.
 * @param {{ root?: string, dist?: string | undefined }} [options]
 * @returns {Promise<LintResult>}
 */
export async function lintProject({ root: given = WEB_ROOT, dist } = {}) {
  const root = path.resolve(given);
  /** @type {Finding[]} */
  const findings = [];
  const scanned = { strings: 0, svelte: 0, scripts: 0, styles: 0, html: 0, manifests: 0 };
  /** @param {string} file */
  const relative = (file) => path.relative(root, file).split(path.sep).join('/');
  const project = await Project.create(root);

  // The strings themselves.
  /** @type {unknown} */
  let copyTree = {};
  if (existsSync(project.copyFile)) {
    await project.loadCopy();
    copyTree = project.copyRuntime?.exports.copy;
    for (const [key, text] of copyLeaves(copyTree)) {
      scanned.strings += 1;
      for (const problem of problems(text)) {
        findings.push({
          file: 'src/copy.ts',
          line: 1,
          column: 1,
          message: `${problem} in ${key}: ${quote(text)}`,
        });
      }
    }
  } else {
    findings.push({
      file: 'src/copy.ts',
      line: 1,
      column: 1,
      message: 'missing: every UI string lives in src/copy.ts',
    });
  }

  // Components, page scripts and styles under src/, read as one program.
  for (const file of await filesBelow(path.join(root, 'src'))) {
    const name = relative(file);
    if (name.endsWith('.svelte')) {
      scanned.svelte += 1;
      const module = project.scan(file, 'svelte');
      for (const css of componentCss(module.root)) {
        for (const attribute of cssAttributes(css)) project.cssAttributes.add(attribute);
      }
    } else if (isPageScript(name)) {
      scanned.scripts += 1;
      project.scan(file, 'script');
    } else if (name.endsWith('.css')) {
      scanned.styles += 1;
      const css = await readFile(file, 'utf8');
      for (const attribute of cssAttributes(css)) project.cssAttributes.add(attribute);
      const at = locator(css);
      for (const found of cssStrings(css)) {
        if (isSymbolsOnly(found.text)) continue;
        findings.push({
          file: name,
          ...at(found.offset),
          message: `literal text ${quote(found.text)} in CSS content; take it from copy.ts`,
        });
      }
    }
  }
  // A manifest built in the Vite config.
  const viteConfig = path.join(root, 'vite.config.ts');
  if (existsSync(viteConfig)) project.scan(viteConfig, 'script');

  // index.html: placeholders, filled-in text, CSS, and inline scripts read with src/.
  const indexFile = path.join(root, 'index.html');
  if (existsSync(indexFile)) {
    scanned.html += 1;
    const html = await readFile(indexFile, 'utf8');
    const { scripts, styles } = htmlCode(
      project.html.parse(html, { sourceCodeLocationInfo: true }),
    );
    // The page's own CSS styles every component too.
    for (const style of styles) {
      for (const attribute of cssAttributes(style.text)) project.cssAttributes.add(attribute);
    }
    findings.push(...(await scanIndexHtml(html, copyTree, 'index.html', project.cssAttributes)));
    const at = locator(html);
    for (const { text, offset } of scripts) {
      project.scanEmbedded({
        file: 'index.html',
        abs: indexFile,
        kind: 'script',
        text,
        locate: (inner) => at(offset + inner),
      });
    }
  }

  const flow = new Flow(project);
  flow.index();
  findings.push(...flow.check());

  /**
   * Manifests, and pages served as they are (public/404.html, the built site),
   * which are not filled from copy.ts but still follow the house style.
   * @param {string} directory
   */
  const servedAsIs = async (directory) => {
    for (const file of await filesBelow(directory)) {
      const name = relative(file);
      if (MANIFEST_FILE.test(file)) {
        scanned.manifests += 1;
        findings.push(...scanManifest(await readFile(file, 'utf8'), name, copyTree));
      } else if (file.endsWith('.html')) {
        scanned.html += 1;
        const tree = project.html.parse(await readFile(file, 'utf8'), {
          sourceCodeLocationInfo: true,
        });
        for (const { text, line, column, where } of htmlStrings(tree, project.cssAttributes)) {
          for (const problem of problems(text)) {
            findings.push({
              file: name,
              line,
              column,
              message: `${problem} in ${where}: ${quote(text)}`,
            });
          }
        }
      }
    }
  };
  await servedAsIs(path.join(root, 'public'));
  // The built site, when asked.
  if (dist !== undefined) await servedAsIs(path.resolve(root, dist));

  findings.sort((a, b) => a.file.localeCompare(b.file) || a.line - b.line || a.column - b.column);
  return { findings, scanned };
}

// Command line ---------------------------------------------------------------------------------

const USAGE = 'usage: check-copy.mjs [--root <web dir>] [--dist <build dir>] [--json]';

/** A mistake on the command line: reported as a message, without a stack. */
class UsageError extends Error {}

/**
 * @param {string[]} argv
 * @returns {Promise<number>} The exit code.
 */
async function main(argv) {
  /** @type {{ root?: string, dist?: string }} */
  const options = {};
  let json = false;
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--json') {
      json = true;
    } else if (arg === '--root' || arg === '--dist') {
      const value = argv[i + 1];
      if (value === undefined) throw new UsageError(`${arg} needs a directory; ${USAGE}`);
      options[arg === '--root' ? 'root' : 'dist'] = path.resolve(value);
      i += 1;
    } else {
      throw new UsageError(`unknown argument ${String(arg)}; ${USAGE}`);
    }
  }
  const { findings, scanned } = await lintProject(options);
  if (json) {
    process.stdout.write(`${JSON.stringify({ findings, scanned }, null, 2)}\n`);
    return findings.length === 0 ? 0 : 1;
  }
  for (const { file, line, column, message } of findings) {
    process.stdout.write(`${file}:${String(line)}:${String(column)}  ${message}\n`);
  }
  /** @param {number} n @param {string} one @param {string} other */
  const counted = (n, one, other) => `${String(n)} ${n === 1 ? one : other}`;
  const what = [
    counted(scanned.strings, 'string', 'strings'),
    counted(scanned.svelte, 'component', 'components'),
    counted(scanned.scripts, 'script', 'scripts'),
    counted(scanned.styles, 'stylesheet', 'stylesheets'),
    counted(scanned.html, 'HTML file', 'HTML files'),
    counted(scanned.manifests, 'manifest', 'manifests'),
  ].join(', ');
  const files = new Set(findings.map((finding) => finding.file)).size;
  process.stdout.write(
    findings.length === 0
      ? `check-copy: clean (${what}).\n`
      : `check-copy: ${counted(findings.length, 'problem', 'problems')} in ${counted(files, 'file', 'files')} (${what}).\n`,
  );
  return findings.length === 0 ? 0 : 1;
}

const invoked = process.argv[1];
if (invoked !== undefined && import.meta.url === pathToFileURL(path.resolve(invoked)).href) {
  main(process.argv.slice(2)).then(
    (code) => {
      process.exitCode = code;
    },
    /** @param {unknown} error */
    (error) => {
      const detail =
        error instanceof UsageError
          ? error.message
          : error instanceof Error
            ? (error.stack ?? error.message)
            : String(error);
      process.stderr.write(`check-copy: ${detail}\n`);
      process.exitCode = 2;
    },
  );
}
