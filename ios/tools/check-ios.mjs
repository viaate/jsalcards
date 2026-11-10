// check-ios.mjs: the guards of the iPhone app. One script; it ends with status 1 on any hit.
//
//   node ios/tools/check-ios.mjs
//
// What it keeps out, under ios/ and in .github/workflows/ios-*.yml:
//
//   (a) signing material, secrets and billed machines;
//   (b) words: any way for a view to draw text that did not come from its screen model;
//   (c) impurity in SnowlightCore: the device's clock or zone, a formatter, a pattern
//       engine, a crash path, any import but Foundation;
//   (d) golden families that no test reads, and tests that name a family that is not there;
//   (e) debug code that a release build would hold: the picture tour's folder is outside
//       the words rules, so every line of code in it must sit inside `#if DEBUG`.
//
// It reads code, not comments. It skips itself and ios/README.md: both must be able to
// name what is banned.
//
// It tests itself first, on every run: a list of small samples, at least one per rule,
// each of which must be refused by the rule it is listed under. A sample that passes is
// itself a failure, and so is a clean sample that is refused.
//
// Node's built-in modules only: it needs no `npm ci`. It imports the site's list of
// banned words from web/scripts/check-copy.mjs, which needs Node 22.18 or newer.

import { spawnSync } from 'node:child_process';
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = join(HERE, '..', '..');

// Where things are -------------------------------------------------------------------------

const SELF = 'ios/tools/check-ios.mjs';
const README = 'ios/README.md';
const KIT = 'ios/SnowlightKit/Sources/';
const APP = 'ios/App/';
const CORE = 'ios/SnowlightCore/Sources/';
const CORE_WORDS = 'ios/SnowlightCore/Sources/SnowlightCore/Words/';
const CORE_SCREENS = 'ios/SnowlightCore/Sources/SnowlightCore/Screens/';
const CORE_TESTS = 'ios/SnowlightCore/Tests/';
const TEST_FILES = 'ios/SnowlightCore/Tests/SnowlightCoreTests/';
const GOLDEN = 'ios/SnowlightCore/Tests/SnowlightCoreTests/Fixtures/golden/';
const SHOWN = 'ios/SnowlightKit/Sources/SnowlightKit/Shell/Shown.swift';
const NAMES = 'ios/SnowlightKit/Sources/SnowlightKit/Shell/Names.swift';
const APP_WORDS_SWIFT = 'ios/SnowlightCore/Sources/SnowlightCore/Words/AppWords.swift';
const APP_WORDS_LIST = 'ios/tools/app-words.txt';
const LOCAL_CONFIG = 'ios/Local.xcconfig';
const THIS_MACHINE = 'ThisMachineTests.swift';
const WORKFLOWS = '.github/workflows/';

/** Folders the build leaves behind, which are never committed (ios/.gitignore). */
const BUILD_FOLDERS = new Set(['Snowlight.xcodeproj', 'out', '.build', 'DerivedData', '.swiftpm', 'node_modules']);

const RUNNERS = ['ubuntu-24.04', 'macos-26', 'xcode-27'];
const ACTIONS = ['actions/checkout@v7', 'actions/setup-node@v7', 'actions/upload-artifact@v7'];
const SIGNING_ENDINGS = ['.p8', '.p12', '.cer', '.mobileprovision', '.pem'];
const LANGUAGE_ENDINGS = ['.strings', '.stringsdict', '.xcstrings'];
const TEXT_ENDINGS = ['.swift', '.mjs', '.js', '.sh', '.yml', '.yaml', '.txt', '.md', '.json', '.xcconfig', '.plist', '.gitignore', '.command'];
const NAME_LITERAL = /^[a-z0-9.]+$/;

function isIosWorkflow(path) {
  return path.startsWith(`${WORKFLOWS}ios-`) && (path.endsWith('.yml') || path.endsWith('.yaml'));
}

function isViewCode(path) {
  return path.endsWith('.swift') && (path.startsWith(KIT) || path.startsWith(APP)) && !path.includes('/Tour/');
}

/** The debug tour: the one part of the kit and the app that the words rules leave alone. */
function isTourCode(path) {
  return path.endsWith('.swift') && (path.startsWith(KIT) || path.startsWith(APP)) && path.includes('/Tour/');
}

/**
 * (e) The first line of code in a tour file that a release build would hold, or null when
 * there is none. Every line of code must sit inside one `#if DEBUG` block that stands at
 * the top of the file's nesting and has no `#else` or `#elseif` of its own. An import
 * counts as code: a release build must not even link what the tour uses.
 * @param {string} code Swift source with comments and the contents of strings blanked.
 * @returns {{ line: number, what: string } | null}
 */
function outsideDebug(code) {
  const lines = code.split('\n');
  let depth = 0;
  let inDebug = false;
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index].trim();
    const number = index + 1;
    if (line === '') continue;
    if (/^#if(?![A-Za-z0-9_])/.test(line)) {
      if (depth === 0) {
        if (!/^#if\s+DEBUG$/.test(line)) return { line: number, what: `'${line}' is not '#if DEBUG'` };
        inDebug = true;
      }
      depth += 1;
      continue;
    }
    if (/^#endif(?![A-Za-z0-9_])/.test(line)) {
      if (depth === 0) return { line: number, what: "an '#endif' that closes nothing" };
      depth -= 1;
      if (depth === 0) inDebug = false;
      continue;
    }
    if (/^#else(?:if)?(?![A-Za-z0-9_])/.test(line)) {
      if (depth <= 1) return { line: number, what: `'${line}' gives the debug block a branch that a release build would hold` };
      continue;
    }
    if (!inDebug) return { line: number, what: 'code outside #if DEBUG' };
  }
  if (depth !== 0) return { line: lines.length, what: "an '#if' that is never closed" };
  return null;
}

// Reading Swift ----------------------------------------------------------------------------

/**
 * Splits Swift source into what is code and what is not.
 *
 * `code` is the source with every comment blanked and the contents of every string
 * literal blanked (the quotes stay), so a rule that looks for a name never finds it in a
 * comment or inside a string. Code inside a string's interpolation stays code.
 * `uncommented` is the source with only the comments blanked.
 * `literals` lists every string literal: its line, its text, and whether it interpolates.
 * Both texts keep every line break, so a position gives the same line in all three.
 * @param {string} text
 */
