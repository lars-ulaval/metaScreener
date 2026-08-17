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

### The RSA corpus contains real upstream noise, on purpose

It was harvested, not curated, and what a harvest brings with it was left in.
That is the point of a realistic demo corpus: a screening tool that has only
ever been run on clean input has not been tested. Measured, not estimated:

- **152 of the 463 records are off topic**, and they arrive from two of the
  eight seeds — 47 under `parents=X002` (science education, largely Brazilian
  Portuguese) and 105 under `parents=X012` (nonlinear dynamics and chimera
  states). Neither has anything to do with heart-rate variability. A
  References-of-X pass inherits whatever its seeds cite.
- **12 records are in Portuguese** (`lang=pt`), correctly labelled, and they
  are the entire X002 education cluster.
- **One abstract is scraped web boilerplate.** `A249` begins *"Thank you for
  visiting nature.com. You are using a browser version with limited support for
  CSS…"* — the publisher's compatibility notice, captured instead of the
  abstract.
- **One record's `lang` disagrees with its own text.** `A235` is labelled
  `lang=en` with an English title (*"Kubios HRV – Heart rate variability
  analysis software"*) and a **Ukrainian** abstract, 702 Cyrillic characters.
- **One record carries Cyrillic author names** mixed with Latin ones (`A356`,
  *Physical Review E*), which is an author-list transliteration artefact rather
  than a language error.

None of this is an apology. Two of the wave-17 findings depend on it: the
off-topic mass is the only population in the project where a screening verdict
can be checked against ground truth known by construction, and the
abstract-less and mislabelled records are what exercise the paths a curated
corpus never reaches.

## Criteria

- `20260122_1654_sampleIcEc.txt` — eight free-text criteria (four inclusion,
  four exclusion) for the VR/HMD review above. One criterion per line, tagged
  `IC-N` or `EC-N`. This is the input to Plugin 03 (Criteria Parser).

- `20260816_1841_rsaSampleIcEc.txt` — eight free-text criteria (four
  inclusion, four exclusion) for the RSA corpus, same format.

> **These two criteria files are realistic examples, not recommended screening
> instruments.** They are what a researcher might plausibly write, and the
> project keeps them because measuring what plausible criteria actually do is
> the point. On the RSA corpus, the inclusion criterion `IC-5` — requiring the
> literal words *emotion*, *dysregulation*, *child*, *adolescent*, *youth* or
> *infant* — removes **117 on-topic papers that satisfied every other
> criterion**, among them the corpus's own seed paper [1] (Berntson, Cacioppo
> and Quigley 1993). Nothing in the product's output tells the user this
> happened. See **F-239** in `docs/internal/diagnostic/03_findings.md` and
> §7.5 of `docs/data/wave17_arms/ANALYSIS_WAVE_17_ARMS.md`. Do not copy either
> file as a template without reading that first.

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
