import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { describe, it } from 'node:test';

import { BLOCKLIST } from '../src/usernames/blocklist.ts';
import {
  MAX_ADMIN_TERMS,
  SCAN_PAGE,
  checkUsername,
  scanPage,
  readings,
  renameTerm,
  squeeze,
  termScanner,
  tokens,
  usernameFormat,
  usernameSkeleton,
  usernameSkeletons,
} from '../src/usernames/check.ts';

/** Realistic teen usernames and innocents that contain a listed term inside another word. */
const GOOD: string[] = JSON.parse(
  readFileSync(new URL('./good-usernames.json', import.meta.url), 'utf8'),
) as string[];

const LEET_OUT: Record<string, string> = { o: '0', i: '1', e: '3', a: '4', s: '5', t: '7' };
const leet = (t: string) => [...t].map((c) => LEET_OUT[c] ?? c).join('');
const stretch = (t: string) => t.replace(/[aeiou]/, (v) => v.repeat(4));
const spaced = (t: string) => [...t].join('_');
const reversed = (t: string) => [...t].reverse().join('');
const fits = (name: string) => usernameFormat(name) === null;

/** Spelling tricks on every list term, built from the data file (no term is written here). */
function badCorpus(): string[] {
  const out = new Set<string>();
  const noReverse = new Set<string>(BLOCKLIST.noReverse);
  for (const term of BLOCKLIST.substring) {
    const variants = [term, leet(term), stretch(term), `zz${term}_99`, `${leet(term)}42`];
    if (term.length <= 10) variants.push(spaced(term));
    if (term.length >= 4 && !noReverse.has(term)) variants.push(reversed(term));
    variants.push(stretch(leet(term)).toUpperCase());
    for (const v of variants) if (fits(v)) out.add(v);
  }
  for (const term of BLOCKLIST.token) {
    for (const v of [
      term,
      `big_${term}`,
      `${term}_99`,
      `${term}42`,
      `x_${leet(term)}`,
      `${stretch(term)}_x`,
      // One letter at a time inside a longer name, and split once.
      `my_${spaced(term)}`,
      `${spaced(term)}_99`,
      `my_${term.slice(0, -1)}_${term.slice(-1)}`,
    ])
      if (fits(v)) out.add(v);
  }
  for (const v of [
    ...allowSplits(),
    ...yearLeet(),
    ...rawVariants(),
    ...hostVariants(),
    ...lookAlikes(),
  ])
    if (fits(v)) out.add(v);
  return [...out];
}

const PREFIXES = ['big', 'my', 'gang', 'love', 'hot', 'eat', 'i', 'huge'];

/** Each allowlisted word that holds a term, and the word's own letters on each side of it. */
function hosts(): { word: string; term: string; left: number; right: number }[] {
  const out = [];
  for (const word of BLOCKLIST.allow)
    for (const term of BLOCKLIST.substring) {
      const at = word.indexOf(term);
      if (at >= 0) out.push({ word, term, left: at, right: word.length - at - term.length });
    }
  return out;
}

/**
 * An allowlisted word with letters run on where it has few of its own beside
 * the term (fewer than 3 on that side, or 3 or fewer in all): a prefix before
 * gangrape-style, or letters after (dicke + xx). The term then reads as itself.
 */
function hostVariants(): string[] {
  const out: string[] = [];
  for (const { word, left, right } of hosts()) {
    const short = left + right <= 3;
    const names = [
      ...(short || left < 3 ? PREFIXES.map((p) => p + word) : []),
      ...(short || right < 3 ? [`${word}xx`, `${word}ing`] : []),
    ];
    // A longer allowlisted word inside the name (drape + ry) is innocent.
    for (const name of names)
      if (!BLOCKLIST.allow.some((w) => w.length > word.length && name.includes(w))) out.push(name);
  }
  return out;
}

/** l for i (bltch), ph for an f that starts a term, and reserved words with rn for m or l for i. */
function lookAlikes(): string[] {
  const out: string[] = [];
  for (const term of BLOCKLIST.substring) {
    if (term.includes('i') && !term.includes('l')) {
      const v = term.replace(/i/g, 'l');
      if (!BLOCKLIST.lookAlikeAllow.some((w) => v.includes(w))) out.push(v, `x_${v}`, `${v}99`);
    }
    if (term.startsWith('f')) out.push(`ph${term.slice(1)}`, `big_ph${term.slice(1)}`);
  }
  return out;
}

