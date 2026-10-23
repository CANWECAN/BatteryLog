# H6 bounded source access and schema inspection — 17 October 2026

> Historical record: licensing and package descriptions below refer to the recorded
> revision. The current unified Apache-2.0 package is defined in [LICENSING.md](LICENSING.md).
> Engineering evidence and qualification limits retain their original scope.

This pass limits metadata responses to 128 KiB, public requests to a 12-second
timeout, and archive range reads to 512 KiB. Third-party documents/code/data
remain outside git; no downloaded code is executed.

## OSF 94gkc access is now available from native Windows

The public node, provider and root-file APIs returned HTTP 200, replacing the
earlier 503-only checkpoint. Browser/search fetch failures do not characterize
the native public API result.

Project: High-resolution dataset of electric vehicle charging responses under
varied power quality disturbances.
https://api.osf.io/v2/nodes/94gkc/
https://api.osf.io/v2/nodes/94gkc/files/osfstorage/

The root listing has three files: a 16,909-byte validation-code ZIP, a
23,008,269-byte data ZIP and a 5,000-byte README. The two small documents were
downloaded; SHA-256 values match the producer's API metadata:

| File | SHA-256 |
| --- | --- |
| Technical Validation Code.zip | 3e6f1cecf9e0f64855be196ccfd8e84de7f46a9c16ebe45133bfedea70c6aaed |
| README.md | 9899927eb0f72469cdddaecf8cf9467aeecb4e9d266a1caa1ca5c36177c4f71f |

## Actual bounded CSV prefixes

HTTP Range requests were honored. Nine ranges transferred 74,232 bytes of the
23 MB data archive; the ETag stayed constant. ZIP metadata lists 327 members,
including 313 CSVs. Two frequency-deviation CSV prefixes were inspected,
2,048 uncompressed bytes each. The complete archive was not downloaded and its
whole-file checksum was not independently verified from partial bytes.

The inspected 22-column headers include battery voltage/current, charging input
voltage and charging status, as well as availability/limit/SOC fields. This is
more informative than the earlier access-only evidence and remains a useful lead.
However:
- DC_Charging_Input_Voltage is not authenticated as the required internal DC-link node.
- Charging_Status is not an authenticated precharge-active/command/feedback signal.
- The current path, time alignment, raw validity/unknown policies and comparable
  independently justified normal envelope remain unqualified.

The unchanged strict aligned-precharge CSV parser rejects both supplied prefixes
at the required-header boundary. This checks format only; no observer is called.
No aliases, guessed phase, sentinel policy or physical reference is synthesized.
Other files were not claimed to lack additional channels.

The producer README describes charging/power-quality experimental analysis;
that description and selected headers do not establish all precharge context.
Original physical steps 7-8 remain open.

## Separate Parquet fleet-data lead

The Rico-dicp/Ev-battery-cell-to-cell-inconsistency README and DATA_LINK.txt were
re-read at dc1dd9226d2c01450b1afb1c8a378b7eb293c291. File lengths and Git blob
identities were verified. The link lists 40 NMC passenger-car and 20 LFP bus
Parquet parts. The bounded public OneDrive response was HTML, not a Parquet
listing or file; the 128 KiB cap was reached. No signed-in session was used.
The Parquet schema remains unverified; additional columns are not ruled out.
This is separate from the OSF power-quality project and PHEV thesis lead.

Source:
https://github.com/Rico-dicp/Ev-battery-cell-to-cell-inconsistency/tree/dc1dd9226d2c01450b1afb1c8a378b7eb293c291

## Closure and next gate

This bounded pass is complete: source access, two actual sample schemas and the
remaining evidence dependencies are explicit. It does not close Parquet schema
access or physical precharge qualification. Further work needs producer signal
definitions/acquisition context and a comparable normal reference before
physical observer acceptance.

External source-bound request metadata, raw small documents, range hashes and
qualification results are in batterylog-dataset-access-20261017-evidence.
Core code, data mappings, thresholds, licensing and the frozen alpha are unchanged.
H7 operator flow and H8 readable reports follow; adapter step 9 stays deferred.
Third-party data is not redistributed.
