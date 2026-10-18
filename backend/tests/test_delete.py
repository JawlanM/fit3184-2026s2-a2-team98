from unittest import mock

from conftest import (ALICE, BOB, MEDIA, THUMBS, call, cloud, file_row, load,  # noqa: F401
                      media_url, put_file, s3_keys, tag_rows, thumb_url)

delete = load("delete")


def test_uploader_deletes_rows_and_objects(cloud):
    f = put_file("a", {"fox": 1, "cat": 2})
    keep = put_file("b", {"fox": 1})
    code, body, _ = call(delete, "POST", "/files/delete", {"urls": [media_url(f)]}, user=ALICE)
    assert code == 200 and body == {"deleted": [media_url(f)], "notFound": [], "failed": []}
    assert file_row(f) is None and tag_rows(f) == {}
    assert s3_keys(MEDIA) == [f"media/{keep}.jpg"]
    assert s3_keys(THUMBS) == [f"thumbs/{keep}.jpg"]


def test_other_user_gets_403(cloud):
    f = put_file("a", {"fox": 1}, owner=ALICE)
    code, body, _ = call(delete, "POST", "/files/delete", {"urls": [media_url(f)]}, user=BOB)
    assert code == 403 and body["error"]["code"] == "FORBIDDEN"
    assert file_row(f) is not None


def test_mixed_list_reports_forbidden_in_failed(cloud):
    mine = put_file("mine", {"fox": 1}, owner=BOB)
    theirs = put_file("theirs", {"fox": 1}, owner=ALICE)
    code, body, _ = call(delete, "POST", "/files/delete",
                         {"urls": [thumb_url(mine), media_url(theirs), media_url("1" * 64)]}, user=BOB)
    assert code == 200
    assert body == {"deleted": [thumb_url(mine)], "notFound": [media_url("1" * 64)],
                    "failed": [media_url(theirs)]}


def test_retry_after_s3_failure_cleans_leftovers(cloud):
    f = put_file("a", {"fox": 1}, ext="mp4")
    with mock.patch.object(delete, "purge_s3", side_effect=RuntimeError("network")):
        _, body, _ = call(delete, "POST", "/files/delete", {"urls": [thumb_url(f)]})
    assert body["failed"] == [thumb_url(f)]
    assert file_row(f) is None                       # step 1 done
    assert f"media/{f}.mp4" in s3_keys(MEDIA)         # step 2 not done

    _, body, _ = call(delete, "POST", "/files/delete", {"urls": [thumb_url(f)]})
    assert body["notFound"] == [thumb_url(f)]
    assert s3_keys(MEDIA) == [] and s3_keys(THUMBS) == []   # D-08: still cleaned