function readSwift(text) {
  const code = text.split('');
  const uncommented = text.split('');
  /** @type {Array<{ line: number, value: string, interpolated: boolean }>} */
  const literals = [];
  const size = text.length;
  let at = 0;
  let line = 1;

  const blank = (target, index) => {
    if (target[index] !== '\n') target[index] = ' ';
  };
  const step = () => {
    if (text[at] === '\n') line += 1;
    at += 1;
  };

  /** Skips a comment that starts at `at`; true if there was one. */
  function comment() {
    if (text[at] === '/' && text[at + 1] === '/') {
      while (at < size && text[at] !== '\n') {
        blank(code, at);
        blank(uncommented, at);
        at += 1;
      }
      return true;
    }
    if (text[at] === '/' && text[at + 1] === '*') {
      let depth = 0;
      while (at < size) {
        if (text[at] === '/' && text[at + 1] === '*') {
          depth += 1;
          blank(code, at);
          blank(uncommented, at);
          blank(code, at + 1);
          blank(uncommented, at + 1);
          at += 2;
          continue;
        }
        if (text[at] === '*' && text[at + 1] === '/') {
          depth -= 1;
          blank(code, at);
          blank(uncommented, at);
          blank(code, at + 1);
          blank(uncommented, at + 1);
          at += 2;
          if (depth === 0) break;
          continue;
        }
        blank(code, at);
        blank(uncommented, at);
        step();
      }
      return true;
    }
    return false;
  }

  /** How a string starts at `at`, or null: the number of # before it and of quotes. */
  function stringStart() {
    let pounds = 0;
    while (text[at + pounds] === '#') pounds += 1;
    if (text[at + pounds] !== '"') return null;
    const triple = text[at + pounds + 1] === '"' && text[at + pounds + 2] === '"';
    return { pounds, quotes: triple ? 3 : 1 };
  }

  /** Reads one string literal that starts at `at`. */
  function string(start) {
    const literal = { line, value: '', interpolated: false };
    literals.push(literal);
    at += start.pounds + start.quotes;
    const closes = () => {
      for (let k = 0; k < start.quotes; k += 1) if (text[at + k] !== '"') return false;
      for (let k = 0; k < start.pounds; k += 1) if (text[at + start.quotes + k] !== '#') return false;
      return true;
    };
    while (at < size) {
      if (closes()) {
        at += start.quotes + start.pounds;
        return;
      }
      if (text[at] === '\\') {
        let k = 1;
        while (k <= start.pounds && text[at + k] === '#') k += 1;
        if (k === start.pounds + 1) {
          // An escape. An opening parenthesis after it starts an interpolation: code.
          if (text[at + k] === '(') {
            literal.interpolated = true;
            for (let j = 0; j <= k; j += 1) blank(code, at + j);
            at += k + 1;
            codeUntilClose();
            continue;
          }
          for (let j = 0; j <= k; j += 1) {
            literal.value += text[at + j] ?? '';
            blank(code, at + j);
          }
          at += k;
          step();
          continue;
        }
      }
      if (text[at] === '\n' && start.quotes === 1) return; // an unfinished string ends with its line
      literal.value += text[at];
      blank(code, at);
      step();
    }
  }

  /** Reads code inside an interpolation, up to and past its closing parenthesis. */
  function codeUntilClose() {
    let depth = 1;
    while (at < size) {
      if (comment()) continue;
      const start = stringStart();
      if (start !== null) {
        string(start);
        continue;
      }
      if (text[at] === '(') depth += 1;
      if (text[at] === ')') {
        depth -= 1;
        if (depth === 0) {
          blank(code, at);
          at += 1;
          return;
        }
      }
      step();
    }
  }

  while (at < size) {
    if (comment()) continue;
    const start = stringStart();
    if (start !== null) {
      string(start);
      continue;
    }
    step();
  }
  return { code: code.join(''), uncommented: uncommented.join(''), literals };
}

/** The line of a position in a text. */
function lineAt(text, index) {
  let line = 1;
  for (let k = 0; k < index; k += 1) if (text[k] === '\n') line += 1;
  return line;
}

/** Every match of a pattern in a text, with its line. */
function matches(text, pattern) {
  const flags = pattern.flags.includes('g') ? pattern.flags : `${pattern.flags}g`;
  const found = [];
  for (const match of text.matchAll(new RegExp(pattern.source, flags))) {
    found.push({ line: lineAt(text, match.index), text: match[0], match });
  }
  return found;
}

/**
 * A text file's values without its comments: a `#` or a `//` that starts a line or
 * follows a space starts a comment, to the end of the line. Swift is read properly.
 */
