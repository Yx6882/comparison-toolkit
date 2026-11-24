"""Tests for ai-council. Stdlib only: `python -m unittest discover -s tests -v`."""

# 注意：本文件里出现的 sk-xxxx、AIza... 都是**测试用的假凭据**，
# 用来验证脱敏器能把它们从记录里抹掉，不是真实密钥。
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import council  # noqa: E402


def demo_raw() -> dict:
    return json.loads(json.dumps(council.DEMO_RAW))


def quiet(func, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return func(*args, **kwargs)


class TestParsing(unittest.TestCase):
    def test_plain_json(self):
        self.assertEqual(council.extract_json('{"a": 1}'), {"a": 1})

    def test_fenced_json(self):
        self.assertEqual(council.extract_json('```json\n{"a": 1}\n```'), {"a": 1})

    def test_prose_wrapped(self):
        text = 'sure, here it is: {"a": {"b": "}"}, "c": [1, 2]} — hope it helps'
        self.assertEqual(council.extract_json(text), {"a": {"b": "}"}, "c": [1, 2]})

    def test_trailing_comma(self):
        self.assertEqual(council.extract_json('{"a": [1, 2,],}'), {"a": [1, 2]})

    def test_garbage_returns_none(self):
        self.assertIsNone(council.extract_json("no json at all"))
        self.assertIsNone(council.extract_json(""))


class TestSafety(unittest.TestCase):
    def test_secret_patterns(self):
        redact = council.Redactor()
        text = "key=sk-abcdefghijklmnopqrstuvwxyz and AIza" + "A" * 35
        out = redact(text)
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz", out)
        self.assertIn("«redacted:key»", out)

    def test_env_secret_redacted(self):
        redact = council.Redactor(["super-secret-value"])
        self.assertEqual(redact("token=super-secret-value"), "token=«redacted:env»")

    def test_minutes_redact_task(self):
        raw = demo_raw()
        raw["council"]["task"] = "decide with sk-abcdefghijklmnopqrstuvwxyz"
        cfg = council.normalize_config(raw)
        minutes = council.Council(cfg).build_minutes(None, [])
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz", json.dumps(minutes))


class TestConfig(unittest.TestCase):
    def test_demo_config_normalises(self):
        cfg = council.normalize_config(demo_raw())
        self.assertEqual(cfg.mode, "council")
        self.assertEqual(cfg.synthesizer, "synth")
        self.assertEqual(cfg.plan, ["propose", "critique", "revise", "converge"])
        self.assertEqual(council.planned_calls(cfg), 4 + 4 + 4 + 1)

    def test_trim_plan_keeps_converge(self):
        plan = council.trim_plan(council.ROUND_PLANS["court"], 3)
        self.assertEqual(plan, ["propose", "critique", "converge"])

    def test_solo_mode(self):
        raw = demo_raw()
        raw["council"]["mode"] = "solo"
        cfg = council.normalize_config(raw)
        self.assertEqual(cfg.plan, ["propose", "converge"])

    def test_missing_task_rejected(self):
        raw = demo_raw()
        raw["council"].pop("task")
        with self.assertRaises(council.ConfigError):
            council.normalize_config(raw)

    def test_unknown_role_rejected(self):
        raw = demo_raw()
        raw["seats"][0]["role"] = "oracle"
        with self.assertRaises(council.ConfigError):
            council.normalize_config(raw)

    def test_duplicate_seat_rejected(self):
        raw = demo_raw()
        raw["seats"][1]["id"] = raw["seats"][0]["id"]
        with self.assertRaises(council.ConfigError):
            council.normalize_config(raw)

    def test_unknown_provider_rejected(self):
        raw = demo_raw()
        raw["seats"][0]["provider"] = "nope"
        with self.assertRaises(council.ConfigError):
            council.normalize_config(raw)

    def test_synthesizer_must_be_a_seat(self):
        raw = demo_raw()
        raw["synthesizer"] = "ghost"
        with self.assertRaises(council.ConfigError):
            council.normalize_config(raw)

    def test_missing_model_rejected(self):
        raw = demo_raw()
        raw["seats"][0].pop("model")
        with self.assertRaises(council.ConfigError):
            council.normalize_config(raw)


class TestCouncil(unittest.TestCase):
    def test_own_set_is_not_cross_reviewed(self):
        cfg = council.normalize_config(demo_raw())
        run = council.Council(cfg, log=lambda _m: None)
        run._assign_labels()
        for seat in cfg.seats:
            run.claims[seat.id] = {"seat": seat, "payload": {"claims": []}, "round": "propose"}
        for seat in cfg.seats:
            labelled = run._anonymised_sets(exclude=seat.id)
            self.assertNotIn(run.labels[seat.id], labelled)
            self.assertEqual(len(labelled), len(cfg.seats) - 1)

    def test_labels_are_anonymous_and_stable(self):
        cfg = council.normalize_config(demo_raw())
        first = council.Council(cfg, log=lambda _m: None)
        second = council.Council(cfg, log=lambda _m: None)
        first._assign_labels()
        second._assign_labels()
        self.assertEqual(first.labels, second.labels)
        self.assertTrue(all(re.fullmatch(r"SET-[A-Z]", v) for v in first.labels.values()))

    def test_demo_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            code = quiet(council.cmd_demo, argparse.Namespace(out=tmp, max_calls=0, seed=None))
            self.assertEqual(code, 0)
            for name in ("transcript.md", "minutes.md", "minutes.json"):
                self.assertTrue((Path(tmp) / name).exists(), name)
            minutes = json.loads((Path(tmp) / "minutes.json").read_text(encoding="utf-8"))
            self.assertEqual([r["name"] for r in minutes["rounds"]], ["propose", "critique", "revise", "converge"])
            self.assertTrue(minutes["decision"]["statement"])
            self.assertEqual(len(minutes["dissent"]), 1)
            self.assertTrue(minutes["contested"])
            self.assertTrue(all(call["ok"] for call in minutes["calls"]))
            transcript = (Path(tmp) / "transcript.md").read_text(encoding="utf-8")
            self.assertIn("独立思考，互不可见", transcript)
            self.assertIn("少数意见", transcript)
            self.assertIn("OFFLINE DEMO", transcript)

    def test_budget_stops_extra_calls_but_funds_convergence(self):
        with tempfile.TemporaryDirectory() as tmp:
            code = quiet(council.cmd_demo, argparse.Namespace(out=tmp, max_calls=3, seed=None))
            self.assertEqual(code, 0)
            minutes = json.loads((Path(tmp) / "minutes.json").read_text(encoding="utf-8"))
            self.assertLessEqual(len(minutes["calls"]), 3)
            self.assertTrue(minutes["budget"]["exhausted"])
            self.assertTrue(any(r["skipped"] for r in minutes["rounds"]))
            self.assertTrue(minutes["decision"]["statement"])

    def test_all_providers_down_exits_2(self):
        raw = demo_raw()
        for seat in raw["seats"]:
            seat["provider"] = "anthropic"
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "council.json"
            config_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
            previous = os.environ.pop("ANTHROPIC_API_KEY", None)
            try:
                code = quiet(
                    council.cmd_run,
                    argparse.Namespace(
                        config=str(config_path),
                        out=str(Path(tmp) / "out"),
                        env="",
                        dry_run=False,
                        language="",
                        max_calls=0,
                        seed=None,
                    ),
                )
            finally:
                if previous is not None:
                    os.environ["ANTHROPIC_API_KEY"] = previous
            self.assertEqual(code, 2)
            minutes = json.loads((Path(tmp) / "out" / "minutes.json").read_text(encoding="utf-8"))
            self.assertFalse(any(call["ok"] for call in minutes["calls"]))
            self.assertIn("no synthesis seat available", minutes["decision"]["statement"])

    def test_dry_run_makes_no_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "council.json"
            config_path.write_text(json.dumps(demo_raw(), ensure_ascii=False), encoding="utf-8")
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = council.cmd_run(
                    argparse.Namespace(
                        config=str(config_path), out="", env="", dry_run=True, language="", max_calls=0, seed=None
                    )
                )
            self.assertEqual(code, 0)
            self.assertIn("planned", buffer.getvalue())
            self.assertFalse((Path(tmp) / "out").exists())

    def test_court_mode_runs_red_team(self):
        raw = demo_raw()
        raw["council"]["mode"] = "court"
        cfg = council.normalize_config(raw)
        minutes = council.Council(cfg, log=lambda _m: None).run()
        self.assertEqual([r["name"] for r in minutes["rounds"]], ["propose", "critique", "revise", "redteam", "converge"])
        self.assertEqual(minutes["budget"]["calls_used"], 4 + 4 + 4 + 1 + 1)
        self.assertTrue(all(call["ok"] for call in minutes["calls"]))

    def test_config_with_bom_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "council.json"
            path.write_bytes(b"\xef\xbb\xbf" + json.dumps(demo_raw(), ensure_ascii=False).encode("utf-8"))
            cfg = council.normalize_config(council.read_config_file(path))
            self.assertEqual(len(cfg.seats), 5)

    def test_validate_warns_when_no_critic(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = demo_raw()
            raw["seats"] = [s for s in raw["seats"] if s["role"] != "critic"]
            path = Path(tmp) / "council.json"
            path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = council.cmd_validate(argparse.Namespace(config=str(path)))
            self.assertEqual(code, 0)
            self.assertIn("no `critic` seat", buffer.getvalue())

    def test_prompts_never_ask_for_agreement(self):
        cfg = council.normalize_config(demo_raw())
        seat = cfg.seats[0]
        critique_prompt = council.user_critique(cfg, seat, {"claims": []}, {"SET-B": {"claims": []}})
        self.assertIn("Do not agree for the sake of agreement.", critique_prompt)
        converge_prompt = council.user_converge(cfg, cfg.seats[-1], "record", "hint")
        self.assertIn("Preserve the sharpest minority argument", converge_prompt)
        propose_system = council.seat_system(seat, cfg)
        self.assertIn("Think independently", propose_system)
        self.assertIn("简体中文", propose_system)


class TestDocs(unittest.TestCase):
    def test_relative_links_resolve(self):
        missing: list[str] = []
        for md in ROOT.rglob("*.md"):
            if {"runs", "__pycache__", ".git"} & set(md.parts):
                continue
            for target in re.findall(r"\]\(([^)]+)\)", md.read_text(encoding="utf-8")):
                if target.startswith(("http://", "https://", "#", "mailto:")):
                    continue
                path = target.split("#")[0].strip()
                if path and not (md.parent / path).exists():
                    missing.append(f"{md.relative_to(ROOT)} -> {target}")
        self.assertEqual(missing, [], "broken relative links in docs")

    def test_every_reference_is_indexed(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        for path in sorted((ROOT / "references").glob("*.md")):
            self.assertIn(path.name, skill, f"{path.name} is not reachable from SKILL.md")


class TestSkillFile(unittest.TestCase):
    def test_frontmatter_matches_agent_skills_spec(self):
        path = ROOT / "SKILL.md"
        self.assertTrue(path.exists(), "SKILL.md is the entry point every agent discovery layer reads")
        text = path.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\n"), "SKILL.md must start with YAML frontmatter")
        front = text.split("---", 2)[1]
        name = re.search(r"^name:\s*(\S+)\s*$", front, re.M)
        desc = re.search(r"^description:\s*(.+)$", front, re.M)
        self.assertIsNotNone(name, "frontmatter needs `name`")
        self.assertIsNotNone(desc, "frontmatter needs `description`")
        assert name and desc
        self.assertRegex(name.group(1), r"^[a-z0-9]+(-[a-z0-9]+)*$")
        self.assertLessEqual(len(name.group(1)), 64)
        self.assertGreater(len(desc.group(1)), 40)
        self.assertLessEqual(len(desc.group(1)), 1024)
        self.assertIn("license:", front)


if __name__ == "__main__":
    unittest.main()
