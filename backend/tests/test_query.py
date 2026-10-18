from conftest import ALICE, BOB, call, cloud, load, put_file, thumb_url  # noqa: F401

query = load("query")


def test_and_with_minimum_counts(cloud):
    both = put_file("both", {"feral pig": 1, "cane toad": 3})
    put_file("few toads", {"feral pig": 2, "cane toad": 2})
    put_file("pig only", {"feral pig": 5})
    code, body, headers = call(query, "POST", "/query/tags",
                               {"tags": {"Feral Pig": 1, "cane toad": 3}})
    assert code == 200
    assert [r["fileId"] for r in body["results"]] == [both]
    assert headers["Access-Control-Allow-Origin"] == "http://localhost:5173"
    r = body["results"][0]
    assert r["tags"] == {"feral pig": 1, "cane toad": 3}
    assert r["viewUrl"].startswith("https://") and "X-Amz-Signature" in r["viewUrl"]
    assert "embedding" not in r


def test_species_and_newest_first(cloud):
    old = put_file("old cat", {"cat": 1}, at="2026-10-01T00:00:00Z")
    new = put_file("new cat", {"cat": 2}, at="2026-10-21T00:00:00Z")
    put_file("dog", {"dog": 1})
    code, body, _ = call(query, "POST", "/query/species", {"species": ["cats"]})
    assert code == 200
    assert [r["fileId"] for r in body["results"]] == [new, old]


def test_date_filter(cloud):
    put_file("old", {"fox": 1}, at="2026-10-01T00:00:00Z")
    new = put_file("new", {"fox": 1}, at="2026-10-21T08:00:00Z")
    _, body, _ = call(query, "POST", "/query/tags",
                      {"tags": {"fox": 1}, "from": "2026-10-21T00:00:00Z", "to": "2026-10-21T23:59:59Z"})
    assert [r["fileId"] for r in body["results"]] == [new]


def test_paging_returns_every_match_once(cloud):
    ids = {put_file(f"f{i}", {"fox": 1}, at=f"2026-10-{10 + i:02d}T00:00:00Z") for i in range(7)}
    seen, token = [], None
    while True:
        req = {"tags": {"fox": 1}, "limit": 3}
        if token:
            req["nextToken"] = token
        _, body, _ = call(query, "POST", "/query/tags", req)
        seen += [r["fileId"] for r in body["results"]]
        token = body["nextToken"]
        if not token:
            break
    assert sorted(seen) == sorted(ids) and len(seen) == 7


def test_token_from_other_search_is_rejected(cloud):
    for i in range(3):
        put_file(f"f{i}", {"fox": 1, "cat": 1})
    _, body, _ = call(query, "POST", "/query/tags", {"tags": {"fox": 1}, "limit": 1})
    code, err, _ = call(query, "POST", "/query/tags",
                        {"tags": {"cat": 1}, "limit": 1, "nextToken": body["nextToken"]})
    assert code == 400 and err["error"]["code"] == "VALIDATION_ERROR"


def test_private_files_only_for_their_uploader(cloud):
    mine = put_file("mine", {"fox": 1}, owner=ALICE, visibility="private")
    pub = put_file("public", {"fox": 1}, owner=ALICE)
    _, body, _ = call(query, "POST", "/query/tags", {"tags": {"fox": 1}}, user=BOB)
    assert [r["fileId"] for r in body["results"]] == [pub]
    _, body, _ = call(query, "POST", "/query/tags", {"tags": {"fox": 1}}, user=ALICE)
    assert {r["fileId"] for r in body["results"]} == {mine, pub}


def test_validation_errors_are_400_in_contract_shape(cloud):
    code, body, headers = call(query, "POST", "/query/tags", {"tags": {"fox": 0}})
    assert code == 400
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert "tags" in body["error"]["message"]
    assert headers["Access-Control-Allow-Origin"] == "http://localhost:5173"


def test_thumbnail_to_full_size(cloud):
    f = put_file("t", {"fox": 1})
    code, body, _ = call(query, "POST", "/query/thumbnail",
                         {"thumbnailUrl": thumb_url(f) + "?X-Amz-Signature=old"})
    assert code == 200
    assert body["fileId"] == f and body["url"].endswith(f"/media/{f}.jpg")
    assert "X-Amz-Signature" in body["viewUrl"]


def test_thumbnail_unknown_is_404(cloud):
    code, body, _ = call(query, "POST", "/query/thumbnail", {"thumbnailUrl": thumb_url("0" * 64)})
    assert code == 404 and body["error"]["code"] == "NOT_FOUND"
    code, _, _ = call(query, "POST", "/query/thumbnail", {"thumbnailUrl": "https://example.com/x.jpg"})
    assert code == 404