/**
 * Every allowlisted word split with underscores so that a term it holds stands
 * apart (s_ before it, _ake after it), or spelled one letter at a time.
 */
function allowSplits(): string[] {
  const out: string[] = [];
  for (const word of BLOCKLIST.allow)
    for (const term of BLOCKLIST.substring) {
      const at = word.indexOf(term);
      if (at < 0) continue;
      const [before, after] = [word.slice(0, at), word.slice(at + term.length)];
      for (const v of [
        [before, term, after],
        [before, term + after],
        [before + term, after],
        [spaced(before), term, after],
      ]) {
        const parts = v.filter((p) => p.length > 0);
        // A part that still holds the term inside another allowlisted word (drape_ry) is innocent.
        const innocent = parts.some((p) =>
          BLOCKLIST.allow.some((w) => w.includes(term) && p.includes(w)),
        );
        if (!innocent && parts.length > 1) out.push(parts.join('_'));
      }
      out.push(spaced(word));
    }
  return out;
}

/** Terms with a year's digits for the letters a 19xx spells (1 i, 9 g, then any leet digit). */
function yearLeet(): string[] {
  const digitFor: Record<string, string> = {
    o: '0',
    i: '1',
    e: '3',
    a: '4',
    s: '5',
    t: '7',
    b: '8',
    g: '9',
  };
  const out: string[] = [];
  for (const term of BLOCKLIST.substring)
    for (let at = term.indexOf('ig'); at !== -1; at = term.indexOf('ig', at + 1)) {
      const [x, y] = [digitFor[term[at + 2] ?? ''], digitFor[term[at + 3] ?? '']];
      if (x === undefined || y === undefined) continue;
      const [before, after] = [term.slice(0, at), term.slice(at + 4)];
      const v = `${before}19${x}${y}${after}`;
      out.push(v, `x${v}x`, `xx_${v}_xx`, `${v}s`);
      // One underscore from a part of one or two letters: n_1993_r.
      if (before.length >= 1 && before.length <= 2 && after.length > 0)
        out.push(`${before}_19${x}${y}_${after}`);
    }
  return out;
}

/** The number codes with underscores in them and around them. */
function rawVariants(): string[] {
  return BLOCKLIST.raw.flatMap((code) => [
    code,
    spaced(code),
    `${code.slice(0, 2)}_${code.slice(2)}`,
    `x_${code.slice(0, 2)}_${code.slice(2)}_x`,
    `snow${code}`,
  ]);
}

describe('username format', () => {
  it('takes 3-20 of a-z, 0-9 and underscore, any case', () => {
    for (const ok of ['abc', 'Snow_Day_2026', 'a1b', 'x'.repeat(20)])
      assert.equal(usernameFormat(ok), null, ok);
  });

  it('refuses the wrong length, characters, all digits and stray underscores', () => {
    assert.equal(usernameFormat('ab'), 'username_length');
    assert.equal(usernameFormat('x'.repeat(21)), 'username_length');
    assert.equal(usernameFormat('snow day'), 'username_chars');
    assert.equal(usernameFormat('snow-day'), 'username_chars');
    assert.equal(usernameFormat('snöday'), 'username_chars');
    assert.equal(usernameFormat('12345'), 'username_digits');
    assert.equal(usernameFormat('_snow'), 'username_underscores');
    assert.equal(usernameFormat('snow_'), 'username_underscores');
    assert.equal(usernameFormat('snow__day'), 'username_underscores');
  });
});

