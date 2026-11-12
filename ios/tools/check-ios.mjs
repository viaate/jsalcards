// check-ios.mjs: the guards of the iPhone app. One script; it ends with status 1 on any hit.
//
//   node ios/tools/check-ios.mjs
//
// What it keeps out, under ios/ and in .github/workflows/ios-*.yml:
//
//   (a) signing material, secrets and billed machines, in whatever form a workflow or a
//       settings file writes them;
//   (b) words: any way for a view to draw text that did not come from its screen model,
//       and any text SnowlightCore hands out through its public surface;
//       and a view laid out by the device's screen, idiom or orientation, or by a length
//       the size of a screen;
//   (c) impurity in SnowlightCore: the device's clock or zone, the process's environment,
//       the network, a formatter, a pattern engine, a crash path, any import but
//       Foundation; and in the tests: the clock, the zone, the environment or the network
//       (but in ThisMachineTests.swift), a skipped test, a test kept from one platform, a
//       count of tests that is not the committed one, a Swift test run in CI whose zone is
//       UTC or not stated;
//   (d) golden families that no test reads, and tests that name a family that is not there;
//   (e) debug code that a release build would hold: the picture tour's folder is outside
//       the words rules, so every line of code in it must sit inside `#if DEBUG`.
//
// It reads code, not comments. It skips itself and ios/README.md: both must be able to
// name what is banned. Its lists of names are lists: what a list leaves out passes. The
// locks that need no list are the compiler's (the word tables, ShownText's initializer and
// every string form of SnowlightCore are not public) and the public-surface rule below.
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
const WINDOW_STYLE = 'ios/SnowlightKit/Sources/SnowlightKit/Shell/WindowStyle.swift';
const TEST_COUNT = 'ios/tools/test-count.txt';
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
];

/**
 * Other ways for a view to come by text that its screen model did not hand it: a value's
 * own description, the text forms SnowlightCore keeps to itself, a binding's raw value,
 * reflection, the compiler's own literals, a cast to text. (b)
 */
const VIEW_VALUE_WORDS = [
  [/\.\s*description(?![A-Za-z0-9_])/, '.description'],
  [/\.\s*debugDescription(?![A-Za-z0-9_])/, '.debugDescription'],
  [/\.\s*localizedDescription(?![A-Za-z0-9_])/, '.localizedDescription'],
  [/\.\s*rawValue(?![A-Za-z0-9_])/, '.rawValue'],
  [/\.\s*stored(?![A-Za-z0-9_])/, "a choice's stored form"],
  [/\.\s*hex(?![A-Za-z0-9_])/, "a color's text form"],
  [/\.\s*wrappedValue(?![A-Za-z0-9_])/, "a binding's raw value"],
  [/(?<![A-Za-z0-9_])Mirror(?![A-Za-z0-9_])/, 'reflection, which hands out the names of fields'],
  [/#(?:function|fileID|filePath|file|dsohandle)(?![A-Za-z0-9_])/, "a literal the compiler fills with a name"],
  [/(?<![A-Za-z0-9_])as\s*[?!]?\s*(?:String|Substring|Character|NSString|StaticString)(?![A-Za-z0-9_])/, 'a cast to text'],
  [/(?<![A-Za-z0-9_)\]>?!])\.\s*init(?![A-Za-z0-9_])/, 'an initializer whose type is left to the compiler (name the type: in a view it could be text)'],
  [/(?<![A-Za-z0-9_])(?:Character|UnicodeScalar|Unicode\s*\.\s*Scalar)(?![A-Za-z0-9_])/, 'a character made from a number'],
];

/** What was typed into search may reach a view only as its binding, `$query.typed`. (b) */
const TYPED = /\.\s*typed(?![A-Za-z0-9_])/;
const BINDING_BEFORE = /\$[A-Za-z_][A-Za-z0-9_]*\s*$/;

const WORD_TABLES = /(?<![A-Za-z0-9_])(SiteWords|SiteFormat|AppWords|DetailsWords|SeasonWords)(?![A-Za-z0-9_])/;
const TEXT_MAKER = /(?<![A-Za-z0-9_])Text\s*(?:\(|\.\s*init(?![A-Za-z0-9_]))/;
const TEXT_VERBATIM = /^Text\(\s*verbatim\s*:/;
const DRAWN = /(?<![A-Za-z0-9_])drawnString(?![A-Za-z0-9_])/;

/**
 * Every way SnowlightCore outside Words/ could make a ShownText: by its name, by an
 * initializer whose type is left to the compiler, through another name for the type, the
 * type passed around as a value, or an extension of the type. (b)
 */
const SHOWN_MAKERS = [
  [/(?<![A-Za-z0-9_])ShownText\s*(?:\(|\.\s*init(?![A-Za-z0-9_]))/, 'ShownText( outside Words/'],
  [/(?<![A-Za-z0-9_)\]>?!])\.\s*init(?![A-Za-z0-9_])/, 'an initializer whose type is left to the compiler (name the type; outside Words/ it could be a ShownText)'],
  [/(?<![A-Za-z0-9_])ShownText\s*\.\s*self(?![A-Za-z0-9_])/, 'the ShownText type passed around as a value'],
  [/(?<![A-Za-z0-9_])typealias\s[^\n=]*=\s*(?:SnowlightCore\s*\.\s*)?ShownText(?![A-Za-z0-9_])/, 'another name for ShownText'],
  [/(?<![A-Za-z0-9_])extension\s+(?:SnowlightCore\s*\.\s*)?ShownText(?![A-Za-z0-9_])/, 'an extension of ShownText outside Words/'],
];

/**
 * The device's clock, zone and languages. Each entry is a pattern, what it is, and an
 * example: the self-test plants every example in SnowlightCore, in a test and in a view,
 * and each must be refused in all three. (c)
 */
const CLOCK_ZONE = [
  [/(?<![A-Za-z0-9_])Date\s*\(\s*\)/, 'Date()', 'let now = Date()'],
  [/(?<![A-Za-z0-9_])Date\s*\.\s*init\s*\(\s*\)/, 'Date.init()', 'let now = Date.init()'],
  [/(?<![A-Za-z0-9_)\]>?!])\.\s*init\s*\(\s*\)/, 'an empty .init() whose type is left to the compiler (a Date made so reads the clock)', 'let now: Date = .init()'],
  [/(?<![A-Za-z0-9_])Date\s*\.\s*now(?![A-Za-z0-9_])/, 'Date.now', 'let now = Date.now'],
  [/(?<![A-Za-z0-9_])\.\s*now(?![A-Za-z0-9_])/, 'a .now with no named value before it', 'let now: Date = .now'],
  [/(?<![A-Za-z0-9_])timeIntervalSinceNow(?![A-Za-z0-9_])/, 'timeIntervalSinceNow', 'let age = posted.timeIntervalSinceNow'],
  [/(?<![A-Za-z0-9_])(?:NSDate|Date)\s*\.\s*timeIntervalSinceReferenceDate(?![A-Za-z0-9_])/, 'the clock as seconds since 2001', 'let seconds = Date.timeIntervalSinceReferenceDate'],
  [/\.\s*current(?![A-Za-z0-9_])/, '.current', 'let zone = TimeZone.current'],
  [/(?<![A-Za-z0-9_])(?:let|var|func|case)\s+current(?![A-Za-z0-9_])/, 'something of our own named current', 'let current = 3'],
  [/(?<![A-Za-z0-9_])autoupdatingCurrent(?![A-Za-z0-9_])/, 'autoupdatingCurrent', 'let zone = TimeZone.autoupdatingCurrent'],
  [/(?<![A-Za-z0-9_])ProcessInfo(?![A-Za-z0-9_])/, 'ProcessInfo', 'let up = ProcessInfo.processInfo.systemUptime'],
  [/(?<![A-Za-z0-9_])Calendar(?![A-Za-z0-9_])/, 'Calendar', 'let calendar = Calendar(identifier: .gregorian)'],
  [/(?<![A-Za-z0-9_])NSDate(?![A-Za-z0-9_])/, 'NSDate', 'let now = NSDate()'],
  [/(?<![A-Za-z0-9_])NSTimeZone(?![A-Za-z0-9_])/, 'NSTimeZone', 'let zone = NSTimeZone.local'],
  [/(?<![A-Za-z0-9_])NSCalendar(?![A-Za-z0-9_])/, 'NSCalendar', 'let calendar = NSCalendar(identifier: .gregorian)'],
  [/(?<![A-Za-z0-9_])NSLocale(?![A-Za-z0-9_])/, 'NSLocale', 'let locale = NSLocale(localeIdentifier: name)'],
  [/(?<![A-Za-z0-9_])preferredLanguages(?![A-Za-z0-9_])/, "the phone's languages", 'let languages = Locale.preferredLanguages'],
  [/(?<![A-Za-z0-9_])CFAbsoluteTimeGetCurrent(?![A-Za-z0-9_])/, 'CFAbsoluteTimeGetCurrent', 'let now = CFAbsoluteTimeGetCurrent()'],
  [/(?<![A-Za-z0-9_])CF(?:TimeZone|Calendar|Locale)[A-Za-z0-9_]*/, 'a Core Foundation zone, calendar or locale', 'let zone = CFTimeZoneCopyDefault()'],
  [/(?<![A-Za-z0-9_])Dispatch(?:Wall)?Time\s*\.\s*now(?![A-Za-z0-9_])/, 'DispatchTime.now', 'let at = DispatchTime.now()'],
  [/(?<![A-Za-z0-9_])(?:ContinuousClock|SuspendingClock)(?![A-Za-z0-9_])/, 'a system clock', 'let clock = ContinuousClock()'],
  [/(?<![A-Za-z0-9_])(?:clock_gettime(?:_nsec_np)?|gettimeofday|mach_absolute_time|mach_continuous_time)(?![A-Za-z0-9_])/, "the C library's clock", 'let status = clock_gettime(CLOCK_REALTIME, &spec)'],
  [/(?<![A-Za-z0-9_.])time\s*\(\s*(?:nil|&)/, "the C library's time()", 'let seconds = time(nil)'],
  [/(?<![A-Za-z0-9_])(?:localtime(?:_r)?|gmtime(?:_r)?|mktime|timegm|strftime|tzset|tzname)(?![A-Za-z0-9_])/, "the C library's zone", 'let parts = localtime_r(&seconds, &broken)'],
  [/(?<![A-Za-z0-9_])typealias\s+[A-Za-z_][A-Za-z0-9_]*\s*=\s*(?:Foundation\s*\.\s*)?(?:Date|TimeZone|Locale|DispatchTime)(?![A-Za-z0-9_])/, 'another name for a clock or zone type', 'typealias Moment = Date'],
  [/(?<![A-Za-z0-9_])(?:Date|TimeZone|Locale)\s*\.\s*self(?![A-Za-z0-9_])/, 'a clock or zone type passed around as a value', 'let kind = Date.self'],
];

