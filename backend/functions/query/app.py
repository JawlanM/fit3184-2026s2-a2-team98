"""POST /query/tags, /query/species, /query/thumbnail (owner A)."""
from fastapi import Request

from common import queries, web
from common.schemas import QueryResponse, SpeciesQuery, TagQuery, ThumbnailQuery, ThumbnailResponse

app = web.create_app()


@app.post("/query/tags", response_model=QueryResponse)
def query_tags(body: TagQuery, request: Request):
    return queries.find_by_tags(body.tags, web.caller(request), frm=body.from_, to=body.to,
                                limit=body.limit, next_token=body.nextToken)


@app.post("/query/species", response_model=QueryResponse)
def query_species(body: SpeciesQuery, request: Request):
    return queries.find_by_species(body.species, web.caller(request), frm=body.from_, to=body.to,
                                   limit=body.limit, next_token=body.nextToken)


@app.post("/query/thumbnail", response_model=ThumbnailResponse)
def query_thumbnail(body: ThumbnailQuery, request: Request):
    return queries.full_size_for_thumbnail(body.thumbnailUrl, web.caller(request))


handler = web.make_handler(app)
