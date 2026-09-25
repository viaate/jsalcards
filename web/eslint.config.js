import js from '@eslint/js';
import { defineConfig, globalIgnores } from 'eslint/config';
import svelte from 'eslint-plugin-svelte';
import ts from 'typescript-eslint';

import svelteConfig from './svelte.config.js';

export default defineConfig(
  globalIgnores([
    'dist/',
    'coverage/',
    'playwright-report/',
    'test-results/',
    'bench/out/',
    'perf/raw/',
  ]),
  js.configs.recommended,
  ts.configs.strictTypeChecked,
  ts.configs.stylisticTypeChecked,
  svelte.configs.recommended,
  {
    languageOptions: {
      parserOptions: {
        project: ['./tsconfig.json', './tsconfig.node.json', './tsconfig.e2e.json'],
        tsconfigRootDir: import.meta.dirname,
        extraFileExtensions: ['.svelte'],
      },
    },
    linterOptions: {
      reportUnusedDisableDirectives: 'error',
      reportUnusedInlineConfigs: 'error',
    },
    rules: {
      eqeqeq: ['error', 'always'],
      'no-console': ['error', { allow: ['warn', 'error'] }],
      '@typescript-eslint/consistent-type-imports': 'error',
    },
  },
  {
    // Node scripts (build, perf, codegen) are plain JavaScript outside every
    // tsconfig: lint them without type information, with Node's globals.
    files: ['**/*.js', '**/*.mjs', '**/*.cjs'],
    extends: [ts.configs.disableTypeChecked],
    languageOptions: {
      globals: Object.fromEntries(
        [
          'AbortController',
          'Buffer',
          'URL',
          'URLSearchParams',
          'TextDecoder',
          'TextEncoder',
          'clearInterval',
          'clearTimeout',
          'console',
          'fetch',
          'performance',
          'process',
          'queueMicrotask',
          'setInterval',
          'setTimeout',
          'structuredClone',
        ].map((name) => [name, 'readonly']),
      ),
    },
    rules: {
      // Command-line scripts report progress on stdout.
      'no-console': 'off',
    },
  },
  {
    files: ['**/*.svelte', '**/*.svelte.ts'],
    languageOptions: {
      parserOptions: {
        parser: ts.parser,
        svelteConfig,
      },
    },
    rules: {
      // TypeScript already reports undefined identifiers, including DOM globals.
      'no-undef': 'off',
    },
  },
);
