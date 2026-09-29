SCF release: SCF 2026.3; 800-53 column: NIST 800-53 R5.2; cases: 221

| Stage | Metric | Value |
|---|---|---|
| Retrieval | Hit rate @1 | 11.3% |
| Retrieval | Mean recall @1 | 1.3% |
| Retrieval | MRR @1 | 0.113 |
| Retrieval | Hit rate @3 | 18.6% |
| Retrieval | Mean recall @3 | 2.7% |
| Retrieval | MRR @3 | 0.145 |
| Retrieval | Hit rate @5 | 24.9% |
| Retrieval | Mean recall @5 | 4.2% |
| Retrieval | MRR @5 | 0.159 |
| Retrieval | Hit rate @10 | 38.0% |
| Retrieval | Mean recall @10 | 7.4% |
| Retrieval | MRR @10 | 0.176 |
| Retrieval | Hit rate @20 | 50.7% |
| Retrieval | Mean recall @20 | 13.0% |
| Retrieval | MRR @20 | 0.184 |
| Retrieval | Hit rate @50 | 62.0% |
| Retrieval | Mean recall @50 | 21.7% |
| Retrieval | MRR @50 | 0.188 |

Embedding model: all-MiniLM-L6-v2 (sentence-transformers); SCF controls ranked: 1591

## Gold set

Security Hub controls read: 251; dropped without a NIST 800-53 rev 5 requirement: 30; dropped because SCF maps none of their 800-53 requirements: 0; cases: 221. Gold controls per case: median 7, max 28; cases with at most 10: 140.

## All cases (221)

| k | embedding hit rate | embedding recall | embedding MRR | tfidf hit rate | tfidf recall | tfidf MRR | random (expected) hit rate | random (expected) recall | random (expected) MRR |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 11.3% | 1.3% | 0.113 | 7.2% | 0.7% | 0.072 | 0.5% | 0.1% | 0.005 |
| 3 | 18.6% | 2.7% | 0.145 | 16.7% | 2.3% | 0.115 | 1.6% | 0.2% | 0.010 |
| 5 | 24.9% | 4.2% | 0.159 | 20.8% | 3.4% | 0.124 | 2.6% | 0.3% | 0.012 |
| 10 | 38.0% | 7.4% | 0.176 | 27.1% | 4.5% | 0.132 | 5.2% | 0.6% | 0.015 |
| 20 | 50.7% | 13.0% | 0.184 | 36.7% | 7.2% | 0.139 | 10.0% | 1.3% | 0.019 |
| 50 | 62.0% | 21.7% | 0.188 | 46.2% | 10.7% | 0.142 | 22.8% | 3.1% | 0.022 |

## Cases with at most 10 gold controls (140)

| k | embedding hit rate | embedding recall | embedding MRR | tfidf hit rate | tfidf recall | tfidf MRR | random (expected) hit rate | random (expected) recall | random (expected) MRR |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 7.1% | 1.1% | 0.071 | 4.3% | 0.6% | 0.043 | 0.3% | 0.1% | 0.003 |
| 3 | 13.6% | 2.8% | 0.101 | 11.4% | 2.3% | 0.074 | 1.0% | 0.2% | 0.006 |
| 5 | 18.6% | 4.6% | 0.113 | 14.3% | 3.7% | 0.081 | 1.6% | 0.3% | 0.008 |
| 10 | 27.1% | 7.8% | 0.123 | 17.1% | 4.9% | 0.084 | 3.3% | 0.6% | 0.010 |
| 20 | 37.9% | 13.2% | 0.130 | 25.0% | 8.0% | 0.090 | 6.4% | 1.3% | 0.012 |
| 50 | 47.9% | 20.8% | 0.134 | 35.0% | 11.7% | 0.093 | 15.2% | 3.1% | 0.014 |
