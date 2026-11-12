#!/usr/bin/env python3
"""Summarize a verifier JUnit report: failing groups, codecs, and top messages."""
import collections, re, sys, xml.etree.ElementTree as ET
root = ET.parse(sys.argv[1]).getroot()
groups = collections.Counter(); codecs = collections.Counter(); msgs = collections.Counter(); skipped = 0
for tc in root.iter("testcase"):
    if tc.find("skipped") is not None:
        skipped += 1
    f = tc.find("failure")
    if f is None:
        f = tc.find("error")
    if f is None:
        continue
    name = tc.get("name"); groups[name.split("[")[0].replace("test_", "")] += 1
    codecs["pyav" if "pyav" in name else "opencv"] += 1
    m = (f.get("message") or "").split("\n")[0]
    m = re.sub(r"\[[0-9, ]+\]", "[..]", m); m = re.sub(r"\d+", "N", m)
    msgs[m[:120]] += 1
print(" groups:", dict(groups)); print(" codec-in-name:", dict(codecs), "skipped:", skipped)
for m, n in msgs.most_common(3):
    print(f"  {n:3d}x {m}")
