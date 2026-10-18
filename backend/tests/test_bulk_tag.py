import boto3

from conftest import BOB, call, cloud, file_row, load, media_url, put_file, tag_rows, thumb_url  # noqa: F401

bulk = load("bulk_tag")


def test_apply_rules():
    assert bulk.apply({"fox": 2}, 1, {"fox": 1, "rabbit": 2}) == {"fox": 3, "rabbit": 2}
    assert bulk.apply({"fox": 3}, 0, {"fox": 1}) == {"fox": 2}
    assert bulk.apply({"fox": 1}, 0, {"fox": 2}) == {}
    assert bulk.apply({"fox": 1}, 0, {"rabbit": 1}) == {"fox": 1}      # missing tag ignored


def test_add_updates_both_tables(cloud):
    f = put_file("a", {"fox": 2})
    code, body, _ = call(bulk, "POST", "/tags/bulk",
                         {"urls": [media_url(f)], "operation": 1, "tags": {"Fox": 1, "rabbit": 2}},
                         user=BOB)                                      # not the uploader (D-01)
    assert code == 200 and body["updated"] == [media_url(f)]
    assert file_row(f)["tags"] == {"fox": 3, "rabbit": 2}
    assert tag_rows(f) == {"fox": 3, "rabbit": 2}


def test_remove_drops_tag_at_zero_and_ignores_missing(cloud):
    f = put_file("a", {"fox": 2, "cat": 1})
    code, body, _ = call(bulk, "POST", "/tags/bulk",
                         {"urls": [thumb_url(f)], "operation": 0,
                          "tags": {"fox": 5, "rabbit": 1}})
    assert code == 200 and body["updated"] == [thumb_url(f)]
    assert file_row(f)["tags"] == {"cat": 1}
    assert tag_rows(f) == {"cat": 1}


def test_not_found_and_processing_are_reported(cloud):
    busy = put_file("busy", {}, status="processing")
    bad = put_file("bad", {}, status="failed")
    code, body, _ = call(bulk, "POST", "/tags/bulk", {
        "urls": [media_url("0" * 64), "https://example.com/x.jpg", media_url(busy), media_url(bad)],
        "operation": 1, "tags": {"fox": 1}})
    assert code == 200
    assert body["notFound"] == [media_url("0" * 64), "https://example.com/x.jpg"]
    assert body["skipped"] == [{"url": media_url(busy), "reason": "processing"},
                               {"url": media_url(bad), "reason": "failed"}]
    assert file_row(busy)["tags"] == {}


def test_same_file_twice_is_edited_once(cloud):
    f = put_file("a", {"fox": 1})
    _, body, _ = call(bulk, "POST", "/tags/bulk",
                      {"urls": [media_url(f), thumb_url(f)], "operation": 1, "tags": {"fox": 1}})
    assert len(body["updated"]) == 2
    assert file_row(f)["tags"] == {"fox": 2}


def test_file_without_tags_map(cloud):
    f = put_file("a", {})
    t = boto3.resource("dynamodb", region_name="ap-southeast-2").Table("EcoGuardFiles")
    t.update_item(Key={"fileId": f}, UpdateExpression="REMOVE tags")
    _, body, _ = call(bulk, "POST", "/tags/bulk",
                      {"urls": [media_url(f)], "operation": 1, "tags": {"cane toad": 3}})
    assert body["updated"] == [media_url(f)]
    assert file_row(f)["tags"] == {"cane toad": 3}
    assert tag_rows(f) == {"cane toad": 3}


def test_concurrent_edit_is_retried_not_lost(cloud, monkeypatch):
    """Bob sets fox to 5 between Alice's read and her write. Both edits must survive."""
    f = put_file("a", {"fox": 2})
    real_get = bulk.files.get
    calls = {"n": 0}

    def get_then_race(file_id, consistent=False):
        item = real_get(file_id, consistent)
        calls["n"] += 1
        if calls["n"] == 1:
            t = boto3.resource("dynamodb", region_name="ap-southeast-2").Table("EcoGuardFiles")
            t.update_item(Key={"fileId": f}, UpdateExpression="SET tags.fox = :n",
                          ExpressionAttributeValues={":n": 5})
        return item

    monkeypatch.setattr(bulk.files, "get", get_then_race)
    _, body, _ = call(bulk, "POST", "/tags/bulk",
                      {"urls": [media_url(f)], "operation": 1, "tags": {"fox": 1}})
    assert body["updated"] == [media_url(f)]
    assert calls["n"] == 2                       # first write refused, second read + write ok
    assert file_row(f)["tags"] == {"fox": 6}     # Bob's 5, plus Alice's 1


def test_edit_to_other_tag_is_kept(cloud, monkeypatch):
    """Bob adds a rabbit while Alice adds a fox: no conflict, both kept."""
    f = put_file("a", {"fox": 2})
    real_get = bulk.files.get

    def get_then_race(file_id, consistent=False):
        item = real_get(file_id, consistent)
        t = boto3.resource("dynamodb", region_name="ap-southeast-2").Table("EcoGuardFiles")
        t.update_item(Key={"fileId": f}, UpdateExpression="SET tags.rabbit = :n",
                      ExpressionAttributeValues={":n": 1})
        return item

    monkeypatch.setattr(bulk.files, "get", get_then_race)
    call(bulk, "POST", "/tags/bulk", {"urls": [media_url(f)], "operation": 1, "tags": {"fox": 1}})
    assert file_row(f)["tags"] == {"fox": 3, "rabbit": 1}


def test_bad_operation_is_400(cloud):
    code, body, _ = call(bulk, "POST", "/tags/bulk",
                         {"urls": ["x"], "operation": 2, "tags": {"fox": 1}})
    assert code == 400 and body["error"]["code"] == "VALIDATION_ERROR"
