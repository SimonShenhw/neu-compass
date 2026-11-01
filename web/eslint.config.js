import js from '@eslint/js';
import globals from 'globals';
import tseslint from 'typescript-eslint';
import reactHooks from 'eslint-plugin-react-hooks';
import jsxA11y from 'eslint-plugin-jsx-a11y';

export default tseslint.config(
  {
    ignores: [
      'dist/**',
      'dist-dev-api/**',
      'node_modules/**',
      'coverage/**',
      // What tools/e2e installs and what a run of it leaves (.gitignore).
      'tools/e2e/.browsers/**',
      'tools/e2e/test-results/**',
      'tools/e2e/playwright-report/**',
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['src/**/*.{ts,tsx}'],
    languageOptions: { globals: globals.browser },
    plugins: { 'react-hooks': reactHooks, 'jsx-a11y': jsxA11y },
    rules: {
      ...reactHooks.configs.recommended.rules,
      ...jsxA11y.configs.recommended.rules,
      // A labelled, horizontally scrollable region needs a keyboard focus stop.
      'jsx-a11y/no-noninteractive-tabindex': [
        'error',
        { roles: ['tabpanel', 'region'] },
      ],
      '@typescript-eslint/consistent-type-imports': 'error',
      'no-console': ['error', { allow: ['info'] }],
    },
  },
  {
    files: ['*.js', 'scripts/*.mjs', 'tools/*/*.mjs'],
    languageOptions: { globals: globals.node },
  },
  {
    // The e2e tests take test from tests/support.ts, whose automatic fixture checks that each page asks nothing of a
    // third party; @playwright/test's own (its default export too) would leave a file without it (recheck 1 of round 35).
    files: ['tools/e2e/tests/**/*.ts'],
    ignores: ['tools/e2e/tests/support.ts'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          paths: [
            {
              name: '@playwright/test',
              importNames: ['test', 'default'],
              message:
                'Take test from ./support: its fixture checks what each page requests.',
            },
          ],
        },
      ],
    },
  },
);