function withoutComments(path, text) {
  if (path.endsWith('.swift')) return readSwift(text).uncommented;
  const hash = /\.(ya?ml|sh|txt|command|gitignore)$/.test(path);
  const slashes = /\.(mjs|js|xcconfig)$/.test(path);
  return text
    .split('\n')
    .map((line) => {
      let kept = line;
      if (hash) kept = kept.replace(/(^|\s)#.*$/, '$1');
      if (slashes) kept = kept.replace(/(^|\s)\/\/.*$/, '$1');
      return kept;
    })
    .join('\n');
}

// The rules ------------------------------------------------------------------------------

/** Names a view may not use, each with what it is. (b) */
const VIEW_SYSTEM_WORDS = [
  [/\.formatted\s*\(/, 'a system formatter (.formatted)'],
  [/(?<![A-Za-z0-9_])[A-Za-z0-9_]*Formatter(?![A-Za-z0-9_])/, 'a system formatter'],
  [/(?<![A-Za-z0-9_])[A-Za-z0-9_]*FormatStyle(?![A-Za-z0-9_])/, 'a system format style'],
  [/(?<![A-Za-z0-9_])String\s*(?:\(|\.init(?![A-Za-z0-9_]))/, 'String( turns a value into words'],
  [/(?<![A-Za-z0-9_])LocalizedStringKey(?![A-Za-z0-9_])/, 'a localized string'],
  [/(?<![A-Za-z0-9_])LocalizedStringResource(?![A-Za-z0-9_])/, 'a localized string'],
  [/(?<![A-Za-z0-9_])NSLocalizedString(?![A-Za-z0-9_])/, 'a localized string'],
  [/(?<![A-Za-z0-9_])AttributedString\s*\(/, 'an attributed string'],
  [/(?<![A-Za-z0-9_])DatePicker(?![A-Za-z0-9_])/, 'a control iOS words for us'],
  [/(?<![A-Za-z0-9_])Date\s*\(\s*\)/, "a read of the device's clock"],
  [/(?<![A-Za-z0-9_])Date\s*\.\s*now(?![A-Za-z0-9_])/, "a read of the device's clock"],
];

/** Other ways to turn a value into words. (b) */
const VIEW_VALUE_WORDS = [
  [/\.\s*description(?![A-Za-z0-9_])/, '.description'],
  [/\.\s*debugDescription(?![A-Za-z0-9_])/, '.debugDescription'],
  [/\.\s*localizedDescription(?![A-Za-z0-9_])/, '.localizedDescription'],
  [/\.\s*rawValue(?![A-Za-z0-9_])/, '.rawValue'],
];

const WORD_TABLES = /(?<![A-Za-z0-9_])(SiteWords|SiteFormat|AppWords|DetailsWords|SeasonWords)(?![A-Za-z0-9_])/;
const TEXT_MAKER = /(?<![A-Za-z0-9_])Text\s*(?:\(|\.\s*init(?![A-Za-z0-9_]))/;
const TEXT_VERBATIM = /^Text\(\s*verbatim\s*:/;
const DRAWN = /(?<![A-Za-z0-9_])drawnString(?![A-Za-z0-9_])/;
const SHOWN_MAKER = /(?<![A-Za-z0-9_])ShownText\s*(?:\(|\.\s*init(?![A-Za-z0-9_]))/;

/** The device's clock or zone. (c) */
const CORE_DEVICE = [
  [/(?<![A-Za-z0-9_])Date\s*\(\s*\)/, 'Date()'],
  [/(?<![A-Za-z0-9_])Date\s*\.\s*now(?![A-Za-z0-9_])/, 'Date.now'],
  [/(?<![A-Za-z0-9_])timeIntervalSinceNow(?![A-Za-z0-9_])/, 'timeIntervalSinceNow'],
  [/\.\s*current(?![A-Za-z0-9_])/, '.current'],
  [/(?<![A-Za-z0-9_])(?:let|var|func|case)\s+current(?![A-Za-z0-9_])/, 'something of our own named current'],
  [/(?<![A-Za-z0-9_])autoupdatingCurrent(?![A-Za-z0-9_])/, 'autoupdatingCurrent'],
  [/(?<![A-Za-z0-9_])ProcessInfo(?![A-Za-z0-9_])/, 'ProcessInfo'],
  [/(?<![A-Za-z0-9_])Calendar(?![A-Za-z0-9_])/, 'Calendar'],
];

/** A formatter. (c) */
const CORE_FORMATTER = [
  [/(?<![A-Za-z0-9_])[A-Za-z0-9_]*Formatter(?![A-Za-z0-9_])/, 'a formatter'],
  [/(?<![A-Za-z0-9_])[A-Za-z0-9_]*FormatStyle(?![A-Za-z0-9_])/, 'a format style'],
  [/\.formatted\s*\(/, '.formatted('],
];

/** A pattern engine, or a character test that reaches beyond ASCII. (c) */
const CORE_PATTERN = [
  'NSRegularExpression',
  'Regex',
  'regularExpression',
  'wholeMatch',
  'firstMatch',
  'prefixMatch',
  'CharacterSet',
  'whitespacesAndNewlines',
  'trimmingCharacters',
  'isWhitespace',
  'isNumber',
  'isLetter',
  'wholeNumberValue',
].map((name) => [new RegExp(`(?<![A-Za-z0-9_])${name}(?![A-Za-z0-9_])`), name]);
CORE_PATTERN.push([/\.\s*whitespaces(?![A-Za-z0-9_])/, '.whitespaces']);

/** A crash path. (c) */
const CORE_CRASH = [
  [/(?<![A-Za-z0-9_])try!/, 'try!'],
  [/(?<![A-Za-z0-9_])as!/, 'as!'],
  [/(?<![A-Za-z0-9_])fatalError\s*\(/, 'fatalError('],
  [/(?<![A-Za-z0-9_])preconditionFailure\s*\(/, 'preconditionFailure('],
  [/(?<![A-Za-z0-9_])assertionFailure\s*\(/, 'assertionFailure('],
  // A value followed at once by `!`: a forced unwrap, or a type that unwraps itself.
  [/[A-Za-z0-9_)\]?>]!(?!=)/, 'a forced unwrap'],
];

const EMOJI = /\p{Extended_Pictographic}|\p{Regional_Indicator}/u;
const EM_DASH = /[\u2014\u2015\u2E3A\u2E3B]|--/u;
const EXCLAMATION = /[!\u00A1\u203C\u2049]/u;

/**
 * Checks a tree of files. `files` maps a repository path to the file's text; a file
 * that is not text maps to null. `banned` is the site's list of banned words.
 * @param {Map<string, string | null>} files
 * @param {ReadonlyArray<readonly [string, string]>} banned
 * @returns {Array<{ rule: string, path: string, line: number, what: string }>}
 */
function checkTree(files, banned) {
  /** @type {Array<{ rule: string, path: string, line: number, what: string }>} */
  const hits = [];
  const hit = (rule, path, line, what) => hits.push({ rule, path, line, what });

  for (const [path, text] of files) {
    const underIos = path.startsWith('ios/');
    const workflow = isIosWorkflow(path);
    if (!underIos && !workflow) continue;

    // (a) Signing files, and the one config file that lives only on the borrowed Mac.
    if (SIGNING_ENDINGS.some((ending) => path.toLowerCase().endsWith(ending))) {
      hit('signing.file', path, 0, 'a certificate, key or profile file');
    }
    if (path === LOCAL_CONFIG) hit('signing.file', path, 0, 'Local.xcconfig is never committed');

    // (b) The app is English only: no language files.
    if (underIos && path.split('/').some((part) => part.endsWith('.lproj'))) {
      hit('language.file', path, 0, 'a .lproj folder');
    }
    if (underIos && LANGUAGE_ENDINGS.some((ending) => path.endsWith(ending))) {
      hit('language.file', path, 0, 'a strings file');
    }

    if (text === null || path === SELF || path === README) continue;
    const values = withoutComments(path, text);

    // (a) Signing settings and secrets, in every text file.
    for (const found of matches(values, /PROVISIONING_PROFILE/)) {
      hit('signing.profile', path, found.line, 'PROVISIONING_PROFILE');
    }
    for (const found of matches(values, /CODE_SIGN_IDENTITY(?:\[[^\]\n]*\])?[ \t]*[=:][ \t]*([^\n]*)/)) {
      const value = found.match[1].trim().replace(/[\\,;]+$/, '').trim().replace(/^(["'])(.*)\1$/, '$2');
      const first = value.split(/\s+/)[0].replace(/^(["'])(.*)\1$/, '$2');
      if (first !== '-') hit('signing.identity', path, found.line, `CODE_SIGN_IDENTITY is given '${value}', not '-'`);
    }
    for (const found of matches(values, /DEVELOPMENT_TEAM[ \t]*[=:][ \t]*["']?[A-Za-z0-9]{10}(?![A-Za-z0-9_])/)) {
      hit('signing.team', path, found.line, 'DEVELOPMENT_TEAM is given a team value');
    }

    if (workflow) checkWorkflow(path, values, hit);
    if (!path.endsWith('.swift')) continue;

    const swift = readSwift(text);

    if (isViewCode(path)) {
      // (b) No text in quotes in a view; in the names file, names only.
      for (const literal of swift.literals) {
        if (path !== NAMES) {
          hit('words.literal', path, literal.line, `a string literal in a view: "${literal.value}"`);
        } else if (literal.interpolated || !NAME_LITERAL.test(literal.value)) {
          hit('words.names', path, literal.line, `"${literal.value}" is not a plain name (a-z, 0-9 and dots)`);
        }
      }
      // (b) Text is made in one file, and there only from a ShownText's characters.
      for (const found of matches(swift.code, TEXT_MAKER)) {
        const rest = swift.code.slice(found.match.index).replace(/\s+/g, '');
        if (path !== SHOWN) hit('words.text', path, found.line, 'Text( outside Shell/Shown.swift');
        else if (!TEXT_VERBATIM.test(rest)) hit('words.text', path, found.line, 'Text( that is not Text(verbatim:');
      }
      for (const found of matches(swift.code, WORD_TABLES)) {
        hit('words.table', path, found.line, `a view names the word table ${found.text}`);
      }
      if (path !== SHOWN) {
        for (const found of matches(swift.code, DRAWN)) {
          hit('words.drawn', path, found.line, 'drawnString outside Shell/Shown.swift');
        }
      }
      for (const [pattern, what] of VIEW_SYSTEM_WORDS) {
        for (const found of matches(swift.code, pattern)) hit('words.system', path, found.line, `${what}: ${found.text}`);
      }
      for (const [pattern, what] of VIEW_VALUE_WORDS) {
        for (const found of matches(swift.code, pattern)) hit('words.value', path, found.line, `${what} turns a value into words`);
      }
    }

    if (isTourCode(path)) {
      // (e) The tour is outside the words rules, so none of it may reach a release build.
      const outside = outsideDebug(swift.code);
      if (outside !== null) hit('tour.debug', path, outside.line, `the debug tour must be wholly inside #if DEBUG: ${outside.what}`);
    }

    if (path.startsWith(CORE)) {
      // (b) Only Words/ makes a ShownText; a screen model types no word.
      if (!path.startsWith(CORE_WORDS)) {
        for (const found of matches(swift.code, SHOWN_MAKER)) {
          hit('core.showntext', path, found.line, 'ShownText( outside Words/');
        }
      }
      if (path.startsWith(CORE_SCREENS)) {
        for (const literal of swift.literals) {
          hit('core.screenliteral', path, literal.line, `a string literal in a screen model: "${literal.value}"`);
        }
      }
      // (c) Purity.
      for (const found of matches(swift.code, /^[ \t]*(?:@[A-Za-z_]+[ \t]+)*import[ \t]+([^\n]*)$/m)) {
        const module = found.match[1].trim();
        if (module !== 'Foundation') hit('core.import', path, found.line, `import ${module}`);
      }
      for (const [pattern, what] of CORE_DEVICE) {
        for (const found of matches(swift.code, pattern)) hit('core.device', path, found.line, `the device's clock or zone: ${what}`);
      }
      for (const [pattern, what] of CORE_FORMATTER) {
        for (const found of matches(swift.code, pattern)) hit('core.formatter', path, found.line, `${what}: ${found.text}`);
      }
      for (const [pattern, what] of CORE_PATTERN) {
        for (const found of matches(swift.code, pattern)) hit('core.pattern', path, found.line, `a pattern engine or a Unicode-wide test: ${what}`);
      }
      for (const [pattern, what] of CORE_CRASH) {
        for (const found of matches(swift.code, pattern)) hit('core.crash', path, found.line, `a crash path: ${what}`);
      }
    }

    // (c) In the tests, one file may read this machine's zone and its environment.
    if (path.startsWith(CORE_TESTS) && !path.endsWith(`/${THIS_MACHINE}`)) {
      for (const found of matches(swift.code, /\.\s*current(?![A-Za-z0-9_])/)) {
        hit('tests.device', path, found.line, `.current outside ${THIS_MACHINE}`);
      }
      for (const found of matches(swift.code, /(?<![A-Za-z0-9_])ProcessInfo(?![A-Za-z0-9_])/)) {
        hit('tests.device', path, found.line, `ProcessInfo outside ${THIS_MACHINE}`);
      }
    }
  }

  checkAppWords(files, banned, hit);
  checkFamilies(files, hit);
  return hits;
}

/** (a) An iOS workflow: no secrets, standard runners only, GitHub's own three actions only. */
function checkWorkflow(path, values, hit) {
  for (const found of matches(values, /(?<![A-Za-z0-9_])secrets[ \t]*[.[:]/)) {
    hit('workflow.secrets', path, found.line, 'a workflow reads a secret');
  }
  const lines = values.split('\n');
  const plain = (value) => value.trim().replace(/^(["'])(.*)\1$/, '$2');
  let permissions = null;
  lines.forEach((line, index) => {
    const number = index + 1;
    const runner = /^\s*(?:-\s+)?runs-on\s*:(.*)$/.exec(line);
    if (runner !== null && !RUNNERS.includes(plain(runner[1]))) {
      hit('runner.label', path, number, `runs-on '${plain(runner[1])}' is not one of ${RUNNERS.join(', ')}`);
    }
    const action = /^\s*(?:-\s+)?uses\s*:(.*)$/.exec(line);
    if (action !== null && !ACTIONS.includes(plain(action[1]))) {
      hit('workflow.uses', path, number, `uses '${plain(action[1])}' is not one of ${ACTIONS.join(', ')}`);
    }
    if (/^\s+permissions\s*:/.test(line)) {
      hit('workflow.permissions', path, number, 'a job sets permissions of its own');
    }
    const top = /^permissions\s*:(.*)$/.exec(line);
    if (top !== null) {
      permissions = { number, inline: top[1].trim(), block: [] };
      for (let k = index + 1; k < lines.length && /^(\s|$)/.test(lines[k]); k += 1) {
        if (lines[k].trim() !== '') permissions.block.push(lines[k].trim());
      }
    }
  });
  if (permissions === null) {
    hit('workflow.permissions', path, 0, 'no top-level permissions; it must be contents: read');
  } else if (permissions.inline !== '' || permissions.block.length !== 1 || permissions.block[0] !== 'contents: read') {
    hit('workflow.permissions', path, permissions.number, 'permissions must be exactly contents: read');
  }
}

/**
 * (b) The words only the app has: the literals of AppWords.swift are exactly the lines of
 * app-words.txt, each marked approved or pending with where that was said, and none uses
 * a word the site bans, an exclamation mark, an em dash or an emoji.
 */
function checkAppWords(files, banned, hit) {
  const swift = files.get(APP_WORDS_SWIFT);
  const list = files.get(APP_WORDS_LIST);
  if (swift === undefined && list === undefined) return;
  if (typeof swift !== 'string') {
    hit('appwords.list', APP_WORDS_SWIFT, 0, 'the list of app words exists and AppWords.swift does not');
    return;
  }
  if (typeof list !== 'string') {
    hit('appwords.list', APP_WORDS_LIST, 0, 'AppWords.swift exists and its list does not');
    return;
  }

  /** @type {Array<{ line: number, words: string }>} */
  const listed = [];
  list.split('\n').forEach((raw, index) => {
    if (raw.trim() === '' || raw.startsWith('#')) return;
    const parts = raw.split('\t');
    if (parts.length !== 3 || !['approved', 'pending'].includes(parts[0]) || parts[1].trim() === '' || parts[2] === '') {
      hit('appwords.format', APP_WORDS_LIST, index + 1, 'a line must be: approved or pending, a tab, who or where, a tab, the words');
      return;
    }
    listed.push({ line: index + 1, words: parts[2] });
  });

  const typed = readSwift(swift).literals;
  for (const literal of typed) {
    if (literal.interpolated || literal.value.includes('\\')) {
      hit('appwords.list', APP_WORDS_SWIFT, literal.line, `"${literal.value}" must be plain text, with no escape and nothing put in`);
    }
  }
  const count = (items) => {
    const counts = new Map();
    for (const item of items) counts.set(item, (counts.get(item) ?? 0) + 1);
    return counts;
  };
  const typedCounts = count(typed.map((literal) => literal.value));
  const listedCounts = count(listed.map((entry) => entry.words));
  for (const literal of typed) {
    if ((listedCounts.get(literal.value) ?? 0) !== typedCounts.get(literal.value)) {
      hit('appwords.list', APP_WORDS_SWIFT, literal.line, `"${literal.value}" is not in ${APP_WORDS_LIST} the same number of times`);
    }
  }
  for (const entry of listed) {
    if (!typedCounts.has(entry.words)) {
      hit('appwords.list', APP_WORDS_LIST, entry.line, `"${entry.words}" is listed and is not in AppWords.swift`);
    }
  }

  const words = new Map();
  for (const literal of typed) words.set(literal.value, { path: APP_WORDS_SWIFT, line: literal.line });
  for (const entry of listed) if (!words.has(entry.words)) words.set(entry.words, { path: APP_WORDS_LIST, line: entry.line });
  for (const [text, where] of words) {
    for (const [label, pattern] of banned) {
      // The site's own rule: whole words, any case (web/scripts/check-copy.mjs).
      if (new RegExp(`(?<![\\p{L}\\p{N}_])(?:${pattern})(?![\\p{L}\\p{N}_])`, 'iu').test(text)) {
        hit('appwords.banned', where.path, where.line, `"${text}" uses the banned word "${label}"`);
      }
    }
    if (EXCLAMATION.test(text)) hit('appwords.style', where.path, where.line, `"${text}" has an exclamation mark`);
    if (EM_DASH.test(text)) hit('appwords.style', where.path, where.line, `"${text}" has an em dash`);
    if (EMOJI.test(text)) hit('appwords.style', where.path, where.line, `"${text}" has an emoji`);
  }
}

/**
 * (d) Every golden family is named by a test, and every family a test names exists. A
 * test names its family as GoldenFile.family("<name>"). A static check: test order
 * differs between Linux and macOS, so this cannot be checked while the tests run.
 */
function checkFamilies(files, hit) {
  const families = new Set();
  for (const path of files.keys()) {
    if (path.startsWith(GOLDEN) && path.endsWith('.json')) families.add(path.slice(GOLDEN.length, -'.json'.length));
  }
  /** @type {Map<string, { path: string, line: number }>} */
  const named = new Map();
  for (const [path, text] of files) {
    if (!path.startsWith(TEST_FILES) || !path.endsWith('.swift') || typeof text !== 'string') continue;
    const source = readSwift(text).uncommented;
    for (const found of matches(source, /GoldenFile\s*\.\s*family\s*\(\s*"([^"\\\n]*)"\s*\)/)) {
      if (!named.has(found.match[1])) named.set(found.match[1], { path, line: found.line });
    }
  }
  for (const family of [...families].sort()) {
    if (!named.has(family)) hit('families.unnamed', `${GOLDEN}${family}.json`, 0, `no test names the golden family '${family}'`);
  }
  for (const [family, where] of named) {
    if (!families.has(family)) hit('families.missing', where.path, where.line, `a test names the golden family '${family}', and there is no such file`);
  }
}

// The self-test ----------------------------------------------------------------------------

const VIEW = 'ios/SnowlightKit/Sources/SnowlightKit/Shell/Sample.swift';
const TOUR = 'ios/SnowlightKit/Sources/SnowlightKit/Tour/Sample.swift';
const CORE_FILE = 'ios/SnowlightCore/Sources/SnowlightCore/Days/Sample.swift';
const SCREEN_FILE = 'ios/SnowlightCore/Sources/SnowlightCore/Screens/Sample.swift';
const TEST_FILE = 'ios/SnowlightCore/Tests/SnowlightCoreTests/SampleTests.swift';
const WORKFLOW = '.github/workflows/ios-sample.yml';
const PROJECT = 'ios/project.yml';
/** Ten characters shaped like a team value, made here so that none is ever written down. */
const TEAM_SHAPE = 'X'.repeat(10);

const view = (body) => `import SwiftUI\nstruct Sample: View {\n    var body: some View {\n        ${body}\n    }\n}\n`;
const core = (body) => `import Foundation\nfunc sample() {\n    ${body}\n}\n`;
const workflow = (changes = {}) =>
  [
    'name: sample',
    'on: push',
    changes.permissions ?? 'permissions:\n  contents: read',
    'jobs:',
    '  one:',
    `    runs-on: ${changes.runner ?? 'macos-26'}`,
    '    steps:',
    `      - uses: ${changes.uses ?? 'actions/checkout@v7'}`,
    `      - run: ${changes.run ?? 'echo ok'}`,
    '',
  ].join('\n');
const appWords = (...words) => `enum AppWords {\n${words.map((word, index) => `    static let w${index} = ShownText("${word}")`).join('\n')}\n}\n`;
const appList = (...words) => `# the list\n${words.map((word) => `approved\towner\t${word}`).join('\n')}\n`;

/** A tree that every rule must pass: the allowed forms, side by side. */
const CLEAN = new Map([
  [SHOWN, 'import SwiftUI\nextension ShownText {\n    var text: Text { Text(verbatim: drawnString) }\n}\n'],
  [NAMES, 'import SwiftUI\nstruct SymbolName {\n    fileprivate let name: String\n    static let map = SymbolName(name: "map")\n    static let done = SymbolName(name: "checkmark.square")\n}\n'],
  // A comment may name what is banned; so may the debug tour, which no release build holds.
  [VIEW, view('ShownLabel(model.title) // never Text("x"), never Date() or String(x)')],
  [TOUR, '// The tour.\n#if DEBUG\nimport MetalKit\nlet key = "tour.name"\nlet said = String(describing: 3) + "Text(\\"x\\")"\n#if targetEnvironment(simulator)\nlet where = "#endif is only named in this string"\n#else\nlet where = "a phone"\n#endif\n#endif // DEBUG\n'],
  [CORE_FILE, core('let note = "Date() and Calendar.current are only named in this string"\n    if 3 != 4 { _ = note }')],
  [SCREEN_FILE, 'struct Sample {\n    let title: ShownText\n}\n'],
  [APP_WORDS_SWIFT, appWords('My School', 'Call it')],
  [APP_WORDS_LIST, appList('My School', 'Call it')],
  [TEST_FILE, 'final class SampleTests: XCTestCase {\n    func testIt() throws { _ = try GoldenFile.family("sample") }\n}\n'],
  [`ios/SnowlightCore/Tests/SnowlightCoreTests/${THIS_MACHINE}`, 'let zone = TimeZone.current\nlet env = ProcessInfo.processInfo.environment\n'],
  [`${GOLDEN}sample.json`, '{}\n'],
  [WORKFLOW, workflow()],
  [PROJECT, 'settings:\n  # CODE_SIGN_IDENTITY: Apple Development\n  CODE_SIGN_IDENTITY: "-"\n  DEVELOPMENT_TEAM: $(SNOWLIGHT_TEAM)\n'],
  ['ios/tools/build.sh', 'xcodebuild build CODE_SIGNING_ALLOWED=NO CODE_SIGN_IDENTITY=- ONLY_ACTIVE_ARCH=YES\n'],
]);

/**
 * The samples: each adds files to the clean tree, or replaces some, and must be refused
 * by every rule it lists.
 * @type {Array<{ name: string, rules: string[], files: Array<[string, string | null]> }>}
 */
const SAMPLES = [
  // (b) Words in a view.
  { name: 'Text("LIVE"), all capitals', rules: ['words.literal', 'words.text'], files: [[VIEW, view('Text("LIVE")')]] },
  { name: 'Text("closed"), lower case', rules: ['words.literal', 'words.text'], files: [[VIEW, view('Text("closed")')]] },
  { name: 'a one-word accessibility label', rules: ['words.literal'], files: [[VIEW, view('ShownLabel(title).accessibilityLabel("Close")')]] },
  { name: 'a string with a value put in', rules: ['words.literal'], files: [[VIEW, view('Label("\\(count) schools", systemImage: name)')]] },
  { name: 'an empty string literal', rules: ['words.literal'], files: [[VIEW, view('ShownLabel(title).navigationTitle("")')]] },
  { name: 'a raw string literal', rules: ['words.literal'], files: [[VIEW, view('ShownLabel(title).navigationTitle(#"Lit"#)')]] },
  { name: 'a string literal over several lines', rules: ['words.literal'], files: [[VIEW, view('ShownLabel(title).help("""\n        Snow day\n        """)')]] },
  { name: 'Text(when, style: .time)', rules: ['words.text'], files: [[VIEW, view('Text(when, style: .time)')]] },
  { name: 'Text(share, format: .percent)', rules: ['words.text'], files: [[VIEW, view('Text(share, format: .percent)')]] },
  { name: 'Text(verbatim:) outside the one file', rules: ['words.text'], files: [[VIEW, view('Text(verbatim: name)')]] },
  { name: 'Text.init', rules: ['words.text'], files: [[VIEW, view('Text.init(verbatim: name)')]] },
  { name: 'Text that is not verbatim in the one file', rules: ['words.text'], files: [[SHOWN, 'extension ShownText {\n    var text: Text { Text(drawnString) }\n}\n']] },
  { name: 'count.formatted()', rules: ['words.system'], files: [[VIEW, view('ShownLabel(count.formatted())')]] },
  { name: 'String(localized: "x")', rules: ['words.system', 'words.literal'], files: [[VIEW, view('ShownLabel(String(localized: "x"))')]] },
  { name: 'String(describing:)', rules: ['words.system'], files: [[VIEW, view('ShownLabel(String(describing: status))')]] },
  { name: 'a number formatter', rules: ['words.system'], files: [[VIEW, view('let f = NumberFormatter()')]] },
  { name: 'a date format style', rules: ['words.system'], files: [[VIEW, view('let style = Date.FormatStyle.dateTime')]] },
  { name: 'a localized string key', rules: ['words.system'], files: [[VIEW, view('let key: LocalizedStringKey = title')]] },
  { name: 'a localized string resource', rules: ['words.system'], files: [[VIEW, view('let key: LocalizedStringResource = title')]] },
  { name: 'NSLocalizedString', rules: ['words.system'], files: [[VIEW, view('let t = NSLocalizedString(key, comment: note)')]] },
  { name: 'an attributed string', rules: ['words.system'], files: [[VIEW, view('let t = AttributedString(title)')]] },
  { name: 'a date picker', rules: ['words.system'], files: [[VIEW, view('DatePicker(selection: $when) { ShownLabel(title) }')]] },
  { name: 'Date() in a view', rules: ['words.system'], files: [[VIEW, view('let now = Date()')]] },
  { name: 'Date.now in a view', rules: ['words.system'], files: [[VIEW, view('let now = Date.now')]] },
  { name: 'a view that names SiteWords', rules: ['words.table'], files: [[VIEW, view('ShownLabel(SiteWords.appName)')]] },
  { name: 'a view that names AppWords', rules: ['words.table'], files: [[APP + 'Sample.swift', view('ShownLabel(AppWords.map)')]] },
  { name: 'a view that names SiteFormat', rules: ['words.table'], files: [[VIEW, view('ShownLabel(SiteFormat.clock(450))')]] },
  { name: 'a view that names DetailsWords', rules: ['words.table'], files: [[VIEW, view('ShownLabel(DetailsWords.said(codes))')]] },
  { name: 'a view that names SeasonWords', rules: ['words.table'], files: [[VIEW, view('ShownLabel(SeasonWords.line(days, since))')]] },
  { name: "a view that reads a ShownText's characters", rules: ['words.drawn'], files: [[VIEW, view('TextField(model.prompt.drawnString, text: $query)')]] },
  { name: '.description', rules: ['words.value'], files: [[VIEW, view('ShownLabel(status.description)')]] },
  { name: '.debugDescription', rules: ['words.value'], files: [[VIEW, view('ShownLabel(status.debugDescription)')]] },
  { name: '.localizedDescription', rules: ['words.value'], files: [[VIEW, view('ShownLabel(error.localizedDescription)')]] },
  { name: '.rawValue', rules: ['words.value'], files: [[VIEW, view('ShownLabel(choice.rawValue)')]] },
  { name: 'a shown word in the names file', rules: ['words.names'], files: [[NAMES, 'struct SymbolName {\n    static let title = SymbolName(name: "Snow day")\n}\n']] },
  { name: 'a capital in the names file', rules: ['words.names'], files: [[NAMES, 'struct SymbolName {\n    static let title = SymbolName(name: "Live")\n}\n']] },
  // (b) Words in SnowlightCore.
  { name: 'ShownText( outside Words/', rules: ['core.showntext'], files: [[CORE_FILE, core('let t = ShownText("Lit")')]] },
  { name: 'ShownText.init outside Words/', rules: ['core.showntext'], files: [[SCREEN_FILE, 'func sample(_ text: String) -> ShownText {\n    ShownText.init(text)\n}\n']] },
  { name: 'a string literal in a screen model', rules: ['core.screenliteral'], files: [[SCREEN_FILE, 'struct Sample {\n    let note = "Not yet"\n}\n']] },
  // (b) The words only the app has.
  { name: 'an app word that is not on the list', rules: ['appwords.list'], files: [[APP_WORDS_SWIFT, appWords('My School', 'Call it', 'Lit')]] },
  { name: 'a listed word that is not in AppWords', rules: ['appwords.list'], files: [[APP_WORDS_LIST, appList('My School', 'Call it', 'Lit')]] },
  { name: 'a list line with no mark', rules: ['appwords.format'], files: [[APP_WORDS_LIST, '\towner\tMy School\napproved\towner\tCall it\n']] },
  { name: 'a list line marked with another word', rules: ['appwords.format'], files: [[APP_WORDS_LIST, 'fine\towner\tMy School\napproved\towner\tCall it\n']] },
  { name: 'a list line that does not say who', rules: ['appwords.format'], files: [[APP_WORDS_LIST, 'approved\t\tMy School\napproved\towner\tCall it\n']] },
  { name: 'an app word the site bans', rules: ['appwords.banned'], files: [[APP_WORDS_SWIFT, appWords('Maybe later')], [APP_WORDS_LIST, appList('Maybe later')]] },
  { name: 'an app word with an exclamation mark', rules: ['appwords.style'], files: [[APP_WORDS_SWIFT, appWords('Snow day!')], [APP_WORDS_LIST, appList('Snow day!')]] },
  { name: 'an app word with an em dash', rules: ['appwords.style'], files: [[APP_WORDS_SWIFT, appWords('Map \u2014 live')], [APP_WORDS_LIST, appList('Map \u2014 live')]] },
  { name: 'an app word with an emoji', rules: ['appwords.style'], files: [[APP_WORDS_SWIFT, appWords('Map \u{2744}')], [APP_WORDS_LIST, appList('Map \u{2744}')]] },
  { name: 'app words with no list', rules: ['appwords.list'], files: [[APP_WORDS_LIST, null]] },
  // (b) English only.
  { name: 'a .lproj folder', rules: ['language.file'], files: [['ios/App/es.lproj/InfoPlist.txt', 'x\n']] },
  { name: 'a .strings file', rules: ['language.file'], files: [['ios/App/Localizable.strings', 'x\n']] },
  { name: 'a .stringsdict file', rules: ['language.file'], files: [['ios/App/Localizable.stringsdict', 'x\n']] },
  { name: 'a string catalog', rules: ['language.file'], files: [['ios/App/Localizable.xcstrings', '{}\n']] },
  // (c) Purity of SnowlightCore.
  { name: 'TimeZone.current in SnowlightCore', rules: ['core.device'], files: [[CORE_FILE, core('let zone = TimeZone.current')]] },
  { name: 'Calendar.current in SnowlightCore', rules: ['core.device'], files: [[CORE_FILE, core('let calendar = Calendar.current')]] },
  { name: 'a Calendar built by hand', rules: ['core.device'], files: [[CORE_FILE, core('let calendar = Calendar(identifier: .gregorian)')]] },
  { name: 'Date() in SnowlightCore', rules: ['core.device'], files: [[CORE_FILE, core('let now = Date()')]] },
  { name: 'Date() inside a string that puts it in', rules: ['core.device'], files: [[CORE_FILE, core('let said = "now \\(Date())"')]] },
  { name: 'Date.now in SnowlightCore', rules: ['core.device'], files: [[CORE_FILE, core('let now = Date.now')]] },
  { name: 'timeIntervalSinceNow', rules: ['core.device'], files: [[CORE_FILE, core('let age = posted.timeIntervalSinceNow')]] },
  { name: 'autoupdatingCurrent', rules: ['core.device'], files: [[CORE_FILE, core('let zone = TimeZone.autoupdatingCurrent')]] },
  { name: 'ProcessInfo', rules: ['core.device'], files: [[CORE_FILE, core('let env = ProcessInfo.processInfo.environment')]] },
  { name: 'something of our own named current', rules: ['core.device'], files: [[CORE_FILE, core('let current = 3')]] },
  { name: 'a date formatter in SnowlightCore', rules: ['core.formatter'], files: [[CORE_FILE, core('let f = DateFormatter()')]] },
  { name: 'an ISO date formatter in SnowlightCore', rules: ['core.formatter'], files: [[CORE_FILE, core('let f = ISO8601DateFormatter()')]] },
  { name: 'a format style in SnowlightCore', rules: ['core.formatter'], files: [[CORE_FILE, core('let s: IntegerFormatStyle<Int> = style')]] },
  { name: '.formatted( in SnowlightCore', rules: ['core.formatter'], files: [[CORE_FILE, core('let s = count.formatted()')]] },
  { name: 'a pattern engine: NSRegularExpression', rules: ['core.pattern'], files: [[CORE_FILE, core('let r = try? NSRegularExpression(pattern: p)')]] },
  { name: 'a pattern engine: Regex', rules: ['core.pattern'], files: [[CORE_FILE, core('let r = try? Regex(p)')]] },
  { name: 'a pattern engine: range(of:options: .regularExpression)', rules: ['core.pattern'], files: [[CORE_FILE, core('let r = text.range(of: p, options: .regularExpression)')]] },
  { name: 'a pattern engine: wholeMatch', rules: ['core.pattern'], files: [[CORE_FILE, core('let m = text.wholeMatch(of: p)')]] },
  { name: 'a pattern engine: firstMatch', rules: ['core.pattern'], files: [[CORE_FILE, core('let m = text.firstMatch(of: p)')]] },
  { name: 'a pattern engine: prefixMatch', rules: ['core.pattern'], files: [[CORE_FILE, core('let m = text.prefixMatch(of: p)')]] },
  { name: 'a character set', rules: ['core.pattern'], files: [[CORE_FILE, core('let s = CharacterSet.decimalDigits')]] },
  { name: 'trimming with the system list', rules: ['core.pattern'], files: [[CORE_FILE, core('let t = text.trimmingCharacters(in: .whitespacesAndNewlines)')]] },
  { name: '.whitespaces', rules: ['core.pattern'], files: [[CORE_FILE, core('let parts = text.components(separatedBy: .whitespaces)')]] },
  { name: 'isWhitespace', rules: ['core.pattern'], files: [[CORE_FILE, core('let blank = character.isWhitespace')]] },
  { name: 'isNumber', rules: ['core.pattern'], files: [[CORE_FILE, core('let digit = character.isNumber')]] },
  { name: 'isLetter', rules: ['core.pattern'], files: [[CORE_FILE, core('let letter = character.isLetter')]] },
  { name: 'wholeNumberValue', rules: ['core.pattern'], files: [[CORE_FILE, core('let n = character.wholeNumberValue')]] },
  { name: 'try!', rules: ['core.crash'], files: [[CORE_FILE, core('let value = try! parse(text)')]] },
  { name: 'as!', rules: ['core.crash'], files: [[CORE_FILE, core('let value = any as! Int')]] },
  { name: 'fatalError(', rules: ['core.crash'], files: [[CORE_FILE, core('fatalError()')]] },
  { name: 'preconditionFailure(', rules: ['core.crash'], files: [[CORE_FILE, core('preconditionFailure()')]] },
  { name: 'assertionFailure(', rules: ['core.crash'], files: [[CORE_FILE, core('assertionFailure()')]] },
  { name: 'a forced unwrap', rules: ['core.crash'], files: [[CORE_FILE, core('let first = rows.first!')]] },
  { name: 'a forced unwrap after a call', rules: ['core.crash'], files: [[CORE_FILE, core('let zone = zone(named: name)!.offset')]] },
  { name: 'a type that unwraps itself', rules: ['core.crash'], files: [[CORE_FILE, 'struct Sample {\n    var name: String!\n}\n']] },
  { name: 'import SwiftUI in SnowlightCore', rules: ['core.import'], files: [[CORE_FILE, 'import SwiftUI\n']] },
  { name: 'import of one Foundation type by name', rules: ['core.import'], files: [[CORE_FILE, 'import struct Foundation.Date\n']] },
  { name: '.current in a test that may not read it', rules: ['tests.device'], files: [[TEST_FILE, 'let zone = TimeZone.current\nlet f = try GoldenFile.family("sample")\n']] },
  { name: 'ProcessInfo in a test that may not read it', rules: ['tests.device'], files: [[TEST_FILE, 'let env = ProcessInfo.processInfo.environment\nlet f = try GoldenFile.family("sample")\n']] },
  // (a) Signing, secrets and billed machines.
  { name: 'DEVELOPMENT_TEAM with a team value', rules: ['signing.team'], files: [[PROJECT, `settings:\n  DEVELOPMENT_TEAM: ${TEAM_SHAPE}\n`]] },
  { name: 'DEVELOPMENT_TEAM with a team value, in a config file', rules: ['signing.team'], files: [['ios/Config/Base.xcconfig', `DEVELOPMENT_TEAM = ${TEAM_SHAPE}\n`]] },
  { name: 'DEVELOPMENT_TEAM with a team value, on a command line', rules: ['signing.team'], files: [['ios/tools/build.sh', `xcodebuild DEVELOPMENT_TEAM="${TEAM_SHAPE}" build\n`]] },
  { name: 'a signing identity', rules: ['signing.identity'], files: [[PROJECT, 'settings:\n  CODE_SIGN_IDENTITY: "Apple Development"\n']] },
  { name: 'a signing identity for one kit', rules: ['signing.identity'], files: [['ios/Config/Base.xcconfig', 'CODE_SIGN_IDENTITY[sdk=iphoneos*] = iPhone Developer\n']] },
  { name: 'an empty signing identity', rules: ['signing.identity'], files: [['ios/tools/build.sh', 'xcodebuild CODE_SIGN_IDENTITY="" build\n']] },
  { name: 'a provisioning profile', rules: ['signing.profile'], files: [[PROJECT, 'settings:\n  PROVISIONING_PROFILE_SPECIFIER: Snowlight\n']] },
  { name: 'a .p8 key', rules: ['signing.file'], files: [['ios/AuthKey.p8', null]] },
  { name: 'a .p12 identity', rules: ['signing.file'], files: [['ios/keys/identity.p12', null]] },
  { name: 'a .cer certificate', rules: ['signing.file'], files: [['ios/dist.cer', null]] },
  { name: 'a provisioning profile file', rules: ['signing.file'], files: [['ios/Snowlight.mobileprovision', null]] },
  { name: 'a .pem file', rules: ['signing.file'], files: [['ios/tools/key.pem', 'x\n']] },
  { name: 'a committed Local.xcconfig', rules: ['signing.file'], files: [[LOCAL_CONFIG, 'DEVELOPMENT_TEAM = $(inherited)\n']] },
  { name: 'runs-on: macos-latest', rules: ['runner.label'], files: [[WORKFLOW, workflow({ runner: 'macos-latest' })]] },
  { name: 'runs-on: macos-26-xlarge', rules: ['runner.label'], files: [[WORKFLOW, workflow({ runner: 'macos-26-xlarge' })]] },
  { name: 'runs-on: macos-26-large', rules: ['runner.label'], files: [[WORKFLOW, workflow({ runner: 'macos-26-large' })]] },
  { name: 'runs-on from a matrix', rules: ['runner.label'], files: [[WORKFLOW, workflow({ runner: '${{ matrix.os }}' })]] },
  { name: 'runs-on as a list', rules: ['runner.label'], files: [[WORKFLOW, workflow({ runner: '[self-hosted, macOS]' })]] },
  { name: 'a workflow that reads a secret', rules: ['workflow.secrets'], files: [[WORKFLOW, workflow({ run: 'echo ${{ secrets.SOMETHING }}' })]] },
  { name: 'an action that is not one of the three', rules: ['workflow.uses'], files: [[WORKFLOW, workflow({ uses: 'actions/cache@v4' })]] },
  { name: 'an allowed action at another version', rules: ['workflow.uses'], files: [[WORKFLOW, workflow({ uses: 'actions/checkout@v4' })]] },
  { name: 'permissions wider than reading', rules: ['workflow.permissions'], files: [[WORKFLOW, workflow({ permissions: 'permissions:\n  contents: write' })]] },
  { name: 'permissions with a second line', rules: ['workflow.permissions'], files: [[WORKFLOW, workflow({ permissions: 'permissions:\n  contents: read\n  id-token: write' })]] },
  { name: 'no permissions at all', rules: ['workflow.permissions'], files: [[WORKFLOW, workflow({ permissions: 'env:\n  A: b' })]] },
  { name: 'permissions set by a job', rules: ['workflow.permissions'], files: [[WORKFLOW, workflow({ run: 'echo ok\n    permissions:\n      contents: write' })]] },
  // (e) Debug code that a release build would hold.
  { name: 'tour code with no #if DEBUG at all', rules: ['tour.debug'], files: [[TOUR, 'import SwiftUI\nlet key = "tour.name"\n']] },
  { name: 'an import before the #if DEBUG of a tour file', rules: ['tour.debug'], files: [[TOUR, 'import MetalKit\n#if DEBUG\nlet key = "tour.name"\n#endif\n']] },
  { name: 'tour code after the #endif', rules: ['tour.debug'], files: [[TOUR, '#if DEBUG\nlet key = "tour.name"\n#endif\nlet late = 3\n']] },
  { name: 'a tour file whose debug block has an #else', rules: ['tour.debug'], files: [[TOUR, '#if DEBUG\nlet key = "tour.name"\n#else\nlet key = "none"\n#endif\n']] },
  { name: 'a tour file under another condition', rules: ['tour.debug'], files: [[TOUR, '#if os(iOS)\nlet key = "tour.name"\n#endif\n']] },
  { name: 'a tour file under DEBUG or something else', rules: ['tour.debug'], files: [[TOUR, '#if DEBUG || TESTFLIGHT\nlet key = "tour.name"\n#endif\n']] },
  { name: 'a tour folder in the app, outside #if DEBUG', rules: ['tour.debug'], files: [[APP + 'Tour/Sample.swift', 'let key = "tour.name"\n']] },
  { name: 'a tour file whose #if DEBUG is never closed', rules: ['tour.debug'], files: [[TOUR, '#if DEBUG\nlet key = "tour.name"\n']] },
  // (d) Families.
  { name: 'a golden family no test names', rules: ['families.unnamed'], files: [[`${GOLDEN}orphan.json`, '{}\n']] },
  { name: 'a golden family named only in a comment', rules: ['families.unnamed'], files: [[TEST_FILE, '// GoldenFile.family("sample")\n']] },
  { name: 'a test that names a family that is not there', rules: ['families.missing'], files: [[TEST_FILE, 'let a = try GoldenFile.family("sample")\nlet b = try GoldenFile.family("gone")\n']] },
];

/** The rules, each of which at least one sample must hold. */
const RULES = [
  'signing.file', 'signing.profile', 'signing.identity', 'signing.team',
  'workflow.secrets', 'runner.label', 'workflow.uses', 'workflow.permissions',
  'words.literal', 'words.names', 'words.text', 'words.table', 'words.drawn', 'words.system', 'words.value',
  'core.showntext', 'core.screenliteral', 'language.file',
  'appwords.list', 'appwords.format', 'appwords.banned', 'appwords.style',
  'core.import', 'core.device', 'core.formatter', 'core.pattern', 'core.crash', 'tests.device',
  'families.unnamed', 'families.missing',
  'tour.debug',
];

/**
 * Runs the samples. Returns what is wrong with the guards themselves; empty when every
 * sample is refused by its rules and the clean tree passes.
 */
function selfTest(banned) {
  const wrong = [];
  for (const cleanHit of checkTree(CLEAN, banned)) {
    wrong.push(`the clean sample was refused: [${cleanHit.rule}] ${cleanHit.path}:${cleanHit.line} ${cleanHit.what}`);
  }
  const held = new Set();
  for (const sample of SAMPLES) {
    const tree = new Map(CLEAN);
    for (const [path, text] of sample.files) {
      if (text === null && CLEAN.has(path)) tree.delete(path);
      else tree.set(path, text);
    }
    const fired = new Set(checkTree(tree, banned).map((one) => one.rule));
    for (const rule of sample.rules) {
      if (fired.has(rule)) held.add(rule);
      else wrong.push(`the sample '${sample.name}' was not refused by the rule ${rule} (it fired: ${[...fired].join(', ') || 'nothing'})`);
    }
  }
  for (const rule of RULES) {
    if (!held.has(rule)) wrong.push(`no sample holds the rule ${rule}`);
  }
  for (const rule of held) {
    if (!RULES.includes(rule)) wrong.push(`the rule ${rule} is not in the list of rules`);
  }
  return wrong;
}

// The real tree ----------------------------------------------------------------------------

/** Every file under a folder, as repository paths, leaving out what a build leaves behind. */
function walk(folder, into) {
  const absolute = join(REPO, ...folder.split('/'));
  if (!existsSync(absolute)) return;
  for (const name of readdirSync(absolute).sort()) {
    const path = `${folder}/${name}`;
    const stat = statSync(join(absolute, name));
    if (stat.isDirectory()) {
      if (!BUILD_FOLDERS.has(name)) walk(path, into);
    } else if (stat.isFile()) {
      into.push(path);
    }
  }
}

/**
 * The files to check. In a git checkout: what is committed or would be (tracked, or new
 * and not ignored), so a Local.xcconfig that git ignores on the borrowed Mac is not taken
 * for a committed one. Anywhere else (an export of a commit): every file there is.
 */
function listFiles() {
  const asked = spawnSync('git', ['rev-parse', '--show-toplevel'], { cwd: REPO, encoding: 'utf8' });
  if (asked.status === 0 && asked.stdout.trim() !== '' && sameFolder(asked.stdout.trim(), REPO)) {
    const listed = spawnSync(
      'git',
      ['ls-files', '-z', '--cached', '--others', '--exclude-standard', '--', 'ios', '.github/workflows'],
      { cwd: REPO, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 },
    );
    if (listed.status === 0) {
      const paths = listed.stdout
        .split('\0')
        .filter((path) => path !== '' && existsSync(join(REPO, ...path.split('/'))));
      return { paths: paths.sort(), how: 'the files git tracks or would add' };
    }
  }
  const paths = [];
  walk('ios', paths);
  walk('.github/workflows', paths);
  return { paths: paths.sort(), how: 'every file in the folder (not a git checkout)' };
}

function sameFolder(one, other) {
  const tidy = (path) => {
    const resolved = join(path);
    return resolved.endsWith(sep) ? resolved.slice(0, -1) : resolved;
  };
  return tidy(one) === tidy(other);
}

function readTree() {
  const { paths, how } = listFiles();
  /** @type {Map<string, string | null>} */
  const files = new Map();
  for (const path of paths) {
    if (!path.startsWith('ios/') && !isIosWorkflow(path)) continue;
    const name = path.split('/').pop() ?? '';
    const isText = TEXT_ENDINGS.some((ending) => name.endsWith(ending));
    files.set(path, isText ? readFileSync(join(REPO, ...path.split('/')), 'utf8') : null);
  }
  return { files, how };
}

function nodeIsNewEnough() {
  const [major, minor] = process.versions.node.split('.').map((part) => Number(part));
  return major > 22 || (major === 22 && minor >= 18);
}

async function main() {
  const say = (line) => process.stdout.write(`${line}\n`);
  if (!nodeIsNewEnough()) {
    say(`check-ios: this needs Node 22.18 or newer; this is ${process.versions.node}`);
    return 3;
  }

  let banned;
  try {
    const site = await import(pathToFileURL(join(REPO, 'web', 'scripts', 'check-copy.mjs')).href);
    banned = site.BANNED;
  } catch (error) {
    say(`check-ios: the site's list of banned words could not be loaded: ${error instanceof Error ? error.message : error}`);
    return 1;
  }
  if (!Array.isArray(banned) || banned.length < 10 || !banned.every((entry) => Array.isArray(entry) && entry.length === 2)) {
    say("check-ios: web/scripts/check-copy.mjs no longer exports BANNED as a list of [label, pattern] pairs");
    return 1;
  }

  const wrong = selfTest(banned);
  if (wrong.length > 0) {
    say('check-ios: the guards failed their own test, so nothing they say can be trusted:');
    for (const line of wrong) say(`  ${line}`);
    return 1;
  }
  say(`self-test: ${SAMPLES.length} samples refused, each by its rule; ${RULES.length} rules held; the clean sample passed`);

  const { files, how } = readTree();
  // The checks mean nothing if they looked in the wrong place.
  const needed = [SHOWN, NAMES, APP_WORDS_SWIFT, APP_WORDS_LIST, 'ios/project.yml', `${WORKFLOWS}ios-core.yml`, `${WORKFLOWS}ios-app.yml`];
  const absent = needed.filter((path) => !files.has(path));
  if (absent.length > 0) {
    say(`check-ios: these files were not found, so the tree is not what the guards expect: ${absent.join(', ')}`);
    return 1;
  }

  const hits = checkTree(files, banned);
  const paths = [...files.keys()];
  const counts = [
    `${paths.length} files (${how})`,
    `${paths.filter(isViewCode).length} view files`,
    `${paths.filter((path) => path.startsWith(CORE) && path.endsWith('.swift')).length} core source files`,
    `${paths.filter((path) => path.startsWith(CORE_TESTS) && path.endsWith('.swift')).length} test files`,
    `${paths.filter(isIosWorkflow).length} workflows`,
    `${paths.filter((path) => path.startsWith(GOLDEN) && path.endsWith('.json')).length} golden families`,
    `${banned.length} banned words from the site`,
  ];
  say(`checked: ${counts.join(', ')}`);
  if (hits.length > 0) {
    for (const one of hits) say(`${one.path}${one.line > 0 ? `:${one.line}` : ''}: [${one.rule}] ${one.what}`);
    say(`check-ios: ${hits.length} ${hits.length === 1 ? 'problem' : 'problems'}`);
    return 1;
  }
  say('check-ios: clean');
  return 0;
}

process.exitCode = await main();
