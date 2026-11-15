"""CSV/JSONL reader, error locality and roster fingerprint tests."""

from __future__ import annotations

import pytest

from sample_attest.codes import (
    DATASET_BLANK_LINE,
    DATASET_DUPLICATE_KEY,
    DATASET_EMPTY,
    DATASET_ENCODING_ERROR,
    DATASET_FILE_NOT_FOUND,
    DATASET_INVALID_FORMAT,
    DATASET_MISSING_KEY,
    DATASET_MISSING_KEY_FIELD,
    DATASET_PARSE_ERROR,
)
from sample_attest.dataset_loader import DatasetLoadError, load_dataset


def write_csv(tmp_path, text, name="data.csv", encoding="utf-8"):
    path = tmp_path / name
    path.write_text(text, encoding=encoding)
    return path


def load(path, fmt="csv", key="subject_id"):
    return load_dataset(path, fmt, key)


def error_codes(exc):
    return [item["code"] for item in exc.value.errors]


def test_csv_loads_and_metadata(small_dataset):
    assert small_dataset.row_count == 30
    assert small_dataset.fieldnames == ["subject_id", "region", "segment", "cluster_id"]
    assert small_dataset.keys[0] == "subject_0001"
    assert len(small_dataset.population_fingerprint) == 64
    assert small_dataset.blank_value_rows == 0


def test_csv_utf8_sig(small_dataset, tmp_path):
    text = "subject_id,name\nsubject_0001,alpha\nsubject_0002,beta\n"
    path = tmp_path / "bom.csv"
    path.write_text(text, encoding="utf-8-sig")
    loaded = load(path)
    assert loaded.row_count == 2
    assert loaded.rows[0]["name"] == "alpha"


def test_population_hash_ignores_row_order(tmp_path):
    left = write_csv(
        tmp_path,
        "subject_id,value\nsubject_0002,b\nsubject_0001,a\nsubject_0003,c\n",
        "left.csv",
    )
    right = write_csv(
        tmp_path,
        "subject_id,value\nsubject_0003,c\nsubject_0001,a\nsubject_0002,b\n",
        "right.csv",
    )
    assert load(left).population_fingerprint == load(right).population_fingerprint


def test_csv_missing_key_field(tmp_path):
    path = write_csv(tmp_path, "id,value\nsubject_0001,x\n")
    with pytest.raises(DatasetLoadError) as exc:
        load(path)
    assert DATASET_MISSING_KEY_FIELD in error_codes(exc)


def test_csv_duplicate_key_locates_line(tmp_path):
    path = write_csv(
        tmp_path,
        "subject_id,value\nsubject_0001,a\nsubject_0002,b\nsubject_0001,c\n",
    )
    with pytest.raises(DatasetLoadError) as exc:
        load(path)
    duplicate = [e for e in exc.value.errors if e["code"] == DATASET_DUPLICATE_KEY][0]
    assert duplicate["line"] == 4
    assert duplicate["previous_line"] == 2


def test_csv_missing_key_value(tmp_path):
    path = write_csv(tmp_path, "subject_id,value\nsubject_0001,a\n,b\n")
    with pytest.raises(DatasetLoadError) as exc:
        load(path)
    missing = [e for e in exc.value.errors if e["code"] == DATASET_MISSING_KEY][0]
    assert missing["line"] == 3


def test_csv_bad_width(tmp_path):
    path = write_csv(tmp_path, "subject_id,value\nsubject_0001,a,extra\n")
    with pytest.raises(DatasetLoadError) as exc:
        load(path)
    assert DATASET_PARSE_ERROR in error_codes(exc)


def test_csv_empty_file(tmp_path):
    path = write_csv(tmp_path, "")
    with pytest.raises(DatasetLoadError) as exc:
        load(path)
    assert DATASET_EMPTY in error_codes(exc)


def test_csv_blank_line_warns_and_skips(tmp_path):
    path = write_csv(tmp_path, "subject_id,value\nsubject_0001,a\n\nsubject_0002,b\n")
    loaded = load(path)
    assert loaded.row_count == 2
    assert DATASET_BLANK_LINE in [item["code"] for item in loaded.warnings]


def test_blank_values_are_counted_not_dropped(tmp_path):
    path = write_csv(
        tmp_path,
        "subject_id,value\nsubject_0001,\nsubject_0002,b\nsubject_0003,\n",
    )
    loaded = load(path)
    assert loaded.row_count == 3
    assert loaded.blank_value_rows == 2


def test_jsonl_loads(cluster_dataset):
    assert cluster_dataset.row_count == 48
    assert cluster_dataset.format == "jsonl"
    assert "cluster" in cluster_dataset.fieldnames
    assert cluster_dataset.rows[0]["subject_id"] == "subject_2001"


def test_jsonl_duplicate_and_bad_line(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text(
        '{"subject_id":"subject_0001"}\n'
        '{"subject_id":"subject_0001"}\n'
        "not json\n",
        encoding="utf-8",
    )
    with pytest.raises(DatasetLoadError) as exc:
        load(path, "jsonl")
    assert DATASET_DUPLICATE_KEY in error_codes(exc)
    assert DATASET_PARSE_ERROR in error_codes(exc)
    assert [e.get("line") for e in exc.value.errors] == [2, 3]


def test_jsonl_missing_key(tmp_path):
    path = tmp_path / "missing.jsonl"
    path.write_text('{"value":"x"}\n', encoding="utf-8")
    with pytest.raises(DatasetLoadError) as exc:
        load(path, "jsonl")
    assert DATASET_MISSING_KEY_FIELD in error_codes(exc)


def test_jsonl_empty_and_blank_file(tmp_path):
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(DatasetLoadError) as exc:
        load(empty, "jsonl")
    assert DATASET_EMPTY in error_codes(exc)
    blank = tmp_path / "blank.jsonl"
    blank.write_text("\n\n", encoding="utf-8")
    with pytest.raises(DatasetLoadError) as exc:
        load(blank, "jsonl")
    assert DATASET_EMPTY in error_codes(exc)


def test_invalid_encoding(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_bytes(b"subject_id,value\nsubject_0001,\xff\xfe\n")
    with pytest.raises(DatasetLoadError) as exc:
        load(path)
    assert DATASET_ENCODING_ERROR in error_codes(exc)


def test_invalid_format_and_missing_file(tmp_path):
    good = write_csv(tmp_path, "subject_id\nsubject_0001\n")
    with pytest.raises(DatasetLoadError) as exc:
        load(good, "parquet")
    assert DATASET_INVALID_FORMAT in error_codes(exc)
    with pytest.raises(DatasetLoadError) as exc:
        load(tmp_path / "absent.csv")
    assert DATASET_FILE_NOT_FOUND in error_codes(exc)
