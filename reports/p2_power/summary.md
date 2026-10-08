# P2 offline power run (deliverable 2): no model call

Every decision point at its declared code fallback (`decider: offline`).
Every count keys on the outcome (the verdict and completion), never the label alone:
an abstaining or unfinished run is excluded, never read as `none`.
Faulted cells hit: 0 of 6 scored; excluded: abstain 0, pending 0; null rejected on faulted cells: 3 of 6.

| cell | truth | outcome | excluded | NB | NM | NS | partial | failed channels | admitted |
|---|---|---|---|---|---|---|---|---|---|
| S0-01 B/C | none | parameter | False | False | True | False | False | ['digestate_ts', 'digestate_vs'] | ['parameter'] |
| S1-01 B/B | none | none | False | True | False | False | True | ['gas_flow'] | [] |
| S2-01 B/B | sensor | parameter | False | False | True | False | False | ['gas_flow', 'ph'] | ['parameter'] |
| S3-01 C/B | influent | parameter | False | False | True | False | False | ['alkalinity', 'cod_total', 'gas_flow', 'ph', 'tan', 'vfa_total'] | ['parameter', 'structural'] |
| S4-01 B/B | state | none | False | False | False | False | True | ['cod_total'] | [] |
| S5-01 A/A | parameter | none | False | False | False | False | False | [] | [] |
| S6-02 B/B | structural | none | False | False | False | False | False | [] | [] |
| S8-01 B/B | sensor | none | False | True | False | True | False | ['gas_flow'] | [] |
