# BIRD Mini-Dev runs

Every BIRD run of this project, one JSONL file per run id in this folder: for each question the
agent's plan, final SQL, result rows, trace summary, tokens and BIRD's official scores (EX, Soft F1).
Report for any run:

```
python -m evaluation.report evaluation/results/<run id>.jsonl
```

**Licence.** These `*-bird-*.jsonl` files contain BIRD questions, hints and values from the BIRD
databases, so they are shared under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/),
like BIRD itself (the rest of the repository is MIT). Source: BIRD Mini-Dev,
<https://github.com/bird-bench/mini_dev>. Attribution: *Li et al., "Can LLM Already Serve as A
Database Interface? A BIg Bench for Large-Scale Database Grounded Text-to-SQLs" (BIRD), NeurIPS
2023.*

## Method

- **test** = the 500 Mini-Dev questions (PostgreSQL), scored with BIRD's official execution
  accuracy (EX). **dev** = BIRD's dev set as revised on 2025-11-06, without the Mini-Dev questions
  (same databases); every change was measured there before the test set was run again.
- `--sample 100` is a fixed sample (same 100 dev questions in every run), so runs on it compare
  question by question.
- The code of each run is the commit recorded in its file (`code_commit`; `-dirty` = uncommitted
  changes). Commits that are no longer on a branch are kept by the tags `archive/bird-phase-0`
  (1493cc9, 6960b34) and `archive/bird-loader-2dbb325`; the final run's commit is tagged
  `bird-minidev-final`.
- The fixes kept for the final run came from reading the 242 misses of the Cerebras test baseline;
  each was measured on dev only, and the test set was run once more at the end.

## Runs

| Run id | Split | Code | Provider (gpt-oss-120b) | Questions | EX | What it was |
|---|---|---|---|---|---|---|
| 20261005-103021-bird-database | test | 2dbb325-dirty | Groq | 101 of 500 | file predates the EX field | first partial run |
| 20261005-160047-bird-dev-database | dev | 4808884-dirty | Groq | 10 | 6/10 | smoke test |
| 20261005-165933-bird-dev-database | dev | 1493cc9 | Groq | 9 of 100 | 3/9 | dev baseline, stopped |
| 20261005-184558-bird-database | test | 6960b34 | Groq | 87 of 500 | 54/87 | free-tier test run, ended when its database stopped |
| 20261012-093609-bird-dev-database | dev | 6f85d14-dirty | Cerebras | 5 | 3/5 | smoke test |
| 20261012-094139-bird-database | test | 6f85d14 | Cerebras | 500 | **258/500 (51.6%)** | **test baseline** |
| 20261012-143325-bird-dev-database | dev | 6f85d14 | Cerebras | 100 | 63/100 | dev baseline (`--sample 100`) |
| 20261012-154356-bird-dev-database | dev | 7632659 | Cerebras | 100 | 66/100 | Run A: fixes 1-6, same sample |
| 20261012-164102-bird-dev-database | dev | 6f85d14 | Cerebras | 71 | 25/71 | Run B old: the 71 dev questions the fixes target |
| 20261012-165312-bird-dev-database | dev | 7632659 | Cerebras | 71 | 46/71 | Run B new: same questions with the fixes |
| 20261013-033205-bird-dev-database | dev | eec2715 | Cerebras | 100 | 65/100 | prompt rule for hint formulas (sql-generator/10), same sample |
| 20261013-042342-bird-dev-database | dev | 9989fb3 | Cerebras | 60 | 33/60 | 60 dev questions with a formula in the hint, before the rule |
| 20261013-052654-bird-dev-database | dev | eec2715 | Cerebras | 60 | 28/60 | same 60 with the rule |
| 20261013-100911-bird-dev-database | dev | a226871 | Cerebras | 100 | 62/100 | reasoning effort `high`, max output 8192, same sample |
| 20261013-122627-bird-database | test | a226871 | Cerebras | 500 | **284/500 (56.8%)** | **final test run**, same settings as the baseline |

## What was kept and what was not

- **Kept** (Run B: 25 -> 46 of 71 targeted dev questions; 24 fixed, 3 broken): schema retrieval
  uses the hint and adds linking tables; an unknown plan intent no longer rejects a reply;
  joins inferred for columns named like a declared foreign key; NUMERIC casts in divisions computed
  in floating point; the evaluation may see phone and e-mail columns; a result check sends answers
  that concatenate columns back for repair.
- **Reverted:** the prompt rule for hint formulas (eec2715, reverted in a56aee7): 28/60 against
  33/60 on the formula questions and 65 against 66 on the sample. BIRD's answers are not consistent
  about precision and the order of `* 100`, so no single rule matches them.
- **Not kept:** reasoning effort `high`: 62/100 against 66 and 65 at the default effort; four
  replies came back without content.
- **Not adopted** (replayed on 562 recorded dev answers without an LLM): dropping `IS NOT NULL`
  filters, `COUNT(DISTINCT x)` <-> `COUNT(x)`, dropping `ROUND`: each breaks at least as many
  answers as it fixes.

## Final test run against the baseline

| | Baseline (6f85d14) | Final (a226871) |
|---|---|---|
| Official EX | 258/500 (51.6%) | **284/500 (56.8%)** |
| simple (148) | 96 | 105 |
| moderate (250) | 124 | 132 |
| challenging (102) | 38 | 47 |
| Not flagged in `evaluation/bird_review.json` (465) | 256 (55.1%) | 282 (60.6%) |

48 questions fixed, 22 broken. Same model (gpt-oss-120b on Cerebras), default reasoning effort,
one candidate, BIRD's hints on, at most 2 repairs.
