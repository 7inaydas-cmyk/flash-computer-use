"""Repo writing standards, enforced: no em/en dashes in shipped prose, and
the config example stays redacted."""
import json
import os
import re
import unittest

REPO = os.path.join(os.path.dirname(__file__), "..")


def repo_files(suffix):
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in (".git",)]
        for f in files:
            if f.endswith(suffix):
                yield os.path.join(root, f)


class DocsStandard(unittest.TestCase):
    def test_no_em_or_en_dashes_in_markdown(self):
        offenders = []
        for path in repo_files(".md"):
            for n, line in enumerate(open(path, encoding="utf-8"), 1):
                if "\u2014" in line or "\u2013" in line:
                    offenders.append(f"{os.path.relpath(path, REPO)}:{n}")
        self.assertEqual(offenders, [], f"em/en dashes found: {offenders}")

    def test_config_example_key_stays_redacted(self):
        cfg = json.load(open(os.path.join(REPO, "zcode-cli-config.example.json")))
        key = cfg["provider"]["zai-coding-plan"]["options"]["apiKey"]
        self.assertIn("mirror apiKey", key)
        self.assertNotRegex(key, r"^[0-9a-f]{20,}")


class SecretScan(unittest.TestCase):
    # assembled from fragments so this file cannot match itself
    PATTERNS = (
        re.compile("023d44" + "c7"),
        re.compile(r"\bsk-[A-Za-z0-9]{16,}"),
        re.compile(r"\bgho_[A-Za-z0-9]{16,}"),
        re.compile(r"x-api-key:\s*[0-9a-f]{24}\."),
    )

    def test_no_key_material_in_tree(self):
        offenders = []
        paths = (list(repo_files(".py")) + list(repo_files(".sh"))
                 + list(repo_files(".md")) + list(repo_files(".json"))
                 + [os.path.join(REPO, "bin", n) for n in ("lcu", "flash-relay")])
        for path in paths:
            text = open(path, encoding="utf-8", errors="replace").read()
            for pat in self.PATTERNS:
                if pat.search(text):
                    offenders.append(f"{os.path.relpath(path, REPO)} matches {pat.pattern}")
        self.assertEqual(offenders, [], f"possible secrets: {offenders}")


if __name__ == "__main__":
    unittest.main()
