"""Tests for the R1 deterministic cleaning pipeline (tools/r1_clean.py).

Covers what the R1 brief demands be tested: Unicode handling, Chinese
punctuation, headings glued to body text, protected abbreviations, repeated
imports of the same file, and malformed input. No AI is involved anywhere.
"""
from __future__ import annotations

import hashlib
import json
import unicodedata
from pathlib import Path

import pytest

from tools import r1_clean as r1


def _doc() -> "r1.Doc":
    return r1.Doc(
        source_name="x.txt", source_path="x.txt",
        source_sha256="0" * 64, encoding="utf-8",
        bytes=0, chars=0, crlf=0, lone_cr=0, lf=0,
    )


def _write(tmp_path: Path, name: str, text: str, encoding: str = "utf-8",
           newline: str = "\n") -> Path:
    p = tmp_path / name
    p.write_bytes(text.encode(encoding) if newline == "\n"
                  else text.replace("\n", newline).encode(encoding))
    return p


# ---------------------------------------------------------------- unicode

def test_nfc_normalisation_and_fullwidth_fold():
    doc = _doc()
    out = r1.normalise_text("ＡＢＣ１２３ 中文　全角", doc)
    assert "ABC123" in out           # full-width ASCII folded
    assert unicodedata.is_normalized("NFC", out)
    assert any(op.operation == "fold_fullwidth_ascii" for op in doc.ops)


def test_fullwidth_punctuation_is_not_rewritten():
    """NFKC would turn ，。 into , . — that would改变 the corpus punctuation."""
    doc = _doc()
    out = r1.normalise_text("动物，植物。", doc)
    assert "，" in out and "。" in out


def test_control_characters_removed_and_logged():
    doc = _doc()
    out = r1.normalise_text("动物\u0007界\u200b", doc)
    assert "\u0007" not in out
    assert any(op.operation == "remove_control_char" for op in doc.ops)


# ---------------------------------------------------------------- latex

def test_latex_arrow_becomes_symbol():
    doc = _doc()
    assert "→" in r1.replace_latex("A $\\rightarrow$ B", doc)


def test_unknown_latex_command_is_kept_and_warned():
    doc = _doc()
    out = r1.replace_latex("x $\\foo{bar}$ y", doc)
    assert "\\foo" in out
    assert any("latex" in w for w in doc.warnings)


# ---------------------------------------------------------------- diagrams

def test_box_drawing_block_removed_but_real_text_kept():
    doc = _doc()
    block = "┌───┬───┐\n│ a │ b │\n└───┴───┘"
    text = "植物细胞\n" + block + "\n细胞壁由纤维素构成。"
    out = r1.strip_diagrams(text, doc)
    assert "纤维素" in out
    assert "┌" not in out
    assert any(op.operation == "remove_diagram_line" for op in doc.ops)


def test_tree_prefix_stripped_text_preserved():
    doc = _doc()
    out = r1.strip_diagrams("├─动物界\n└─植物界", doc)
    assert "动物界" in out and "植物界" in out
    assert "├" not in out


# ---------------------------------------------------------------- headings

def test_chapter_heading_split_from_body():
    doc = _doc()
    h = r1.detect_heading("第二章 植物王国：地球生态植物界（Plantae）是由多细胞真核生物组成的。", doc, 1)
    assert h is not None and h["kind"] == "chapter"
    assert h["title"].startswith("第二章")
    assert "植物界" in h["remainder"]


def test_numbered_section_heading():
    doc = _doc()
    h = r1.detect_heading("3. 爬行动物纲 (Reptilia)爬行动物是第一批登陆的脊椎动物。", doc, 1)
    assert h is not None and h["kind"] == "section_num"
    assert h["version" if False else "title"].endswith("(Reptilia)")


def test_heading_glued_without_evidence_is_reported_not_guessed():
    doc = _doc()
    h = r1.detect_heading("第四章 人体生物学：精妙绝伦的生命系统人体生物学研究微观结构。", doc, 1)
    assert h is not None
    assert h["boundary"] == "unresolved"
    assert h["title"] == "第四章"
    assert "人体生物学研究微观结构" in h["remainder"]
    assert doc.warnings