describe('readings', () => {
  it('reads leet both ways for 1, and the letters alone', () => {
    assert.deepEqual(readings('b1g_5n0w').sort(), ['bgnw', 'bigsnow', 'blgsnow']);
  });

  it('leaves a year standing apart alone', () => {
    assert.deepEqual(readings('emma2009'), ['emma']);
    assert.deepEqual(readings('snow_1999'), ['snow']);
  });

  it('reads a 19xx next to a letter as letters too', () => {
    assert.ok(readings('x1960').includes('xiggo'));
    assert.ok(readings('1960x').includes('iggox'));
  });

  it('reads each 1 as i or l on its own', () => {
    const read = readings('b11l');
    for (const r of ['biil', 'bill', 'blil', 'blll']) assert.ok(read.includes(r), r);
  });

  it('cuts runs and splits tokens', () => {
    assert.equal(squeeze('fuuuuun', 1), 'fun');
    assert.equal(squeeze('boooooks', 2), 'books');
    assert.deepEqual(tokens('snow_day99fun').sort(), ['day', 'day99fun', 'fun', 'snow']);
  });
});

describe('blocklist', () => {
  it('names its source and license', () => {
    const text = readFileSync(new URL('../src/usernames/blocklist.ts', import.meta.url), 'utf8');
    assert.match(text, /LDNOOBW/);
    assert.match(text, /CC BY 4\.0/);
    assert.match(text, /5faf2ba42d7b1c0977169ec3611df25a3c08eb13/);
  });

  it('accepts good usernames with a year standing apart or a 20xx', () => {
    const names = GOOD.filter((n) => /^[a-z]+$/.test(n) && n.length <= 14);
    assert.ok(names.length >= 40);
    for (const name of names)
      for (const year of [1960, 1985, 1999, 2009, 2013, 2026])
        for (const v of [`${name}_${year}`, ...(year >= 2000 ? [`${name}${year}`] : [])])
          assert.equal(checkUsername(v, { adminName: 'Olivia' }), null, v);
  });

  it(`accepts all ${GOOD.length} good usernames`, () => {
    assert.ok(GOOD.length >= 300);
    for (const name of [
      ...GOOD,
      'cassidy',
      'glasshopper',
      'bassist_99',
      'sussex_snow',
      'grapejuice',
      'analyst_kid',
      'assess_this',
      'booboo_bear',
      'grape_juice',
      'mood_ring',
      'teem',
    ])
      assert.equal(checkUsername(name, { adminName: 'Olivia' }), null, name);
  });

  it('accepts every allowlisted word standing as itself', () => {
    for (const { word } of hosts())
      for (const name of [word, `x_${word}`, `${word}_x`, `${word}9`, `the_${word}_99`])
        if (fits(name)) assert.equal(checkUsername(name, { adminName: 'Olivia' }), null, name);
  });

  it('excuses nothing when an allowlisted word runs into other letters where it has few of its own', () => {
    const names = hostVariants();
    assert.ok(names.length >= 200, `${names.length} names`);
    const missed = names.filter((name) => fits(name) && checkUsername(name) === null);
    assert.deepEqual(missed, [], `${missed.length} of ${names.length} got through`);
  });

  it('refuses the n-word backwards and with l for i, and years one underscore from a letter', () => {
    // The file lists the full form backwards; its reversal is the word itself.
    const back = BLOCKLIST.substring.find((t) => t.startsWith('regg'))!;
    assert.ok(back !== undefined);
    const term = reversed(back);
    for (const name of [
      back,
      `${back}s`,
      `${back}_lol`,
      spaced(back),
      back.replace('i', 'ii'),
      back.slice(1).replace('e', 'a'),
      term.replace('i', 'l'),
      `${term.slice(0, 4).replace('i', 'l')}uh`,
      `${term[0]}_19${term.slice(4, 5) === 'e' ? '93' : '99'}_${term.slice(-1)}`,
    ])
      assert.equal(checkUsername(name)?.problem, 'username_blocked', name);
  });

  it('refuses every spelling trick on every term', () => {
    const corpus = badCorpus();
    assert.ok(corpus.length >= 200, `${corpus.length} bad names`);
    const missed = corpus.filter((name) => checkUsername(name) === null);
    assert.deepEqual(missed, [], `${missed.length} of ${corpus.length} got through`);
  });

  it('excuses a term only inside an allowlisted word typed in letters', () => {
    const term = BLOCKLIST.substring.find((t) => 'scunthorpe'.includes(t))!;
    assert.ok(term !== undefined);
    assert.equal(checkUsername('scunthorpe'), null);
    assert.equal(checkUsername('class_clown'), null);
    assert.notEqual(checkUsername(`scunthorpe_${term}`), null);
    assert.notEqual(checkUsername(`${term}_scunthorpe`), null);
    assert.notEqual(checkUsername('s_cunthorpe'), null);
    assert.notEqual(checkUsername('scunthorpe'.replace('o', '0')), null);
  });

  it('keeps no allowlisted word that holds a term forwards from the slur kind', () => {
    // Words holding these stems only backwards (logging) stay; forwards they are refused.
    for (const stem of ['nigg', 'kike', 'negro'])
      for (const word of BLOCKLIST.allow) assert.ok(!word.includes(stem), word);
  });

  it('refuses number codes split by underscores', () => {
    for (const code of BLOCKLIST.raw)
      for (const v of [`${code}_x`, `x_${spaced(code)}`, `${code.slice(0, 2)}_${code.slice(2)}_x`])
        assert.equal(checkUsername(v)?.problem, 'username_blocked', v);
    assert.equal(checkUsername('snow_88'), null);
    assert.equal(checkUsername('jake1988'), null);
  });

  it('applies the admin extra terms and allowlist on top of the file', () => {
    assert.equal(checkUsername('frostbiter'), null);
    assert.equal(
      checkUsername('frostbiter', { extra: { substring: ['stbit'] } })?.problem,
      'username_blocked',
    );
    assert.equal(
      checkUsername('frost_bite', { extra: { token: ['bite'] } })?.problem,
      'username_blocked',
    );
    assert.equal(checkUsername('frostbite', { extra: { token: ['bite'] } }), null);
    const term = BLOCKLIST.substring.find((t) => t.length >= 4)!;
    assert.equal(checkUsername(`zz${term}zz`, { extra: { allow: [`zz${term}zz`] } }), null);
    assert.notEqual(checkUsername(`zz_${term}zz`, { extra: { allow: [`zz${term}zz`] } }), null);
    for (const v of ['snow_1312', 'snow_13_12', '1_3_1_2_x'])
      assert.equal(checkUsername(v, { extra: { raw: ['1312'] } })?.problem, 'username_blocked', v);
    assert.equal(checkUsername('snow_1312'), null);
  });
});

