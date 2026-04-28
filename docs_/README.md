# docs_ (samples)

This folder contains small sample inputs that can be used to test metaScreener quickly.

- docs_/samples/ic_ec_12.txt
- docs_/samples/20260122_1654_aggregate.csv
- docs_/samples/ex_ref_2.txt

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