def test_chapter_word_inside_sentence_is_not_a_heading():
    doc = _doc()
    assert r1.detect_heading("书中提到的第二章并不在此处。", doc, 1) is None


# ---------------------------------------------------------------- sentences

def test_chinese_punctuation_splits_sentences():
    doc = _doc()
    sents = r1.split_sentences("动物是异养生物。鸟类有羽毛！鱼用鳃呼吸？", False)
    assert [s for s, _ in sents] == ["动物是异养生物。", "鸟类有羽毛！", "鱼用鳃呼吸？"]


def test_decimal_and_abbreviations_are_not_split():
    doc = _doc()
    text = "圆周率约为 3.14。U.S. 独立战争始于 1775 年。详见 https://example.com/a.b。"
    sents = [s for s, _ in r1.split_sentences(text, False)]
    assert len(sents) == 3
    assert "3.14" in sents[0]
    assert "U.S." in sents[1]
    assert "https://example.com/a.b" in sents[2]


def test_semicolon_split_is_opt_in():
    doc = _doc()
    assert len(r1.split_sentences("甲；乙。", False)) == 1
    assert len(r1.split_sentences("甲；乙。", True)) == 2


def test_search_form_keeps_han_and_latin():
    form = r1.search_form("门（Chordata）是…１２３")
    assert "chordata" in form
    assert "门" in form


# ---------------------------------------------------------------- pipeline

def test_pipeline_is_deterministic_and_ids_are_stable(tmp_path):
    src = _write(tmp_path, "doc.txt", "第一章 动物界\n动物界（Animalia）是最大的类群。\n")
    a = r1.process_document(src, tmp_path / "out1")
    b = r1.process_document(src, tmp_path / "out2")
    assert [s["sentence_id"] for s in a.sentences] == [s["sentence_id"] for s in b.sentences]
    assert a.sentences[0]["text"] == b.sentences[0]["text"]


def test_same_file_twice_is_one_manifest_hash(tmp_path):
    src = _write(tmp_path, "doc.txt", "动物界是最大类群。\n")
    r1.process_document(src, tmp_path / "out")
    r1.process_document(src, tmp_path / "out")
    manifest = json.loads((tmp_path / "out" / "manifest.json").read_text(encoding="utf-8"))
    digest = hashlib.sha256(src.read_bytes()).hexdigest()
    assert manifest[digest]["imports"] == 2
    assert len(manifest) == 1


def test_crlf_converted_and_counted(tmp_path):
    src = _write(tmp_path, "doc.txt", "甲。\n乙。\n", newline="\r\n")
    doc = r1.process_document(src, tmp_path / "out")
    assert doc.crlf == 2
    assert any(op.operation == "normalise_line_endings" for op in doc.ops)


def test_source_file_is_never_modified(tmp_path):
    src = _write(tmp_path, "doc.txt", "第一章 动物界\n动物界（Animalia）是最大类群。\n")
    before = src.read_bytes()
    r1.process_document(src, tmp_path / "out")
    assert src.read_bytes() == before


def test_malformed_encoding_is_reported_not_silently_replaced(tmp_path):
    bad = tmp_path / "bad.txt"
    bad.write_bytes(b"\xff\xfe broken utf-8 \x80")
    doc = r1.process_document(bad, tmp_path / "out")
    assert any("UTF-8 decode failed" in w for w in doc.warnings)


def test_every_record_traces_back_to_a_source_line(tmp_path):
    src = _write(tmp_path, "doc.txt", "第一章 动物界\n动物界（Animalia）是最大类群。\n植物界（Plantae）营光合作用。\n")
    doc = r1.process_document(src, tmp_path / "out")
    for s in doc.sentences:
        assert 1 <= s["line"] <= 3
        assert s["source_sha256"] == doc.source_sha256


def test_no_content_lost_when_join_happens(tmp_path):
    """A hard-wrapped sentence must come out whole, not truncated."""
    head = "动物界由多细胞真核生物构成，"
    src = _write(tmp_path, "doc.txt", "第一章 动物界\n" + head + "\n并通过异养方式获取营养。\n")
    doc = r1.process_document(src, tmp_path / "out")
    joined = " ".join(s["text"] for s in doc.sentences)
    assert head in joined and "并通过异养方式获取营养。" in joined


