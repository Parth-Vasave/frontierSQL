# FrontierSQL — frontend

Two static pages built by Vite:

- `/` (`index.html`, `src/home/`): the project homepage. It replays one real recorded answer in
  the chat UI (`src/home/recordedAnswer.ts`) and shows the recorded safety and question runs
  (`src/home/evaluation.ts`). `src/home/evaluation.test.ts` recomputes those numbers from
  `../evaluation/results/*.jsonl`, so a new run means new result files and an update there.
- `/chat/` (`chat/index.html`, `src/main.tsx`): the analyst app.

Both are plain files in `dist/`, so any static host serves them without rewrite rules.

The chat UI for the FrontierSQL backend, in the familiar two-pane layout of Claude.ai or
ChatGPT: past chats in a left sidebar, a settings menu bottom-left (switch or connect a database,
browse its schema, theme, help), and a conversation pane. Each answer shows the grounded answer,
the result table and a chart, under a one-line verification summary that opens into the plan, the
exact SQL that ran, step timings and every result check. Chats are kept in the browser's
localStorage only; there are no accounts and the server keeps no conversation state.

See `../DESIGN.md` for the design system and `../PRODUCT.md` for product context.

## Develop

```bash
npm install
npm run dev        # http://localhost:5173 (homepage), /chat/ (app); proxies /api to http://localhost:8000
```

The dev server expects the backend (see the repository root's `docker-compose.yml`) running at
`http://localhost:8000`. Override the proxy target with `VITE_API_PROXY_TARGET`, or point a built
app at a different origin with `VITE_API_BASE_URL` (see `.env.example`).

## Check

```bash
npm run typecheck
npm test
npm run build
```
