import pytest
from pydantic import ValidationError

from conftest import MEDIA, THUMBS, fid

from common import labels, urls
from common.expr import Expr
from common.schemas import BulkTagRequest, TagQuery


def test_normalise_spaces_case_and_synonyms():
    assert labels.normalise("  Cane   Toad ") == "cane toad"
    assert labels.normalise("toads") == "cane toad"
    assert labels.normalise("Feral Pig") == "feral pig"
    assert labels.normalise("quoll") == "quoll"          # unknown species pass through (D-04)


def test_rekognition_mapping():
    assert labels.from_rekognition("Fox") == "fox"
    assert labels.from_rekognition("Hog") == "feral pig"
    assert labels.from_rekognition("Car") is None


def test_parse_media_thumb_and_presigned_urls():
    f = fid("a")
    assert urls.parse_file_url(f"https://{MEDIA}.s3.ap-southeast-2.amazonaws.com/media/{f}.mp4") == (f, "mp4")
    assert urls.parse_file_url(f"https://{THUMBS}.s3.ap-southeast-2.amazonaws.com/thumbs/{f}.jpg") == (f, None)
    signed = f"https://{MEDIA}.s3.ap-southeast-2.amazonaws.com/media/{f}.jpg?X-Amz-Signature=abc"
    assert urls.parse_file_url(signed) == (f, "jpg")
    assert urls.parse_file_url(f"https://{MEDIA}.s3.amazonaws.com/media/{f}.jpg") == (f, "jpg")


H = "a" * 64


@pytest.mark.parametrize("bad", [
    f"http://{MEDIA}.s3.ap-southeast-2.amazonaws.com/media/{H}.jpg",           # not https
    f"https://someone-else.s3.ap-southeast-2.amazonaws.com/media/{H}.jpg",     # other bucket
    f"https://{MEDIA}.s3.ap-southeast-2.amazonaws.com/media/abc.jpg",          # not a sha256
    f"https://{MEDIA}.s3.ap-southeast-2.amazonaws.com/media/{H}.exe",
    f"https://{MEDIA}.s3.evil.com/media/{H}.jpg",
    f"https://{THUMBS}.s3.ap-southeast-2.amazonaws.com/media/{H}.jpg",         # media path, thumbs bucket
    "not a url",
])
def test_parse_rejects_foreign_urls(bad):
    assert urls.parse_file_url(bad) is None


def test_expr_placeholders_for_reserved_words_and_spaces():
    e = Expr()
    cond = f"{e.name('tags')}.{e.name('feral pig')} >= {e.value(1)} AND {e.name('tags')} <> {e.value(2)}"
    assert cond == "#n0.#n1 >= :v0 AND #n0 <> :v1"
    assert e.names == {"#n0": "tags", "#n1": "feral pig"}


def test_tag_query_validation():
    q = TagQuery.model_validate({"tags": {" Fox ": 2, "toad": 1}, "from": "2026-10-01"})
    assert q.tags == {"fox": 2, "cane toad": 1}
    assert q.from_ == "2026-10-01T00:00:00Z"
    for bad in ({"tags": {}}, {"tags": {"fox": 0}}, {"tags": {"fox": True}},
                {"tags": {"fox": "2"}}, {"tags": {"fox": 1}, "limit": 101},
                {"tags": {"fox": 1}, "from": "yesterday"}):
        with pytest.raises(ValidationError):
            TagQuery.model_validate(bad)


def test_bulk_operation_must_be_0_or_1():
    ok = {"urls": ["x"], "tags": {"fox": 1}}
    BulkTagRequest.model_validate({**ok, "operation": 0})
    for op in (2, -1, "1", True):
        with pytest.raises(ValidationError):
            BulkTagRequest.model_validate({**ok, "operation": op})
