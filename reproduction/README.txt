Counting Producer Participation Across Credits and Audio Submissions
reproduction

Requirements
  CPython 3.14 on a POSIX system with numpy 2.5.3, pandas 3.0.5 and pyarrow
  26.0.0.  The package is self-contained: every input is included and no network
  access is used.

Command
  python3.14 -B reproduce.py

  The command copies code/, data/ and transfer/ into runs/<UTC timestamp>/ and
  runs four stages there: the producer-credit scan and count targets, the
  artist-year support replay, the constructed minimal cases, and the regulatory
  transfer calculation.  The shipped tree is never modified.  Each stage has a
  120-second CPU limit; use --cpu-limit 1800 if the machine is slow.

Comparison
  Each result file under runs/.../results/ is compared with expected.json,
  which holds the corresponding reference result.  Execution records,
  environment fields, absolute paths and wall-clock timings are dropped before
  comparison; integers and text must then agree exactly and floats exactly too,
  since this package reproduces without drift.  PASS and CHECK.json indicate a
  full match.  The regulatory transfer stage additionally re-checks its own five
  reference files and prints "PASS counting_units: 5 stable result files".

Modifications
  Two shipped references record input locations from the package's original
  layout rather than scientific values: the music rewrite certificate keys
  source_hashes by bare file name ("producer_recs.csv.gz"), and the minimal
  cases name their bounded-dyad metadata under "evidence/".  This package ships
  every primary input in data/ and passes data/<name> on the command line, so
  expected.json pins those two path fields to the spelling this package emits.
  Nothing else about those files is altered: every count, executed query text,
  key digest and counterexample row still comes from the shipped reference.

Expected counts
  804,781 physical credit rows and 800,973 distinct payloads; 17,450 matched
  recordings; the recording join gives 23,473 producer-recording relationships
  against 28,522 submission-joined rows, an increase of 5,049 rows = 21.51%;
  43,094 regulatory reduction cells; 9 compared result files.

Data
  data/producer_recs.csv.gz holds the historical processed credit relation
  (804,781 rows; prior CC BY-NC-SA 3.0 supplementary-relationship notice, see
  SOURCE.txt).  data/submission_metadata.npz (100,000 submission rows, 88,816
  recordings) and data/artist_features83.npz (27 rows x 83 features) hold the
  retained AcousticBrainz values (CC0).  data/first_dyad_metadata.json holds the
  bounded first-dyad rows.  data/SOURCES.json records sizes, hashes and upstream
  identifiers.  transfer/data/schema_aware_records.parquet holds the public
  moderation-record reduction used by the transfer calculation.

Files
  reproduce.py      the driver
  expected.json     expected result content, keyed by run-relative path
  code/             the primary analysis programs
  data/             the primary inputs
  transfer/         the regulatory transfer program, its input and references
  RESULTS.tsv       paper item to program, line, output and input
  ENVIRONMENT.json  the recorded release environment