/**
 * The process's environment, and the phone's own settings store: SnowlightCore is handed
 * a store (AppearanceChoice.kept(in:)) and never takes the phone's. In SnowlightCore and
 * the tests. (c)
 */
const ENVIRONMENT = [
  [/(?<![A-Za-z0-9_])(?:getenv|secure_getenv|setenv|unsetenv|putenv|environ)(?![A-Za-z0-9_])/, "the process's environment", 'let zone = getenv("TZ")'],
  [/(?<![A-Za-z0-9_])environment(?![A-Za-z0-9_])/, "the process's environment", 'let all = info.environment'],
  [/(?<![A-Za-z0-9_])UserDefaults\s*(?:\.\s*standard|\(\s*\))/, "the phone's own settings store", 'let store = UserDefaults.standard'],
  [/(?<![A-Za-z0-9_])\.\s*standard(?![A-Za-z0-9_])/, 'a .standard with no named type before it (the phone\'s own settings store, say)', 'let store: UserDefaults = .standard'],
];

/** The network. Nothing in M0 reads it: not SnowlightCore, not a test, not a view. (c) */
const NETWORK = [
  [/(?<![A-Za-z0-9_])(?:NS)?URLSession[A-Za-z0-9_]*/, 'URLSession', 'URLSession.shared.dataTask(with: request).resume()'],
  [/(?<![A-Za-z0-9_])(?:NS)?(?:Mutable)?URLRequest(?![A-Za-z0-9_])/, 'URLRequest', 'let request = URLRequest(url: address)'],
  [/(?<![A-Za-z0-9_])NSURLConnection(?![A-Za-z0-9_])/, 'NSURLConnection', 'NSURLConnection.sendAsynchronousRequest(request, queue: queue) { _, _, _ in }'],
  [/(?<![A-Za-z0-9_])URL\s*\(\s*string\s*:/, 'a URL made from text', 'let address = URL(string: text)'],
  [/(?<![A-Za-z0-9_])URLComponents(?![A-Za-z0-9_])/, 'URLComponents', 'let parts = URLComponents(string: text)'],
  [/(?<![A-Za-z0-9_])NW(?:Connection|Listener|PathMonitor|Endpoint|Browser)(?![A-Za-z0-9_])/, "Apple's Network framework", 'let link = NWConnection(host: host, port: 443, using: .tls)'],
  [/(?<![A-Za-z0-9_])CF(?:Stream|Socket|Network|Host|HTTP)[A-Za-z0-9_]*/, 'a Core Foundation socket or stream', 'CFStreamCreatePairWithSocketToHost(nil, host, 443, &input, &output)'],
  [/(?<![A-Za-z0-9_])getStreamsToHost(?![A-Za-z0-9_])/, 'a stream to a host', 'Stream.getStreamsToHost(withName: host, port: 443, inputStream: &input, outputStream: &output)'],
];
/** A string literal that names a place on a network. */
const ADDRESS_LITERAL = /[A-Za-z][A-Za-z0-9+.-]*:\/\//;

/**
 * What else of the device a view could read and turn into words: its zone and language,
 * the app's bundle, the phone's name, the clipboard, the file system, the settings store.
 * Only Shell/WindowStyle.swift may hold the settings store, and it reads the appearance
 * through SnowlightCore. (b)
 */
const VIEW_DEVICE = [
  [/(?<![A-Za-z0-9_])TimeZone(?![A-Za-z0-9_])/, 'TimeZone', 'let zone = TimeZone(identifier: name)'],
  [/(?<![A-Za-z0-9_])Locale(?![A-Za-z0-9_])/, 'Locale', 'let locale = Locale(identifier: name)'],
  [/(?<![A-Za-z0-9_])Bundle(?![A-Za-z0-9_])/, "the app's bundle", 'let id = Bundle.main.bundleIdentifier'],
  [/(?<![A-Za-z0-9_])UIDevice(?![A-Za-z0-9_])/, 'UIDevice', 'let phone = UIDevice.current.name'],
  [/(?<![A-Za-z0-9_])UIApplication(?![A-Za-z0-9_])/, 'UIApplication', 'let icon = UIApplication.shared.alternateIconName'],
  [/(?<![A-Za-z0-9_])UIPasteboard(?![A-Za-z0-9_])/, 'the clipboard', 'let pasted = UIPasteboard.general.string'],
  [/(?<![A-Za-z0-9_])FileManager(?![A-Za-z0-9_])/, 'the file system', 'let folder = FileManager.default.temporaryDirectory'],
  [/(?<![A-Za-z0-9_])NS(?:HomeDirectory|TemporaryDirectory|UserName|FullUserName|OpenStepRootDirectory|StringFrom[A-Za-z]+)(?![A-Za-z0-9_])/, 'a name the system hands out as text', 'let home = NSHomeDirectory()'],
  [/(?<![A-Za-z0-9_])URL(?![A-Za-z0-9_])/, 'a URL, whose parts are text', 'let folder = URL.documentsDirectory'],
  [/(?<![A-Za-z0-9_])UserDefaults(?![A-Za-z0-9_])/, 'the settings store (only Shell/WindowStyle.swift holds it)', 'let store = UserDefaults.standard'],
  [/(?<![A-Za-z0-9_])(?:string|stringArray|object|array|dictionary|value|url)\s*\(\s*forKey\s*:/, 'a stored value read as it is', 'let kept = store.string(forKey: key)'],
  [/(?<![A-Za-z0-9_])dictionaryRepresentation(?![A-Za-z0-9_])/, 'every stored value at once', 'let all = store.dictionaryRepresentation()'],
  [/(?<![A-Za-z0-9_])UUID(?![A-Za-z0-9_])/, 'a random identifier, whose text form is a word', 'Button(UUID().uuidString) { }'],
  [/(?<![A-Za-z0-9_])CommandLine(?![A-Za-z0-9_])/, "the app's launch arguments, which are text", 'Button(CommandLine.arguments[0]) { }'],
  [/(?<![A-Za-z0-9_])(?:fontName|familyName|familyNames|fontNames|accessibilityName|persistentIdentifier|accessibilityIdentifier|_kvcKeyPathString)(?![A-Za-z0-9_])/, 'a name the system hands out as text', 'Button(UIFont.systemFont(ofSize: 1).fontName) { }'],
];
const SETTINGS_STORE = 'the settings store (only Shell/WindowStyle.swift holds it)';

/**
 * What a view may not lay itself out by: the device's screen, its idiom, its orientation.
 * A screen is laid out from the room its window gives it and the system's width class
 * (SnowlightCore's ContentLayout), because the same app runs on an iPhone 17 Pro, on the
 * iPhone Duo closed and open, and a fold changes the room while it runs. UIDevice is
 * already refused by the list above. (b)
 */
const VIEW_LAYOUT = [
  [/(?<![A-Za-z0-9_])UIScreen(?![A-Za-z0-9_])/, "the device's screen", 'let wide = UIScreen.main.bounds.width'],
  [/(?<![A-Za-z0-9_])(?:UIUserInterfaceIdiom|userInterfaceIdiom)(?![A-Za-z0-9_])/, "the device's idiom", 'let pad = traits.userInterfaceIdiom == .pad'],
  [/(?<![A-Za-z0-9_])(?:UIInterfaceOrientation|UIDeviceOrientation|interfaceOrientation|isPortrait|isLandscape)(?![A-Za-z0-9_])/, 'the orientation (the inner screen of the Duo does not follow it; lay out by the width class)', 'let side = scene.interfaceOrientation.isLandscape'],
  [/(?<![A-Za-z0-9_])(?:nativeBounds|nativeScale)(?![A-Za-z0-9_])/, "the screen's own measure", 'let pixels = window.windowScene?.screen.nativeBounds'],
];
/** A number in a view's code: a length of 300 points or more is the size of a screen. (b) */
const VIEW_NUMBER = /(?<![A-Za-z0-9_.])[0-9][0-9_]*(?:\.[0-9]+)?(?![A-Za-z0-9_.])/;
const SCREEN_SIZED = 300;

/**
 * Ways around the type system, which would let code make a ShownText it may not make, or
 * read text a type keeps to itself: a cast the compiler does not check, raw memory, a
 * symbol looked up by its name. In the views and in SnowlightCore. (b)
 */
const UNSAFE = [
  [/(?<![A-Za-z0-9_])(?:unsafeBitCast|unsafeDowncast)(?![A-Za-z0-9_])/, 'a cast the compiler does not check', 'let made = unsafeBitCast(characters, to: Said.self)'],
  [/(?<![A-Za-z0-9_])(?:Unsafe[A-Za-z0-9_]*|withUnsafe[A-Za-z0-9_]*|Unmanaged|withMemoryRebound|assumingMemoryBound|bindMemory)(?![A-Za-z0-9_])/, 'raw memory', 'let bytes = withUnsafeBytes(of: value) { Array($0) }'],
  [/(?<![A-Za-z0-9_])(?:dlsym|dlopen|NSClassFromString|NSSelectorFromString|NSProtocolFromString)(?![A-Za-z0-9_])|@_silgen_name|@_cdecl/, 'a symbol looked up by its name', 'let call = dlsym(nil, name)'],
];

/**
 * Imports that see past what SnowlightCore makes public: a testable import hands the kit
 * every internal name (ShownText's initializer, the stored forms), and the underscored
 * attributes (@_spi, @_private and the like) do the same. Anywhere in the kit and the
 * app, the tour included. (b)
 */
const PRIVATE_IMPORT = /(?<![A-Za-z0-9_])@(?:testable|_[A-Za-z0-9_]+)(?![A-Za-z0-9_])/;

/**
 * What else of the machine SnowlightCore could read: its files, the app's bundle, a
 * process or its arguments, a random value, the user's own folders. SnowlightCore is
 * handed its data and gives the same answer every time. (c)
 */
const CORE_HOST = [
  [/(?<![A-Za-z0-9_])(?:FileManager|FileHandle|InputStream|OutputStream|fopen|opendir)(?![A-Za-z0-9_])/, "the machine's files", 'let kept = FileManager.default.contents(atPath: path)'],
  [/(?<![A-Za-z0-9_])(?:Data|NSData|String|NSString)\s*\(\s*contentsOf(?:File)?\s*:/, 'a file read by its address', 'let kept = try? Data(contentsOf: address)'],
  [/(?<![A-Za-z0-9_])Bundle(?![A-Za-z0-9_])/, "the app's bundle", 'let id = Bundle.main.bundleIdentifier'],
  [/(?<![A-Za-z0-9_])(?:CommandLine|Process|NSTask|posix_spawn[A-Za-z_]*|popen)(?![A-Za-z0-9_])/, 'a process or its arguments', 'let said = CommandLine.arguments'],
  [/(?<![A-Za-z0-9_])(?:random|randomElement|shuffled|shuffle|arc4random[A-Za-z0-9_]*|SystemRandomNumberGenerator|UUID|drand48)(?![A-Za-z0-9_])/, 'a random value (the core gives the same answer every time)', 'let pick = Int.random(in: 0...9)'],
  [/(?<![A-Za-z0-9_])(?:homeDirectory[A-Za-z]*|temporaryDirectory|currentDirectoryPath|NSHomeDirectory[A-Za-z]*|NSTemporaryDirectory|NSUserName|NSFullUserName)(?![A-Za-z0-9_])/, "this machine's own folders or user", 'let folder = NSTemporaryDirectory()'],
];
/** The tests read their fixtures from their own bundle, and nothing else of the machine. (c) */
const TEST_HOST = [CORE_HOST[3], CORE_HOST[5]];
/** A string literal that is a path on this machine. In SnowlightCore and the tests. (c) */
const MACHINE_PATH_LITERAL = /^\/[A-Za-z]/;

/**
 * The types that hold text. SnowlightCore's public surface may name one of them in two
 * places only: the characters of a ShownText, which Shell/Shown.swift alone reads, and what
 * a person typed into search, which goes back to the system's own field. (b)
 */
const STRING_TYPE = /(?<![A-Za-z0-9_])(?:String|Substring|Character|StringProtocol|StaticString|NSString|NSMutableString|NSAttributedString|AttributedString|AttributedSubstring|LocalizedStringKey|LocalizedStringResource|UnicodeScalar|Unicode\s*\.\s*Scalar)(?![A-Za-z0-9_])/;
const PUBLIC_TEXT = new Set([
  'ios/SnowlightCore/Sources/SnowlightCore/Words/ShownText.swift drawnString',
  'ios/SnowlightCore/Sources/SnowlightCore/Screens/ShellModel.swift typed',
]);

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
    // The build setting, for every kit or none, and XcodeGen's target attribute; in a
    // settings file, a project file, a command line or a property list.
    for (const found of matches(values, TEAM_VALUE)) {
      hit('signing.team', path, found.line, `${found.match[1]} is given a team value`);
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
      for (const found of matches(swift.code, TYPED)) {
        if (!BINDING_BEFORE.test(swift.code.slice(0, found.match.index))) {
          hit('words.value', path, found.line, 'what was typed into search, read outside its binding ($query.typed)');
        }
      }
      // (b) The device, its clock, zone, language, files and settings: none of it is a
      // view's to read, so none of it can be drawn.
      for (const [pattern, what] of [...CLOCK_ZONE, ...VIEW_DEVICE]) {
        if (path === WINDOW_STYLE && what === SETTINGS_STORE) continue;
        for (const found of matches(swift.code, pattern)) hit('view.device', path, found.line, `a view reads the device: ${what}`);
      }
      // (b) Laid out from the room the window gives, never from the device or for one phone.
      for (const [pattern, what] of VIEW_LAYOUT) {
        for (const found of matches(swift.code, pattern)) hit('view.layout', path, found.line, `a view lays itself out by ${what}`);
      }
      for (const found of matches(swift.code, VIEW_NUMBER)) {
        if (Number(found.text.replace(/_/g, '')) >= SCREEN_SIZED) {
          hit('view.layout', path, found.line, `${found.text}: a length the size of a screen (lay out from the room the window gives)`);
        }
      }
      checkNetwork(path, swift, 'view.network', hit);
      checkUnsafe(path, swift, hit);
    }

    if (path.startsWith(KIT) || path.startsWith(APP)) {
      // (b) The kit and the app see SnowlightCore only through what it makes public.
      for (const found of matches(swift.code, PRIVATE_IMPORT)) {
        hit('view.import', path, found.line, `${found.text}: an attribute that sees past what SnowlightCore makes public`);
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
        for (const [pattern, what] of SHOWN_MAKERS) {
          for (const found of matches(swift.code, pattern)) hit('core.showntext', path, found.line, what);
        }
      }
      // (b) No text leaves SnowlightCore but a ShownText's characters and what was typed.
      checkPublicSurface(path, swift.code, hit);
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
      for (const [pattern, what] of [...CLOCK_ZONE, ...ENVIRONMENT]) {
        for (const found of matches(swift.code, pattern)) hit('core.device', path, found.line, `the device's clock or zone: ${what}`);
      }
      for (const [pattern, what] of CORE_HOST) {
        for (const found of matches(swift.code, pattern)) hit('core.device', path, found.line, `the machine: ${what}`);
      }
      checkMachinePaths(path, swift, 'core.device', hit);
      checkNetwork(path, swift, 'core.network', hit);
      checkUnsafe(path, swift, hit);
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

    if (path.startsWith(CORE_TESTS)) {
      // (c) In the tests, one file may read this machine's clock, zone and environment.
      if (!path.endsWith(`/${THIS_MACHINE}`)) {
        for (const [pattern, what] of [...CLOCK_ZONE, ...ENVIRONMENT]) {
          for (const found of matches(swift.code, pattern)) hit('tests.device', path, found.line, `${what} outside ${THIS_MACHINE}`);
        }
      }
      // No test starts a process, reads the user's folders or a path of the machine,
      // ThisMachineTests.swift included: the fixtures come from the tests' own bundle.
      for (const [pattern, what] of TEST_HOST) {
        for (const found of matches(swift.code, pattern)) hit('tests.device', path, found.line, `the machine: ${what}`);
      }
      checkMachinePaths(path, swift, 'tests.device', hit);
      // No test reads the network, ThisMachineTests.swift included.
      checkNetwork(path, swift, 'tests.network', hit);
      for (const found of matches(swift.code, /^[ \t]*(?:@[A-Za-z_]+[ \t]+)*import[ \t]+([^\n]*)$/m)) {
        const module = found.match[1].trim();
        if (!TEST_IMPORTS.includes(module)) hit('tests.import', path, found.line, `import ${module}: a test imports only ${TEST_IMPORTS.join(', ')}`);
      }
      // Every test runs on every machine: none is skipped, none is kept from a platform.
      for (const found of matches(swift.code, /(?<![A-Za-z0-9_])XCTSkip[A-Za-z]*/)) {
        hit('tests.skip', path, found.line, `${found.text}: a test that may be skipped`);
      }
      for (const found of matches(swift.code, /^[ \t]*#(?:if|elseif)(?![A-Za-z0-9_])/m)) {
        hit('tests.skip', path, found.line, 'a test file with #if: the same tests must run on Linux and on macOS');
      }
    }
  }

  checkAppWords(files, banned, hit);
  checkFamilies(files, hit);
  checkTestCount(files, hit);
  return hits;
}

/** The modules a test may import. */
const TEST_IMPORTS = ['XCTest', 'Foundation', 'SnowlightCore'];

/** (b) A way around the type system, in a view or in SnowlightCore. */
function checkUnsafe(path, swift, hit) {
  for (const [pattern, what] of UNSAFE) {
    for (const found of matches(swift.code, pattern)) hit('code.unsafe', path, found.line, `a way around the type system: ${what}`);
  }
}

/** (c) A string literal that is a path on this machine, such as its zone file. */
function checkMachinePaths(path, swift, rule, hit) {
  for (const literal of swift.literals) {
    if (MACHINE_PATH_LITERAL.test(literal.value)) hit(rule, path, literal.line, `a path on this machine: "${literal.value}"`);
  }
}

/** (c) The network: its types and calls, and any string literal that names an address. */
function checkNetwork(path, swift, rule, hit) {
  for (const [pattern, what] of NETWORK) {
    for (const found of matches(swift.code, pattern)) hit(rule, path, found.line, `the network: ${what}`);
  }
  for (const literal of swift.literals) {
    if (ADDRESS_LITERAL.test(literal.value)) hit(rule, path, literal.line, `the network: an address in a string, "${literal.value}"`);
  }
}

/**
 * (b) SnowlightCore's public surface hands out no text. Every declaration marked public
 * (or open) is read from the word to the start of its body or its value, across the lines
 * of its parameters, and must name no type that holds text, but for the two allowed:
 * `ShownText.drawnString` and `SearchQuery.typed`. A public property states its type, so
 * the check can read it. A public extension or protocol makes its members public without
 * the word, so neither is written in SnowlightCore. The cases of a public enum are public
 * too, so none carries text.
 */
function checkPublicSurface(path, code, hit) {
  const keyword = /(?<![A-Za-z0-9_.])(?:public|open(?=\s+(?:class|func|var|let|subscript|init|override|static|final|extension)(?![A-Za-z0-9_])))(?![A-Za-z0-9_])/g;
  for (const found of code.matchAll(keyword)) {
    const start = found.index;
    const alias = /^(?:public|open)\s+(?:[a-z]+\s+)*typealias(?![A-Za-z0-9_])/.test(code.slice(start, start + 120));
    let depth = 0;
    let end = start;
    for (; end < code.length; end += 1) {
      const c = code[end];
      if (c === '(' || c === '[') depth += 1;
      else if (c === ')' || c === ']') depth = Math.max(0, depth - 1);
      else if (depth === 0 && (c === '{' || c === '\n')) break;
      else if (depth === 0 && c === '=' && !alias && code[end + 1] !== '=' && !'!<>='.includes(code[end - 1] ?? '')) break;
    }
    const head = code.slice(start, end).replace(/\s+/g, ' ').trim();
    const line = lineAt(code, start);
    const kind = /(?:^|\s)(let|var|func|init|subscript|struct|enum|class|protocol|extension|typealias|actor|case|associatedtype)(?![A-Za-z0-9_])/.exec(head);
    if (kind === null) continue;
    if (kind[1] === 'extension' || kind[1] === 'protocol') {
      hit('core.publicstring', path, line, `a public ${kind[1]} makes its members public without the word; write public on each member: ${head}`);
      continue;
    }
    const named = /(?:let|var)\s+([A-Za-z_][A-Za-z0-9_]*)/.exec(head);
    const name = named === null ? '' : named[1];
    if ((kind[1] === 'let' || kind[1] === 'var') && !head.slice(named === null ? 0 : named.index).includes(':')) {
      hit('core.publicstring', path, line, `a public property must state its type, so this check can read it: ${head}`);
    }
    if (STRING_TYPE.test(head) && !PUBLIC_TEXT.has(`${path} ${name}`)) {
      hit('core.publicstring', path, line, `text in SnowlightCore's public surface: ${head}`);
    }
    if (kind[1] === 'enum') {
      const open = code.indexOf('{', end);
      if (open < 0) continue;
      let level = 0;
      let close = code.length;
      for (let k = open; k < code.length; k += 1) {
        if (code[k] === '{') level += 1;
        else if (code[k] === '}') {
          level -= 1;
          if (level === 0) {
            close = k;
            break;
          }
        }
      }
      const body = code.slice(open, close);
      for (const cased of matches(body, /^[ \t]*(?:indirect[ \t]+)?case[ \t]+[A-Za-z_][^\n]*$/m)) {
        if (STRING_TYPE.test(cased.text)) {
          hit('core.publicstring', path, lineAt(code, open) + cased.line - 1, `a case of a public enum carries text: ${cased.text.trim()}`);
        }
      }
    }
  }
}

/**
 * (c) The tests counted from their source equal the committed count, so a test that goes
 * missing is seen. Every XCTest test is an instance method `func test...()`; one marked
 * private or static is never run, so it is refused.
 */
function checkTestCount(files, hit) {
  let count = 0;
  let any = false;
  for (const [path, text] of files) {
    if (!path.startsWith(TEST_FILES) || !path.endsWith('.swift') || typeof text !== 'string') continue;
    any = true;
    const code = readSwift(text).code;
    count += matches(code, /(?<![A-Za-z0-9_])func\s+test[A-Za-z0-9_]*\s*\(\s*\)/).length;
    for (const found of matches(code, /(?<![A-Za-z0-9_])(?:private|fileprivate|static|class)\s+(?:@[A-Za-z_]+\s+)*func\s+test[A-Za-z0-9_]*\s*\(/)) {
      hit('tests.count', path, found.line, `a test method that XCTest never runs: ${found.text}`);
    }
  }
  if (!any) return;
  const committed = files.get(TEST_COUNT);
  if (typeof committed !== 'string') {
    hit('tests.count', TEST_COUNT, 0, `the committed count of tests is missing; the source holds ${count}`);
    return;
  }
  const numbers = committed.split('\n').map((line) => line.trim()).filter((line) => line !== '' && !line.startsWith('#'));
  if (numbers.length !== 1 || !/^[0-9]+$/.test(numbers[0])) {
    hit('tests.count', TEST_COUNT, 0, 'the count file must hold one whole number (lines that start with # are notes)');
  } else if (Number(numbers[0]) !== count) {
    hit('tests.count', TEST_COUNT, 0, `the committed count is ${numbers[0]} and the source holds ${count} tests`);
  }
}

/** A team value given to the build setting or to XcodeGen's attribute. (a) */
const TEAM_VALUE = /(DEVELOPMENT_TEAM|DevelopmentTeam)(?:\[[^\]\n]*\])?["']?[ \t]*(?:[=:]|<\/key>\s*<string>)[ \t]*["']?[A-Za-z0-9]{10}(?![A-Za-z0-9_])/;

/** Ways a workflow could reach a secret, or run with the rights that hold them. (a) */
const WORKFLOW_SECRETS = [
  [/(?<![A-Za-z0-9_-])secrets(?![A-Za-z0-9_-])/, 'the secrets context, in any form'],
  [/(?<![A-Za-z0-9_-])github\s*(?:\.\s*token|\[\s*["']token)/, "the run's own token"],
  [/GITHUB_TOKEN/, "the run's own token"],
  [/(?<![A-Za-z0-9_-])toJSON\s*\(\s*github\s*\)/, 'the whole github context, which holds the token'],
  [/(?<![A-Za-z0-9_-])pull_request_target(?![A-Za-z0-9_-])/, "a trigger that runs a fork's change with this repository's rights"],
];

/** The zone names that are UTC by another name. (c) */
const UTC_NAMES = /^:?(?:UTC|UCT|GMT|GMT0|GMT[+-]0|Zulu|Universal|Greenwich|Z|Etc\/(?:UTC|UCT|GMT|GMT0|GMT[+-]0|Zulu|Universal|Greenwich))$/i;

/**
 * (a) An iOS workflow: no secrets, standard runners only, GitHub's own three actions only,
 * read-only permissions. The file is read line by line, so every place the words runs-on,
 * uses, permissions and secrets appear is checked, wherever and however they are written:
 * a form this reader does not follow (a quoted key, a flow mapping, the word inside a
 * value) is refused, never passed. So are the YAML forms that could spell a key or a value
 * in other characters: an escape by number, and a tag.
 */
function checkWorkflow(path, values, hit) {
  for (const [pattern, what] of WORKFLOW_SECRETS) {
    for (const found of matches(values, pattern)) hit('workflow.secrets', path, found.line, `a workflow reaches for a secret: ${what}`);
  }
  for (const found of matches(values, /\\[xuU][0-9A-Fa-f]/)) {
    hit('workflow.syntax', path, found.line, 'an escape by number, which can spell any key or value in other characters');
  }
  for (const found of matches(values, /!!|!</)) {
    hit('workflow.syntax', path, found.line, 'a YAML tag, which can turn a value into another');
  }
  const lines = values.split('\n');
  const plain = (value) => value.trim().replace(/^(["'])(.*)\1$/, '$2');
  let permissions = null;
  lines.forEach((line, index) => {
    const number = index + 1;
    for (let k = 0; k < (line.match(/(?<![A-Za-z0-9_-])runs-on(?![A-Za-z0-9_-])/g) ?? []).length; k += 1) {
      const runner = /^\s*runs-on\s*:(.*)$/.exec(line);
      if (runner === null) {
        hit('runner.label', path, number, 'runs-on in a form this guard does not read (a quoted key, a flow mapping, or the word in a value)');
      } else if (!RUNNERS.includes(plain(runner[1]))) {
        hit('runner.label', path, number, `runs-on '${plain(runner[1])}' is not one of ${RUNNERS.join(', ')}`);
      }
    }
    for (let k = 0; k < (line.match(/(?<![A-Za-z0-9_-])uses(?![A-Za-z0-9_-])/g) ?? []).length; k += 1) {
      const action = /^\s*(?:-\s+)?uses\s*:(.*)$/.exec(line);
      if (action === null) {
        hit('workflow.uses', path, number, 'uses in a form this guard does not read (a quoted key, a flow mapping, or the word in a value)');
      } else if (!ACTIONS.includes(plain(action[1]))) {
        hit('workflow.uses', path, number, `uses '${plain(action[1])}' is not one of ${ACTIONS.join(', ')}`);
      }
    }
    if (/(?<![A-Za-z0-9_-])permissions(?![A-Za-z0-9_-])/.test(line) && !/^permissions\s*:/.test(line)) {
      hit('workflow.permissions', path, number, 'permissions set by a job, or written in a form this guard does not read');
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
  checkTestZones(path, lines, hit);
}

/**
 * (c) Every Swift test run in an iOS workflow states its zone in its own step: TZ and
 * SNOWLIGHT_EXPECT_ZONE, the same name, and not UTC by any name. Without the second,
 * ThisMachineTests has nothing to compare and the run would pass on a UTC clock.
 */
function checkTestZones(path, lines, hit) {
  const indent = (line) => line.length - line.trimStart().length;
  lines.forEach((line, index) => {
    if (!/(?<![A-Za-z0-9_-])swift\s+test(?![A-Za-z0-9_-])/.test(line)) return;
    // The step that holds the line: the nearest list item at or above it, not deeper.
    let first = index;
    while (first > 0 && !(/^\s*-\s/.test(lines[first]) && indent(lines[first]) <= indent(line))) first -= 1;
    let last = first + 1;
    while (last < lines.length && (lines[last].trim() === '' || indent(lines[last]) > indent(lines[first]))) last += 1;
    const step = lines.slice(first, last).join('\n');
    const value = (name) => {
      const found = new RegExp(`(?:^|[\\s"'{,])${name}["']?\\s*[:=]\\s*["']?([^\\s"',}]*)`, 'm').exec(step);
      return found === null ? null : found[1];
    };
    const zone = value('TZ');
    const expected = value('SNOWLIGHT_EXPECT_ZONE');
    if (zone === null || expected === null) {
      hit('workflow.zone', path, index + 1, 'a Swift test run whose step does not set both TZ and SNOWLIGHT_EXPECT_ZONE');
    } else if (zone !== expected) {
      hit('workflow.zone', path, index + 1, `a Swift test run with TZ ${zone} and SNOWLIGHT_EXPECT_ZONE ${expected}: they must be the same zone`);
    } else if (zone === '' || UTC_NAMES.test(zone)) {
      hit('workflow.zone', path, index + 1, `a Swift test run under '${zone}', which is UTC: the tests never run on a UTC clock`);
    }
  });
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
const CORE_STATE = 'ios/SnowlightCore/Sources/SnowlightCore/State/Sample.swift';
const SEARCH_VIEW = 'ios/SnowlightKit/Sources/SnowlightKit/Shell/SampleSearch.swift';
const LAYOUT_VIEW = 'ios/SnowlightKit/Sources/SnowlightKit/Layout/Sample.swift';
const WORKFLOW = '.github/workflows/ios-sample.yml';
const PROJECT = 'ios/project.yml';
/** Ten characters shaped like a team value, made here so that none is ever written down. */
const TEAM_SHAPE = 'X'.repeat(10);

const view = (body) => `import SwiftUI\nstruct Sample: View {\n    var body: some View {\n        ${body}\n    }\n}\n`;
const core = (body) => `import Foundation\nfunc sample() {\n    ${body}\n}\n`;
const test = (body) => `import XCTest\n@testable import SnowlightCore\n\nfinal class SampleTests: XCTestCase {\n    func testIt() throws {\n        _ = try GoldenFile.family("sample")\n        ${body}\n    }\n}\n`;
/** A Swift test step as the workflows write it: its own zone, stated twice, not UTC. */
const zonedTests = (tz = 'America/St_Johns', expected = tz) =>
  `      - name: Core tests\n        env:\n          TZ: ${tz}\n          SNOWLIGHT_EXPECT_ZONE: ${expected}\n        run: swift test --package-path ios/SnowlightCore`;
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
    changes.tests ?? zonedTests(),
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
  // What SnowlightCore may write: explicit initializers, its own initializer through
  // self, a zone by its name, a fixed moment, a value's own field named now, a public
  // surface with no text in it, a switch inside a public enum.
  [CORE_STATE, 'import Foundation\n\npublic struct Moment: Equatable {\n    public let now: Int64\n    public static let zero: Moment = Moment(0)\n    init(_ value: Int64) {\n        now = value\n    }\n    init(copy other: Moment) {\n        self.init(other.now)\n    }\n    public func later(by step: Int64) -> Moment {\n        Moment.init(now + step)\n    }\n}\n\npublic enum Look: Equatable {\n    case light\n    case dark(Int)\n    var note: String {\n        switch self {\n        case .light:\n            return String()\n        case .dark:\n            return String(repeating: "x", count: 1)\n        }\n    }\n}\n\nfunc moment(_ input: Moment, in name: String) -> Int64? {\n    guard let zone = TimeZone(identifier: name) else {\n        return nil\n    }\n    let start = Date(timeIntervalSince1970: 0)\n    return input.now + Int64(zone.secondsFromGMT(for: start))\n}\n'],
  [SCREEN_FILE, 'struct Sample {\n    let title: ShownText\n}\n'],
  // The two places SnowlightCore's public surface may hold text.
  [`${CORE_WORDS}ShownText.swift`, 'public struct ShownText: Equatable {\n    public let drawnString: String\n    init(_ characters: String) {\n        drawnString = characters\n    }\n}\n'],
  [`${CORE_SCREENS}ShellModel.swift`, 'public struct SearchQuery: Equatable {\n    public var typed: String\n    public init() {\n        typed = String()\n    }\n}\n'],
  [APP_WORDS_SWIFT, appWords('My School', 'Call it')],
  [APP_WORDS_LIST, appList('My School', 'Call it')],
  [TEST_FILE, test('let fixed = Date(timeIntervalSince1970: 1_800_000_000)\n        let zone = TimeZone(identifier: "America/St_Johns")\n        let folder = Bundle.module.resourceURL\n        _ = (fixed, zone, folder)')],
  [`ios/SnowlightCore/Tests/SnowlightCoreTests/${THIS_MACHINE}`, 'import Foundation\nimport XCTest\nlet zone = TimeZone.current\nlet env = ProcessInfo.processInfo.environment\n'],
  [TEST_COUNT, '# the tests\n1\n'],
  [`${GOLDEN}sample.json`, '{}\n'],
  [WORKFLOW, workflow()],
  [PROJECT, 'settings:\n  # CODE_SIGN_IDENTITY: Apple Development\n  CODE_SIGN_IDENTITY: "-"\n  DEVELOPMENT_TEAM: $(SNOWLIGHT_TEAM)\n'],
  ['ios/tools/build.sh', 'xcodebuild build CODE_SIGNING_ALLOWED=NO CODE_SIGN_IDENTITY=- ONLY_ACTIVE_ARCH=YES\n'],
  // The search field's binding, and the one view file that may hold the settings store.
  [SEARCH_VIEW, view('Color.clear.searchable(text: $query.typed, prompt: model.prompt.text)')],
  // Lengths below the size of a screen, and the width class, may be written in a view.
  [LAYOUT_VIEW, view('Color.clear.frame(width: 62, height: 299.5).padding(0.5).opacity(sizeClass == .regular ? 1 : 0x0)')],
  [WINDOW_STYLE, 'import SwiftUI\nfinal class AppearanceStore {\n    private let store: UserDefaults\n    init(store: UserDefaults = .standard) {\n        self.store = store\n    }\n}\n'],
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
  { name: 'Date() in a view', rules: ['view.device'], files: [[VIEW, view('let now = Date()')]] },
  { name: 'Date.now in a view', rules: ['view.device'], files: [[VIEW, view('let now = Date.now')]] },
  // A plain-string control given text the screen model did not hand over.
  { name: 'Button(option.choice.stored)', rules: ['words.value'], files: [[VIEW, view('Button(option.choice.stored) { }')]] },
  { name: "a navigation title that draws the phone's zone", rules: ['view.device'], files: [[VIEW, view('Color.clear.navigationTitle(TimeZone.current.identifier)')]] },
  { name: "an accessibility label from a color's text form", rules: ['words.value'], files: [[VIEW, view('ShownLabel(title).accessibilityLabel(Tokens.color(.ink, in: .light).hex)')]] },
  { name: "Button(ProcessInfo.processInfo.processName)", rules: ['view.device'], files: [[VIEW, view('Button(ProcessInfo.processInfo.processName) { }')]] },
  { name: 'what was typed, read outside its binding', rules: ['words.value'], files: [[VIEW, view('Button(query.typed) { }')]] },
  { name: 'what was typed, through a longer path than its binding', rules: ['words.value'], files: [[VIEW, view('Color.clear.searchable(text: $model.query.typed)')]] },
  { name: "a binding's raw value", rules: ['words.value'], files: [[VIEW, view('Button($query.typed.wrappedValue) { }')]] },
  { name: 'reflection over a model', rules: ['words.value'], files: [[VIEW, view('Button(Mirror(reflecting: model).children.first?.label ?? name) { }')]] },
  { name: 'the name of the function', rules: ['words.value'], files: [[VIEW, view('Button(#function) { }')]] },
  { name: 'the name of the file', rules: ['words.value'], files: [[VIEW, view('Button(#fileID) { }')]] },
  { name: 'a cast to text', rules: ['words.value'], files: [[VIEW, view('Button(value as? String ?? name) { }')]] },
  { name: 'a stored value read as it is, in the one file that holds the store', rules: ['view.device'], files: [[WINDOW_STYLE, 'import SwiftUI\nfinal class AppearanceStore {\n    private let store: UserDefaults\n    var said: String? {\n        store.string(forKey: name)\n    }\n}\n']] },
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
  { name: 'a ShownText made by .init in State/, with a word of its own', rules: ['core.showntext'], files: [['ios/SnowlightCore/Sources/SnowlightCore/State/Plant.swift', 'enum Plant {\n    static let open: ShownText = .init("Open today")\n}\n']] },
  { name: 'a ShownText made by .init in a screen model, from a stored form', rules: ['core.showntext'], files: [['ios/SnowlightCore/Sources/SnowlightCore/Screens/Plant.swift', 'struct Plant {\n    var shown: ShownText\n    mutating func set(_ choice: AppearanceOption) {\n        shown = .init(choice.stored)\n    }\n}\n']] },
  { name: 'ShownText passed around as a type', rules: ['core.showntext'], files: [[CORE_FILE, core('let kind = ShownText.self')]] },
  { name: 'another name for ShownText', rules: ['core.showntext'], files: [[CORE_FILE, 'typealias Words = ShownText\n']] },
  { name: 'an extension of ShownText outside Words/', rules: ['core.showntext'], files: [[CORE_FILE, 'extension ShownText {\n    static let lit = Self("Lit")\n}\n']] },
  // (b) Text in SnowlightCore's public surface.
  { name: "a choice's stored form made public", rules: ['core.publicstring'], files: [[CORE_STATE, 'public enum AppearanceChoice {\n    case system\n    public var stored: String {\n        switch self {\n        case .system:\n            return "system"\n        }\n    }\n}\n']] },
  { name: 'a public initializer that takes text', rules: ['core.publicstring'], files: [[CORE_STATE, 'public struct TokenColor {\n    public init?(hex: String) {\n        return nil\n    }\n}\n']] },
  { name: 'a public function that hands out text', rules: ['core.publicstring'], files: [[CORE_STATE, 'public func label(of value: Int) -> String {\n    String(value)\n}\n']] },
  { name: 'a public function that takes text over several lines', rules: ['core.publicstring'], files: [[`${CORE_WORDS}Plant.swift`, 'public func shown(\n    _ characters: Substring\n) -> ShownText {\n    ShownText(String(characters))\n}\n']] },
  { name: 'a public subscript that takes text', rules: ['core.publicstring'], files: [[CORE_STATE, 'public struct Table {\n    public subscript(key: String) -> Int {\n        0\n    }\n}\n']] },
  { name: 'a public enum whose raw values are text', rules: ['core.publicstring'], files: [[CORE_STATE, 'public enum Kind: String {\n    case lit\n}\n']] },
  { name: 'a case of a public enum that carries text', rules: ['core.publicstring'], files: [[CORE_STATE, 'public enum Said: Equatable {\n    case none\n    case note(String)\n}\n']] },
  { name: 'a public property whose type is left to the compiler', rules: ['core.publicstring'], files: [[CORE_STATE, 'public struct Plant {\n    public static let note = "Lit"\n}\n']] },
  { name: 'another public name for text', rules: ['core.publicstring'], files: [[CORE_STATE, 'public typealias Name = String\n']] },
  { name: 'a public extension', rules: ['core.publicstring'], files: [[CORE_STATE, 'public extension Look {\n    var name: String { String() }\n}\n']] },
  { name: 'a public protocol', rules: ['core.publicstring'], files: [[CORE_STATE, 'public protocol Named {\n    var name: String { get }\n}\n']] },
  { name: 'text kept public in the one file that may hold some', rules: ['core.publicstring'], files: [[`${CORE_SCREENS}ShellModel.swift`, 'public struct SearchQuery {\n    public var typed: String\n    public var said: String\n}\n']] },
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
  { name: 'Date() in a test', rules: ['tests.device'], files: [[TEST_FILE, test('let now = Date()')]] },
  { name: 'Date.now in a test', rules: ['tests.device'], files: [[TEST_FILE, test('let now = Date.now')]] },
  { name: 'getenv("TZ") in a test', rules: ['tests.device'], files: [[TEST_FILE, test('let zone = getenv("TZ")')]] },
  { name: 'NSTimeZone.local in a test', rules: ['tests.device'], files: [[TEST_FILE, test('let zone = NSTimeZone.local')]] },
  { name: 'a test that reads a web address', rules: ['tests.network'], files: [[TEST_FILE, test('let page = try Data(contentsOf: URL(string: "https://example.invalid/x")!)')]] },
  { name: 'a test that starts a download', rules: ['tests.network'], files: [[TEST_FILE, test('URLSession.shared.dataTask(with: request) { _, _, _ in }.resume()')]] },
  { name: 'a network address in ThisMachineTests', rules: ['tests.network'], files: [[`ios/SnowlightCore/Tests/SnowlightCoreTests/${THIS_MACHINE}`, 'let where = "wss://example.invalid/live"\n']] },
  { name: 'a test that imports the network', rules: ['tests.import'], files: [[TEST_FILE, `import FoundationNetworking\n${test('_ = 1')}`]] },
  { name: "a test that imports Apple's Network framework", rules: ['tests.import'], files: [[TEST_FILE, `import Network\n${test('_ = 1')}`]] },
  { name: 'a test that may be skipped', rules: ['tests.skip'], files: [[TEST_FILE, test('throw XCTSkip("later")')]] },
  { name: 'a test skipped on a condition', rules: ['tests.skip'], files: [[TEST_FILE, test('try XCTSkipIf(true)')]] },
  { name: 'a test kept from one platform', rules: ['tests.skip'], files: [[TEST_FILE, `#if os(Linux)\n${test('_ = 1')}#endif\n`]] },
  { name: 'a count of tests that is not the source', rules: ['tests.count'], files: [[TEST_COUNT, '# the tests\n2\n']] },
  { name: 'no count of tests', rules: ['tests.count'], files: [[TEST_COUNT, null]] },
  { name: 'a count file that is not one number', rules: ['tests.count'], files: [[TEST_COUNT, '1\n2\n']] },
  { name: 'a test method that is never run', rules: ['tests.count'], files: [[TEST_FILE, `${test('_ = 1')}extension SampleTests {\n    private func testHidden() {}\n}\n`]] },
  { name: 'a network address in SnowlightCore', rules: ['core.network'], files: [[CORE_FILE, core('let root = "https://live.invalid/v1/"')]] },
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
  { name: 'permissions set by a job under a quoted key', rules: ['workflow.permissions'], files: [[WORKFLOW, workflow({ run: 'echo ok\n    "permissions": write-all' })]] },
  // (a) The same, written in forms a line reader could miss.
  { name: 'a billed runner under a quoted key', rules: ['runner.label'], files: [[WORKFLOW, workflow().replace('    runs-on: macos-26', '    "runs-on": macos-26-xlarge')]] },
  { name: 'a billed runner in a flow mapping', rules: ['runner.label'], files: [[WORKFLOW, workflow().replace('    runs-on: macos-26', '    { runs-on: macos-26-xlarge }')]] },
  { name: 'another action in flow style', rules: ['workflow.uses'], files: [[WORKFLOW, workflow({ run: 'echo ok\n  two:\n    runs-on: ubuntu-24.04\n    steps: [{uses: actions/cache@v4}]' })]] },
  { name: 'every secret printed at once', rules: ['workflow.secrets'], files: [[WORKFLOW, workflow({ run: "echo '${{ toJSON(secrets) }}'" })]] },
  { name: "the run's own token", rules: ['workflow.secrets'], files: [[WORKFLOW, workflow({ run: 'echo ${{ github.token }}' })]] },
  { name: 'the whole github context', rules: ['workflow.secrets'], files: [[WORKFLOW, workflow({ run: "echo '${{ toJSON(github) }}'" })]] },
  { name: "a trigger with the repository's rights on a fork's change", rules: ['workflow.secrets'], files: [[WORKFLOW, workflow().replace('on: push', 'on: pull_request_target')]] },
  { name: 'a key spelled by number', rules: ['workflow.syntax'], files: [[WORKFLOW, workflow().replace('    runs-on: macos-26', '    "runs\\x2don": macos-26-xlarge')]] },
  { name: 'a YAML tag', rules: ['workflow.syntax'], files: [[WORKFLOW, workflow({ run: '!!binary bWFjb3MtMjYteGxhcmdl' })]] },
  // (c) Swift tests in CI always run in a stated zone that is not UTC.
  { name: 'a Swift test run that states no zone', rules: ['workflow.zone'], files: [[WORKFLOW, workflow({ tests: '      - run: swift test --package-path ios/SnowlightCore' })]] },
  { name: 'a Swift test run that states TZ only', rules: ['workflow.zone'], files: [[WORKFLOW, workflow({ tests: '      - name: Core tests\n        env:\n          TZ: America/St_Johns\n        run: swift test --package-path ios/SnowlightCore' })]] },
  { name: 'a Swift test run whose two zones differ', rules: ['workflow.zone'], files: [[WORKFLOW, workflow({ tests: zonedTests('America/St_Johns', 'Pacific/Kiritimati') })]] },
  { name: 'a Swift test run under UTC', rules: ['workflow.zone'], files: [[WORKFLOW, workflow({ tests: zonedTests('UTC') })]] },
  { name: 'a Swift test run under UTC by another name', rules: ['workflow.zone'], files: [[WORKFLOW, workflow({ tests: zonedTests('Etc/GMT') })]] },
  { name: 'a Swift test run with the zone in its command only', rules: ['workflow.zone'], files: [[WORKFLOW, workflow({ tests: '      - run: TZ=UTC SNOWLIGHT_EXPECT_ZONE=UTC swift test --package-path ios/SnowlightCore' })]] },
  // (a) A team value in the forms Xcode and XcodeGen also read.
  { name: 'DEVELOPMENT_TEAM for one kit with a team value', rules: ['signing.team'], files: [[PROJECT, `settings:\n  DEVELOPMENT_TEAM[sdk=iphoneos*]: ${TEAM_SHAPE}\n`]] },
  { name: "XcodeGen's DevelopmentTeam attribute with a team value", rules: ['signing.team'], files: [[PROJECT, `targets:\n  Snowlight:\n    attributes:\n      DevelopmentTeam: ${TEAM_SHAPE}\n`]] },
  { name: 'a team value in a property list', rules: ['signing.team'], files: [['ios/App/Signing.plist', `<dict>\n  <key>DevelopmentTeam</key>\n  <string>${TEAM_SHAPE}</string>\n</dict>\n`]] },
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

// Every entry of the lists of the clock, the zone, the environment, the network and the
// device is planted, by its own example, everywhere its list applies: in SnowlightCore, in a
// test, in a view. A pattern that stops matching its example fails the self-test.
for (const [, what, example] of CLOCK_ZONE) {
  SAMPLES.push({ name: `in SnowlightCore: ${what}`, rules: ['core.device'], files: [[CORE_FILE, core(example)]] });
  SAMPLES.push({ name: `in a test: ${what}`, rules: ['tests.device'], files: [[TEST_FILE, test(example)]] });
  SAMPLES.push({ name: `in a view: ${what}`, rules: ['view.device'], files: [[VIEW, view(example)]] });
}
for (const [, what, example] of ENVIRONMENT) {
  SAMPLES.push({ name: `in SnowlightCore: ${what}`, rules: ['core.device'], files: [[CORE_FILE, core(example)]] });
  SAMPLES.push({ name: `in a test: ${what}`, rules: ['tests.device'], files: [[TEST_FILE, test(example)]] });
}
for (const [, what, example] of NETWORK) {
  SAMPLES.push({ name: `in SnowlightCore: ${what}`, rules: ['core.network'], files: [[CORE_FILE, core(example)]] });
  SAMPLES.push({ name: `in a test: ${what}`, rules: ['tests.network'], files: [[TEST_FILE, test(example)]] });
  SAMPLES.push({ name: `in a view: ${what}`, rules: ['view.network'], files: [[VIEW, view(example)]] });
}
for (const [, what, example] of VIEW_DEVICE) {
  SAMPLES.push({ name: `in a view: ${what}`, rules: ['view.device'], files: [[VIEW, view(example)]] });
}
for (const [, what, example] of VIEW_LAYOUT) {
  SAMPLES.push({ name: `in a view: ${what}`, rules: ['view.layout'], files: [[VIEW, view(example)]] });
}
SAMPLES.push(
  { name: 'a view sized for the iPhone 17 Pro', rules: ['view.layout'], files: [[LAYOUT_VIEW, view('Color.clear.frame(width: 402, height: 874)')]] },
  { name: 'a screen-sized length written with a fraction and a separator', rules: ['view.layout'], files: [[LAYOUT_VIEW, view('Color.clear.frame(maxWidth: 1_000.5)')]] },
);
for (const [, what, example] of UNSAFE) {
  SAMPLES.push({ name: `in SnowlightCore: ${what}`, rules: ['code.unsafe'], files: [[CORE_FILE, core(example)]] });
  SAMPLES.push({ name: `in a view: ${what}`, rules: ['code.unsafe'], files: [[VIEW, view(example)]] });
}
for (const [, what, example] of CORE_HOST) {
  SAMPLES.push({ name: `in SnowlightCore: ${what}`, rules: ['core.device'], files: [[CORE_FILE, core(example)]] });
}
for (const [, what, example] of TEST_HOST) {
  SAMPLES.push({ name: `in a test: ${what}`, rules: ['tests.device'], files: [[TEST_FILE, test(example)]] });
  SAMPLES.push({ name: `in ThisMachineTests: ${what}`, rules: ['tests.device'], files: [[`ios/SnowlightCore/Tests/SnowlightCoreTests/${THIS_MACHINE}`, `import Foundation\nfunc sample() {\n    ${example}\n}\n`]] });
}
// The forms the second look at M0a's guards planted and saw pass: each by itself.
SAMPLES.push(
  { name: 'text made by an initializer whose type is left to the compiler, in a view', rules: ['words.value'], files: [[VIEW, view('let said: String = .init(42)\n        return Button(said) { }')]] },
  { name: 'a word spelled from numbers, in a view', rules: ['words.value'], files: [[VIEW, view('Button(Character(Unicode.Scalar(UInt8(65))).uppercased()) { }')]] },
  { name: 'a testable import of SnowlightCore in the kit', rules: ['view.import'], files: [[VIEW, `@testable import SnowlightCore\n${view('ShownLabel(model.title)')}`]] },
  { name: 'a testable import of SnowlightCore in the app', rules: ['view.import'], files: [[APP + 'Sample.swift', '@testable import SnowlightCore\nimport SwiftUI\n']] },
  { name: 'a testable import of SnowlightCore in the tour', rules: ['view.import'], files: [[TOUR, '#if DEBUG\n@testable import SnowlightCore\nlet key = "tour.name"\n#endif\n']] },
  { name: 'an SPI import of SnowlightCore in the kit', rules: ['view.import'], files: [[VIEW, `@_spi(Words) import SnowlightCore\n${view('ShownLabel(model.title)')}`]] },
  { name: 'a path on this machine in SnowlightCore', rules: ['core.device'], files: [[CORE_FILE, core('let zone = "/etc/localtime"')]] },
  { name: 'a path on this machine in a test', rules: ['tests.device'], files: [[TEST_FILE, test('let zone = FileManager.default.contents(atPath: "/etc/localtime")')]] },
);
// The forms the first critic of M0a planted in an export and saw pass: each by itself.
for (const example of [
  'let now = Date.init()', 'let now = NSDate()', 'let zone = NSTimeZone.local', 'let zone = NSTimeZone.system',
  'let now = CFAbsoluteTimeGetCurrent()', 'let now = Date.timeIntervalSinceReferenceDate',
  'let calendar = NSCalendar(identifier: .gregorian)',
]) {
  SAMPLES.push({ name: `in SnowlightCore, as planted: ${example}`, rules: ['core.device'], files: [[CORE_FILE, core(example)]] });
}

/** The rules, each of which at least one sample must hold. */
const RULES = [
  'signing.file', 'signing.profile', 'signing.identity', 'signing.team',
  'workflow.secrets', 'runner.label', 'workflow.uses', 'workflow.permissions', 'workflow.syntax', 'workflow.zone',
  'words.literal', 'words.names', 'words.text', 'words.table', 'words.drawn', 'words.system', 'words.value',
  'view.device', 'view.layout', 'view.network', 'view.import', 'code.unsafe',
  'core.showntext', 'core.screenliteral', 'core.publicstring', 'language.file',
  'appwords.list', 'appwords.format', 'appwords.banned', 'appwords.style',
  'core.import', 'core.device', 'core.network', 'core.formatter', 'core.pattern', 'core.crash',
  'tests.device', 'tests.network', 'tests.import', 'tests.skip', 'tests.count',
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
  const needed = [SHOWN, NAMES, WINDOW_STYLE, APP_WORDS_SWIFT, APP_WORDS_LIST, TEST_COUNT, 'ios/project.yml', `${WORKFLOWS}ios-core.yml`, `${WORKFLOWS}ios-app.yml`];
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
