# The coordinator session

**Every session working on this repository reads this file first, before touching
anything else, and confirms it is not the coordinator.** That check takes one line and is
the cheapest defence this project has against the failure it has already had three times.

---

## Who the coordinator is

| | |
|---|---|
| **Coordinator session ID** | `session_01Cu6G2kQjP2QSzvtkyP8cPr` |
| **Its routine** | `trig_012S8ncXhsvDXbojKiBc4ZFC` — daily at 08:00 UTC, **review-only** |
| **Set** | 2026-09-03, by the lead ("You are the sole coordinator") |

There is exactly one coordinator at a time. If you are reading this and your own session
ID is not the one above, **you are not the coordinator** — see "If you are a component
session" below.

If the ID above does not match any live session, the coordinator has ended. Do not appoint
yourself. Say so to the lead and stop; the lead names the next one, and whoever it is
updates this file in their first commit.

## What the coordinator does

- Reviews every open PR, independently. Subscribes to their activity.
- Relays a child session's questions to the lead, and the lead's decisions back down.
- Reports at gates, on design changes needing sign-off, on duplicate work, and on a
  session blocked for more than one check-in. Otherwise it stays quiet.
- Merges only when the lead says to.

## What the coordinator does **not** do

**It never launches a component session.** Not on a schedule, not on inference, not
because a component looks finished or blocked. A component session starts only when the
lead writes `launch: <component>` (see `CLAUDE.md`, "Who starts a component session").

## If you are a component session

You almost certainly are. Then:

1. **Do not spawn sessions.** Not a child, not a helper, not a "quick" one. If work needs
   splitting, say so to the coordinator and let the lead decide.
2. **Do not create scheduled routines** beyond a check-in on your own PR, and delete that
   when the PR merges or closes.
3. **Do not merge anything**, including your own PR. Open it as a draft and report.
4. **Before you write a line of code, list the open PRs** (`gh pr list` / GitHub) and read
   their titles. If one already covers your component, stop and tell the coordinator. This
   check is a backstop, not the defence — the defence is that only the lead launches — but
   it costs ten seconds and would have caught two of the three collisions below.
5. Route every question and every decision through the coordinator, never sideways to
   another session.

## Why this file exists

Three of the first six components of this project were built **twice**, in parallel, by
two sessions that did not know about each other:

| Component | Duplicate PRs | Outcome |
|---|---|---|
| ADM1 core | #2 vs #4 | #2 canonical; #4 reduced to the extensions |
| Plant layer | #6 vs #7 | #6 canonical; #7 salvaged into it |
| Observation model + fault injection | #11 vs #12 | #11 canonical; #12 closed, three items salvaged into #13 |

Each collision had the same shape: a routine launched a component because its plan said
so, while another session was already building it because a decision had reached that
session directly. Each cost a full component's work. The mitigation added after the first
— "check the open PRs" — did not prevent the third, because by the time anyone looks, the
duplicate work has usually started.

So the authority moved rather than the checklist: the routine cannot launch, and there is
one named coordinator whose ID is written down here, in the repository, where a session
that has just started can see it before it does anything else.

## Keeping this file true

Whoever changes the coordinator updates the table above **in the same commit**. A stale ID
here is worse than no file: it would tell a new session that a dead session is in charge.
