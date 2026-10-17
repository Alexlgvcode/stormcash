"""Detectors proposed by Droid (spec §14.7d), each merged by a person after review.

Each module is a pure function over one candidate kind's frozen feature
snapshot (`KIND`, `NAME`, `fires(features) -> bool`), with its test in
`server/tests/test_proposed_<name>.py` and its numbers in its pull request.
Nothing here is imported by `detectors.run_incremental`: wiring a proposed
detector in is a separate change a person makes.
"""
