# refund-week: the run reported in the paper

One run of `ht2wv bench run examples/samples/refund-week --backend codex --model gpt-6-astra --effort xhigh
--context-window 350000` on 2026-10-13 (47 sessions, 5 h 22 min), at commit `78b8a28`.

**This is the run as it happened, before the fixes it led to.** At that commit the export step did not copy a
skill's `references/` into the run, the sample's reference reports opened with "orders handled" instead of
"requests", and a day on which nothing was done lost its requests. Day 4 and what follows from it (days 5 and 6)
are affected by the first and third; the rejection of the reference days is affected by the second.
The week has not been re-run since.

- `bench-report.md`, `bench-report.json`: the report the run wrote (server paths replaced by `<home>`).
- `skill/`: the skill as it stood at the end of the week, after four revisions: `SKILL.md`, `stages/`,
  `references/`, `verifier.yaml`, `checks/`, and its own `CHANGELOG.md` (which describes each revision).
  Its replay cases and unit tests are left out.
- `rescore-checks-asrun.json`, `rescore-checks-fixed.json`: the scripted items of that verifier re-run without a
  model on the sample as it was during the run and on the corrected sample (12/17 and 17/17 hidden items caught;
  the reference passes every scripted item on 0 and on 3 of the 5 probed days). Judged items were not re-run.
  `rescore_checks.py` is the script: `python rescore_checks.py <home with skills/ and profile/> <sample dir> <tag>`.
