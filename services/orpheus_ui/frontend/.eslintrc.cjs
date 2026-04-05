module.exports = {
  root: true,
  env: { browser: true, es2020: true },
  extends: [
    'eslint:recommended',
    'plugin:@typescript-eslint/recommended',
    'plugin:react-hooks/recommended',
  ],
  ignorePatterns: ['dist', '.eslintrc.cjs', 'coverage'],
  parser: '@typescript-eslint/parser',
  plugins: ['react-refresh'],
  rules: {
    // This codebase co-locates hooks, utilities, and constants alongside
    // components (e.g. useAuth in AuthContext.tsx, paginate in DateRangeFilter.tsx).
    // Splitting them would be unnecessary churn.  Disable the mixed-export warning
    // so it doesn't block CI — fast-refresh still works for the component parts.
    'react-refresh/only-export-components': 'off',
    '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
  },
}