describe('the skeletons a taken-away name is held by', () => {
  it('give the same letters with any digits or underscores one shared skeleton', () => {
    const held = usernameSkeletons('mean_name');
    for (const name of [
      'meanname1',
      '9meanname',
      'mean_name_2010',
      'Mean_Name_99',
      'm3anname7',
      'meannname',
    ])
      assert.ok(
        usernameSkeletons(name).some((k) => held.includes(k)),
        `${name}: ${usernameSkeletons(name).join(',')}`,
      );
    assert.equal(usernameSkeletons('mean_name')[0], usernameSkeleton('mean_name'));
    assert.ok(!usernameSkeletons('kind_name').some((k) => held.includes(k)));
  });

  it('turn into the word a rename blocks: letters alone, runs cut to one', () => {
    assert.deepEqual(renameTerm('Mean_Name_99'), { term: 'meaname', kind: 'substring' });
    assert.deepEqual(renameTerm('zqx_7'), { term: 'zqx', kind: 'token' });
    assert.equal(renameTerm('ab_12'), null);
  });
});

describe('terms glued to a common word', () => {
  const allowed = new Set<string>(BLOCKLIST.allow);
  /** Every term with every affix before it, after it, both, two in a row, and with digits, from the data file. */
  function glued(terms: readonly string[]): string[] {
    const out = new Set<string>();
    const affixes = BLOCKLIST.tokenAffixes;
    for (const term of terms)
      for (const [i, affix] of affixes.entries()) {
        const other = affixes[(i * 7 + 3) % affixes.length]!;
        for (const name of [
          affix + term,
          term + affix,
          affix + term + other,
          affix + other + term,
          `${affix}${term}${i % 10}`,
          `${i % 10}${affix}${term}`,
          `${affix}${leet(term)}`,
          `${stretch(term)}${affix}`,
          `${affix}${term}_${i}`,
        ])
          // A part that is an allowlisted word (ur+anus) is innocent.
          if (fits(name) && !name.split(/[_0-9]+/).some((part) => allowed.has(part))) out.add(name);
      }
    return [...out];
  }

  it('refuses every whole-token term typed with a common affix or word', () => {
    const names = glued(BLOCKLIST.token);
    assert.ok(names.length > 5000, String(names.length));
    const missed = names.filter((n) => checkUsername(n) === null);
    assert.equal(missed.length, 0, missed.slice(0, 10).join(' '));
  });

  it('refuses every reserved staff word typed with a common affix or word', () => {
    const names = glued(BLOCKLIST.reservedTokens);
    const missed = names.filter((n) => checkUsername(n)?.problem !== 'username_reserved');
    assert.deepEqual(missed, []);
  });

  it('still passes an allowlisted word typed with an affix, and words that merely start like one', () => {
    for (const name of [
      'analog',
      'my_analog',
      'uranus',
      'therapist',
      'moodboy',
      'teammate',
      'modern_kid',
    ])
      assert.equal(checkUsername(name), null, name);
  });
});

