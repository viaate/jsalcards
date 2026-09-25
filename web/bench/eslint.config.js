import { defineConfig, globalIgnores } from 'eslint/config';

import root from '../eslint.config.js';

export default defineConfig(globalIgnores(['out/']), root, {
  languageOptions: {
    parserOptions: {
      project: ['./tsconfig.json'],
      tsconfigRootDir: import.meta.dirname,
    },
  },
});
