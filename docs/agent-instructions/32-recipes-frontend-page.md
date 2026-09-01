# 32 — Recipe: adding a frontend page or panel

When you add a new React page or panel to `services/orpheus_ui/frontend`,
follow this list.

## Files involved

```
services/orpheus_ui/frontend/
├── src/
│   ├── pages/<NewPage>.tsx              # your page
│   ├── App.tsx                          # route + import
│   ├── components/Layout.tsx            # sidebar nav entry
│   └── lib/                             # shared helpers
└── orpheus-ui-frontend-tests/components.test.tsx  # vitest cases
```

## Checklist

1. **Create the page file**: `src/pages/<NewPage>.tsx`. Follow the
   pattern of `Equivalences.tsx` or `AudioEvents.tsx`. Use:
   - `useQuery` from `@tanstack/react-query` with `placeholderData:
     previousData` for any filtered/paginated query (kills stale-flicker).
   - `<Card>`, `<PageHeader>`, `<LoadingSpinner>` from `../components/ui`.
   - `fetchWithAuth` from `../lib/utils` for API calls.
   - Lucide icons for visual elements.

2. **Add the route in `App.tsx`**:
   ```tsx
   import NewPage from './pages/NewPage'
   ...
   <Route path="/new-page" element={<NewPage />} />
   ```

3. **Add the nav entry in `Layout.tsx`** if it's a top-level page:
   ```tsx
   { name: 'New Page', href: '/new-page', icon: SomeIcon },
   ```

4. **Add at least one vitest case** in
   `orpheus-ui-frontend-tests/components.test.tsx`:
   ```tsx
   describe('NewPage', () => {
     beforeEach(() => {
       localStorage.setItem('orpheus_token', 'test-token')
       mockFetch.mockImplementation((url: string) => {
         if (url.includes('/api/new-thing')) {
           return Promise.resolve(new Response(JSON.stringify({...})))
         }
         return Promise.resolve(new Response(JSON.stringify({})))
       })
     })

     it('renders header', async () => {
       const { default: NewPage } = await import('../src/pages/NewPage')
       renderWithProviders(<NewPage />)
       await waitFor(() => {
         expect(screen.getByRole('heading', { level: 1, name: /new page/i })).toBeInTheDocument()
       })
     })
   })
   ```

5. **Verify locally — the WHOLE flow:**
   ```bash
make -C services/orpheus_ui/frontend lint test build
npx tsc --noEmit        # no make target for the typecheck
```

   `npm run build` is the one that catches `.gitignore` eating a new
   file. Don't skip it. See [`99-gotchas.md`](99-gotchas.md).

6. **Check `git status` after committing.** If anything new shows up,
   the `lib/` rule in `.gitignore` may have caught a file. Verify:
   ```bash
   git check-ignore -v services/orpheus_ui/frontend/src/<new-file>
   ```

7. **Document it in the User Guide (non-negotiable #12).** A new page,
   panel, filter, or interaction is end-user-facing — describe what the user
   *sees and does* in the [User Guide](../user-guide/index.md), in this same
   change. Then `make docs-build` to verify the site builds. The page isn't
   done until the guide is updated.

## Shared helpers go in `src/lib/`

Don't duplicate logic between pages. Extract to `src/lib/`. Examples:
- `lib/utils.ts` — `fetchWithAuth`, `cn`, `formatDateTime`.
- `lib/api.ts` — typed API client functions.
- `lib/speciesLinks.ts` — `buildSpeciesLinks` for iNaturalist/Wikipedia
  links.

**The `.gitignore` rule eats new files in `src/lib/` by default**
(Python `lib/` build-artifacts rule matches it). The negation rules
directly under `lib/` in `.gitignore` prevent this. Verify with
`git check-ignore -v services/orpheus_ui/frontend/src/lib/<file>` — no
output means it is tracked. (`git check-attr` inspects `.gitattributes`
and LFS, not ignore rules.)

## Backend endpoint usually needs a matching change

If your page calls a new `/api/...` endpoint, add it to
`services/orpheus_ui/backend/src/orpheus_ui/api/`. Add tests in
`services/orpheus_ui/backend/tests/test_api.py`. Pattern: the existing
endpoint tests use `MagicMock(spec=User)` for the auth dependency.

## See also

- [`10-tooling.md`](10-tooling.md) — the make/npm rules.
- [`99-gotchas.md`](99-gotchas.md) — the `.gitignore` `lib/` trap.
- Existing page patterns: `Equivalences.tsx`, `AudioEvents.tsx`,
  `Entities.tsx` (Entity detail drawer is in this file too).