describe('reserved names', () => {
  it('refuses staff words and the admin name in any case or disguise', () => {
    for (const name of [
      'admin',
      'ADMIN',
      '4dm1n',
      'a_d_m_i_n',
      'admiiin',
      'moderator99',
      'mod',
      'Snowlight',
      'snowlightmap',
      'the_admin',
      'snowlight_official',
      'official_olivia',
      'staff_member',
      'support',
      'root',
      'null',
      'undefined',
      'everyone',
      'here',
      'system',
      'team',
      'help',
      'olivia',
      'Olivia',
      '0livia',
      'ol1via',
      'deleted_user',
      'theadmin',
      'xadminx',
      'b_admin_ton',
      'snowlightofficial',
      'the_snowlight_kid',
      'the_mod',
      'mod_bob',
      'm_o_d_squad',
      'support_team',
      'helpdesk',
      'team_x',
      'real_olivia',
      'x_olivia',
      'oliviaaa',
      'theolivia',
      'player_0042',
      'p1ayer_0042',
      'player0042',
      'playerr_0042',
      'pl4yer_7',
    ])
      assert.equal(
        checkUsername(name, { adminName: 'Olivia' })?.problem,
        'username_reserved',
        name,
      );
  });

  it('leaves words that only contain one', () => {
    for (const name of [
      'mood',
      'badminton',
      'modern_kid',
      'helpful_hana',
      'teamwork',
      'root_beer',
      'olivia_smith',
      'oliviasmith',
      'heres_johnny',
      'badminton',
      'badminton_ace',
      'player_one',
    ])
      assert.equal(checkUsername(name, { adminName: 'Olivia' }), null, name);
  });
});

describe('reserved names in any spelling', () => {
  const words = [...new Set([...BLOCKLIST.reserved, ...BLOCKLIST.reservedTokens])];
  const stretchAllow = new Set<string>(BLOCKLIST.reservedStretchAllow);
  /** Each letter doubled and tripled in turn. */
  const repeats = (word: string) =>
    [...word].flatMap((c, i) =>
      [2, 3].map((n) => word.slice(0, i) + c.repeat(n) + word.slice(i + 1)),
    );

  it('refuses every reserved word with repeated letters, alone and as a part', () => {
    const tokens = new Set<string>(BLOCKLIST.reservedTokens);
    let checked = 0;
    for (const word of words)
      for (const v of repeats(word)) {
        if (stretchAllow.has(v)) continue;
        const names = [v, ...(tokens.has(word) ? [`the_${v}`, `real_${v}`, `${v}_x`] : [])];
        for (const name of names)
          if (fits(name)) {
            checked++;
            assert.equal(
              checkUsername(name, { adminName: 'Olivia' })?.problem,
              'username_reserved',
              name,
            );
          }
      }
    assert.ok(checked >= 300, `${checked} names`);
  });

  it('refuses the long ones backwards, with rn for m and with l for i', () => {
    for (const word of BLOCKLIST.reservedSubstring) {
      for (const name of [reversed(word), `${reversed(word)}_x`, word.replace('i', 'l')])
        assert.equal(checkUsername(name)?.problem, 'username_reserved', name);
      if (word.includes('m'))
        assert.equal(checkUsername(word.replace('m', 'rn'))?.problem, 'username_reserved', word);
    }
    for (const name of ['adrnin', 'admln', 'nimda', 'rotaredom', 'thgilwons', 'snowllght', 'tearn'])
      assert.equal(checkUsername(name)?.problem, 'username_reserved', name);
  });

  it('leaves the real words a stretched reserved word would catch', () => {
    for (const name of [...BLOCKLIST.reservedStretchAllow, 'the_mood', 'mood_ring', 'kevin_turner'])
      assert.equal(checkUsername(name, { adminName: 'Olivia' }), null, name);
  });
});

