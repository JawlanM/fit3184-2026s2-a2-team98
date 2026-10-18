import json
from unittest import mock

from boto3.dynamodb.types import TypeSerializer

from conftest import load

notifier = load("notifier")
_s = TypeSerializer()

BASE = {"fileId": "f" * 64, "uploadedAt": "2026-10-20T03:15:00Z", "location": "Clayton VIC"}


def _img(item):
    return {k: _s.serialize(v) for k, v in item.items()}


def _rec(old, new, seq="1"):
    d = {"SequenceNumber": seq, "NewImage": _img(new)}
    if old is not None:
        d["OldImage"] = _img(old)
    return {"eventName": "MODIFY" if old else "INSERT", "dynamodb": d}


def ready(tags):
    return {**BASE, "status": "ready", "tags": tags}


def test_gained_table_from_d02():
    g = notifier.gained_species
    processing = {**BASE, "status": "processing"}
    assert g({}, {**processing, "tags": {}}) == {}                      # placeholder
    assert g(processing, ready({"fox": 2})) == {"fox": 2}               # ML result
    assert g(processing, ready({})) == {}                               # nothing detected
    assert g(processing, {**BASE, "status": "failed"}) == {}            # ML failed
    assert g(ready({"fox": 2}), ready({"fox": 2})) == {}                # retry, same tags
    assert g(ready({"fox": 2}), ready({"fox": 3})) == {"fox": 3}        # count up
    assert g(ready({"fox": 2}), ready({"fox": 2, "rabbit": 1})) == {"rabbit": 1}
    assert g(ready({"fox": 2}), ready({"fox": 1})) == {}                # removal


def test_handler_publishes_with_species_attribute():
    sns = mock.Mock()
    with mock.patch.object(notifier.aws, "sns", return_value=sns):
        out = notifier.handler({"Records": [
            _rec({**BASE, "status": "processing"}, ready({"fox": 2})),
            _rec(ready({"fox": 2}), ready({"fox": 2}), seq="2"),
        ]}, None)
    assert out == {"batchItemFailures": []}
    assert sns.publish.call_count == 1
    kw = sns.publish.call_args.kwargs
    assert kw["MessageAttributes"]["species"]["DataType"] == "String.Array"
    assert json.loads(kw["MessageAttributes"]["species"]["StringValue"]) == ["fox"]
    assert "fox: 2" in kw["Message"] and "Clayton VIC" in kw["Message"]
    assert f"/files/{'f' * 64}" in kw["Message"]
    assert "X-Amz" not in kw["Message"]                          # no expiring links in email
    assert len(kw["Subject"]) <= 100


def test_failed_publish_reports_only_that_record():
    sns = mock.Mock()
    sns.publish.side_effect = [RuntimeError("throttled"), None]
    with mock.patch.object(notifier.aws, "sns", return_value=sns):
        out = notifier.handler({"Records": [
            _rec(None, ready({"fox": 1}), seq="10"),
            _rec(None, ready({"cat": 1}), seq="11"),
        ]}, None)
    assert out == {"batchItemFailures": [{"itemIdentifier": "10"}]}


def test_long_subject_is_cut_to_100():
    s = notifier.subject({f"species number {i}": i for i in range(20)})
    assert len(s) == 100
