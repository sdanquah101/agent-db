# The Q6 (H4) development cells offline: no model call

S7-01 at B/A, B/B, B/C and S7-02 at A/C, two seeds each (replicates 0 and 1), each
run by both arms with every decision at its offline fallback: the procedural P2
(`p2.yaml`, the code-only floor) and the agent arm (`p2_agents.yaml` as committed,
its frozen record checked before every run, its roles at their scripted plans).
Descriptive only (design note §7). The scores are eval's (`eval/attribution.py`):
`primary in truth`, the label names one of the two faults; `exact`, the label set
(the label and the secondary labels both arms write by one rule, the other admitted
labels, since Q-H4 "a") equals the truth. `truth admitted` shows which of the
faults the admission let through. Every count keys on the outcome; an abstaining
or unfinished run is excluded.

- procedural: primary in truth 0 of 8 scored; exact 0 of 8 scored; excluded abstain 0, pending 0; both faults admitted in 0 of 8 runs
- agents: primary in truth 0 of 0 scored; exact 0 of 0 scored; excluded abstain 8, pending 0; both faults admitted in 0 of 8 runs

| cell | seed | arm | truth | outcome | label set | primary in truth | exact | rule | truth admitted | NB | NM | NS | failed channels | evaluations | wall min |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| S7-01 B/A | 0 | agents | sensor,influent | abstain | - | False | False | abstain:verifier_abstain | - | False | False | True | ['ph'] | 196/750 | 48.5 |
| S7-01 B/A | 0 | procedural | sensor,influent | none | none | False | False | null_failed_unexplained | - | False | False | True | ['ph'] | 195/750 | 48.4 |
| S7-01 B/A | 1 | agents | sensor,influent | abstain | - | False | False | abstain:verifier_abstain | - | False | False | False | [] | 188/750 | 46.4 |
| S7-01 B/A | 1 | procedural | sensor,influent | none | none | False | False | null_stands | - | False | False | False | [] | 187/750 | 46.9 |
| S7-01 B/B | 0 | agents | sensor,influent | abstain | - | False | False | abstain:verifier_abstain | - | False | True | False | ['ch4_fraction', 'ph'] | 232/750 | 59.5 |
| S7-01 B/B | 0 | procedural | sensor,influent | parameter | parameter | False | False | NM+parameter | - | False | True | False | ['ch4_fraction', 'ph'] | 231/750 | 59.5 |
| S7-01 B/B | 1 | agents | sensor,influent | abstain | - | False | False | abstain:verifier_abstain | - | False | False | False | [] | 211/750 | 54.7 |
| S7-01 B/B | 1 | procedural | sensor,influent | none | none | False | False | null_stands | - | False | False | False | [] | 210/750 | 54.8 |
| S7-01 B/C | 0 | agents | sensor,influent | abstain | - | False | False | abstain:verifier_abstain | - | False | True | False | ['ch4_fraction', 'ph', 'vfa_total'] | 288/750 | 73.6 |
| S7-01 B/C | 0 | procedural | sensor,influent | parameter | parameter | False | False | NM+parameter | - | False | True | False | ['ch4_fraction', 'ph', 'vfa_total'] | 287/750 | 73.6 |
| S7-01 B/C | 1 | agents | sensor,influent | abstain | - | False | False | abstain:verifier_abstain | - | False | False | False | [] | 245/750 | 63.2 |
| S7-01 B/C | 1 | procedural | sensor,influent | none | none | False | False | null_stands | - | False | False | False | [] | 244/750 | 63.2 |
| S7-02 A/C | 0 | agents | structural,parameter | abstain | - | False | False | abstain:verifier_abstain | - | False | False | False | [] | 233/375 | 107.1 |
| S7-02 A/C | 0 | procedural | structural,parameter | none | none | False | False | null_stands | - | False | False | False | [] | 232/375 | 106.6 |
| S7-02 A/C | 1 | agents | structural,parameter | abstain | - | False | False | abstain:verifier_abstain | - | False | False | False | [] | 242/375 | 108.5 |
| S7-02 A/C | 1 | procedural | structural,parameter | none | none | False | False | null_stands | - | False | False | False | [] | 241/375 | 109.3 |

Seed checks: both arms of every cell and seed saw byte-identical observations: True; the two seeds of every cell differ: True.