describe('scan for a new term', () => {
  it('scans a number code', () => {
    const scan = termScanner('13_12', 'raw');
    assert.equal(scan('snow_13_12'), true);
    assert.equal(scan('snow_1313'), false);
  });

  it('lists the names a new term catches, honoring the allowlist', () => {
    const scan = termScanner('bite', 'substring', ['frostbite']);
    assert.equal(scan('big_bite'), true);
    assert.equal(scan('b1t3_me'), true);
    assert.equal(scan('frostbite'), false);
    assert.equal(scan('emma_snow'), false);
    const token = termScanner('bite', 'token');
    assert.equal(token('frostbite'), false);
    assert.equal(token('frost_bite'), true);
  });
});

/**
 * The slowest shapes of name anyone can register: many 1s and ls (each read
 * both ways) and many one-letter parts (each a start in the trie).
 */
function adversarial(count: number): string[] {
  const shapes = [
    (a: string, b: string) => `${a}_1_${b}_1_c_1_d_1_e_ff`,
    (a: string, b: string) => `1_1_1_1_${a}_${b}_c_d_e_fg`,
    (a: string, b: string) => `l1l1_1l1l_${a}_${b}_z_w_qr`,
    (a: string, b: string) => `n1_9_9_3_${a}_1_1_1_1${b}`,
    (a: string, b: string) => `${a}1${b}1c1d1e1f1g1h1i1j1`,
  ];
  const letters = 'abcdefghjkmnopqrstuvwxyz';
  return Array.from({ length: count }, (_, i) =>
    shapes[i % shapes.length]!(letters[i % 24]!, letters[(i * 7 + 3) % 24]!),
  ).filter(fits);
}

/**
 * One child process, a fresh isolate as a Worker gets: the startup compile
 * and warm-up, then the admin's terms (MAX_ADMIN_TERMS of every kind, each of
 * the longest length) filed and a full scan page of `names` checked, as the
 * first request does. Prints the times in ms.
 */
function coldRun(names: readonly string[]): { startup: number; page: number; count: number } {
  const script = `
    import { checkUsername, prepareBlocklist, scanPage, MAX_ADMIN_TERMS, MAX_USERNAME } from '../src/usernames/check.ts';
    const names = JSON.parse(process.argv[1]);
    let seed = 99;
    const word = (p) => {
      let out = p;
      while (out.length < MAX_USERNAME) {
        seed = (seed * 1103515245 + 12345) % 2147483648;
        out += 'abcdefghijklmnopqrstuvwxyz'[seed % 26];
      }
      return out;
    };
    const terms = (p) => Array.from({ length: MAX_ADMIN_TERMS }, () => word(p));
    const raw = Array.from({ length: MAX_ADMIN_TERMS }, (_, i) => String(100000 + i * 7919) + 'x');
    let t = performance.now();
    prepareBlocklist(true);
    const startup = performance.now() - t;
    t = performance.now();
    const extra = { substring: terms('zq'), token: terms('tk'), allow: terms('al'), raw };
    // As the scan endpoint does: the names its work budget takes, after compiling the terms.
    const count = scanPage(names, extra);
    for (let i = 0; i < count; i++) checkUsername(names[i], { adminName: 'olivia', extra });
    console.log(JSON.stringify({ startup, page: performance.now() - t, count }));`;
  const out = execFileSync(
    process.execPath,
    [
      '--experimental-strip-types',
      '--no-warnings',
      '--input-type=module',
      '-e',
      script,
      JSON.stringify(names),
    ],
    { cwd: new URL('.', import.meta.url), encoding: 'utf8' },
  );
  return JSON.parse(out.trim()) as { startup: number; page: number; count: number };
}

