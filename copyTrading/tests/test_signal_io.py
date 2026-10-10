from datetime import date

from copytrade.signal_io import read_new, signal_path


def test_reads_incrementally_by_offset(tmp_path):
    path = signal_path(tmp_path, date(2026, 10, 10))
    path.write_text('{"v":1,"id":"1","ts":1760000000,"aksi":"tutup","pos_id":7}\n', encoding="utf-8")
    first = read_new(path, 0)
    assert [record.signal.id for record in first.records] == ["1"]
    assert first.offset == path.stat().st_size
    assert read_new(path, first.offset).records == ()


def test_partial_line_waits_until_newline(tmp_path):
    path = signal_path(tmp_path, date(2026, 10, 10))
    complete = '{"v":1,"id":"1","ts":1760000000,"aksi":"tutup","pos_id":7}\n'
    path.write_bytes(complete.encode() + b'{"v":1,"id":"2"')
    first = read_new(path, 0)
    assert [record.signal.id for record in first.records] == ["1"]
    assert first.has_partial_line
    assert first.offset == len(complete.encode())
    with path.open("ab") as stream:
        stream.write(b',"ts":1760000000,"aksi":"tutup","pos_id":8}\n')
    second = read_new(path, first.offset)
    assert [record.signal.id for record in second.records] == ["2"]


def test_day_rollover_uses_distinct_file_names():
    assert signal_path("signals", date(2026, 10, 9)).name == "sinyal_20261009.jsonl"
    assert signal_path("signals", date(2026, 10, 10)).name == "sinyal_20261010.jsonl"


def test_offset_recovers_if_daily_file_was_truncated(tmp_path):
    path = signal_path(tmp_path, date(2026, 10, 10))
    path.write_text('{"v":1,"id":"1","ts":1760000000,"aksi":"tutup","pos_id":7}\n', encoding="utf-8")
    result = read_new(path, 5000)
    assert [record.signal.id for record in result.records] == ["1"]
