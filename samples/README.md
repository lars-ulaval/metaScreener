# samples/

This folder contains small sample inputs that can be used to test metaScreener quickly.

## Two corpora

Both are aggregate CSVs in the same 34-column metaScreener schema, byte for
byte the same header, so either can be used wherever the other is.

- `20260122_1654_aggregate.csv` — 776 records on immersive virtual reality
  and head-mounted-display training. This is the corpus the documented
  walkthrough runs on, and the one every committed measurement in `docs/data/`
  was made against.
- `20260816_1841_rsaAggregate.csv` — 463 records on respiratory sinus
  arrhythmia, harvested as a References-of-X pass over 8 seed papers. A second,
  independent corpus for exercising the pipeline on unfamiliar material.

## Criteria

- `20260122_1654_sampleIcEc.txt` — eight free-text criteria (four inclusion,
  four exclusion) for the VR/HMD review above. One criterion per line, tagged
  `IC-N` or `EC-N`. This is the input to Plugin 03 (Criteria Parser).

There is no criteria file for the RSA corpus yet.

## Reference lists

- `20260122_1654_sampleReferences.txt` — a short bibliography as numbered
  citations, for Plugin 02.
- `20260122_1654_rsaSampleReferences.txt` — the RSA seed bibliography, same
  format.

## Plugin 01 (Reference Markers, experimental) - input not bundled

Plugin 01 accepts images (PDF or PNG) containing visible reference markers,
such as numbered citations (`[1]`, `[2]`) or author-year citations
(`[Smith 2022]`). No public-domain sample with the required visual format
is included in this repository to avoid copyright concerns. Users can
generate a test input by exporting a bibliography page from any open-access
article as a PDF or PNG.

Standard PRISMA flow diagrams typically do **not** contain reference
markers and should not be used as Plugin 01 input - feeding one as input
may produce hallucinated output.