describe('speed', () => {
  it('checks a name in well under 1 ms once warm, with admin terms, the slowest names too', () => {
    const slow = adversarial(200);
    const names = [...GOOD, ...badCorpus(), ...slow];
    const extra = {
      substring: Array.from({ length: MAX_ADMIN_TERMS }, (_, i) => `zq${i}x`.replace(/\d/g, 'q')),
      token: ['zzz'],
      allow: ['xyz'],
      raw: ['1312'],
    };
    for (const n of names.slice(0, 200)) checkUsername(n, { extra });
    const times: number[] = [];
    for (const name of names) {
      const t0 = performance.now();
      checkUsername(name, { adminName: 'Olivia', extra });
      times.push(performance.now() - t0);
    }
    times.sort((a, b) => a - b);
    const p99 = times[Math.floor(times.length * 0.99)]!;
    const max = times.at(-1)!;
    // The slowest shapes on their own, after a few rounds.
    for (let round = 0; round < 3; round++) for (const n of slow) checkUsername(n, { extra });
    const t0 = performance.now();
    for (const n of slow) checkUsername(n, { adminName: 'Olivia', extra });
    const slowMean = (performance.now() - t0) / slow.length;
    console.log(
      `checks: ${times.length}, p99 ${(p99 * 1000).toFixed(1)} us, max ${(max * 1000).toFixed(1)} us, slowest shapes mean ${(slowMean * 1000).toFixed(1)} us`,
    );
    assert.ok(p99 < 1, `p99 ${p99} ms`);
    assert.ok(slowMean < 0.5, `slowest shapes ${slowMean} ms`);
  });

  it('reads a name at most 19 ways however many 1s and ls it has', () => {
    for (const name of [...adversarial(50), 'l1l1l1l1l1l1l1l1l1la', 'phil_born_l1l1l1l1'])
      assert.ok(readings(name).length <= 19, name);
  });

  /** The slowest registrable names random searches found (round 3's critic and this round), slowest first. */
  const SEARCHED = [
    'nn1_5n1caaaa_cllcccc',
    'lathmta1ayels1sthsyx',
    'aa5l51a5lnl1c1a_clcc',
    'c1n5_naa1_na5c5n11_c',
    'a5n15cnaa_c_ncn1ca11',
    '11ccca_nn1nacca_cc15',
    'auao19ga9ou191u_1uao',
    'lc_5_1an15nn_n5lc_15',
  ];

  it('ends a scan page by its work: the slowest names one or two at a time, at least one', () => {
    const extra = { substring: ['zzqqzzqq'] };
    assert.equal(scanPage(SEARCHED, extra), 1, 'first page, terms not compiled yet');
    checkUsername('snow_day', { extra });
    assert.equal(scanPage(SEARCHED, extra), 2, 'terms compiled');
    assert.equal(scanPage(GOOD.slice(0, 20), extra), SCAN_PAGE);
    assert.equal(scanPage(['l1l1l1l1l1l1l1l1l1la'], null), 1);
    assert.equal(scanPage([], null), 0);
  });

  for (const [kind, names] of [
    ['good', GOOD],
    ['slowest', adversarial(SCAN_PAGE)],
    ['searched slowest', SEARCHED],
  ] as const)
    it(`keeps a fresh isolate's first scan page of ${kind} names with ${MAX_ADMIN_TERMS} full-length terms of each kind under 5 ms`, () => {
      // The best of three runs, so that a busy machine does not fail it.
      const runs = [coldRun(names), coldRun(names), coldRun(names)];
      const page = Math.min(...runs.map((r) => r.page));
      const startup = Math.min(...runs.map((r) => r.startup));
      console.log(
        `cold ${kind}: startup ${startup.toFixed(1)} ms, first scan page of ${runs[0]!.count} ${page.toFixed(2)} ms (runs ${runs.map((r) => r.page.toFixed(2)).join(', ')})`,
      );
      assert.ok(page < 5, `first page ${page} ms`);
      // Startup has its own, larger limit (the Worker compiles and warms the lists there, not in a request).
      assert.ok(startup < 250, `startup ${startup} ms`);
    });
});
