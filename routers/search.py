"""
routers/search.py — Tool 2: Hybrid search
GET /api/search
"""

import os
from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizedQuery
from azure.identity import ManagedIdentityCredential

router = APIRouter()

def get_search_client():
    endpoint = os.environ["SEARCH_ENDPOINT"]
    index    = os.environ["SEARCH_INDEX"]
    cred     = ManagedIdentityCredential()
    return SearchClient(endpoint=endpoint, index_name=index, credential=cred)

@router.get("/api/search")
def search(
    q:          str            = Query(..., min_length=2),
    top:        int            = Query(5,  ge=1, le=20),
    chunk_type: Optional[str]  = Query(None)
):
    try:
        client  = get_search_client()
        filters = f"chunk_type eq '{chunk_type}'" if chunk_type else None

        results = client.search(
            search_text=q,
            top=top,
            filter=filters,
            query_type="semantic",
            semantic_configuration_name="eln-semantic",
            query_caption="extractive",
            vector_queries=[
                VectorizedQuery(
                    text=q,
                    k_nearest_neighbors=50,
                    fields="embedding",
                    exhaustive=False
                )
            ],
            select=[
                "id", "exp_number_full", "chunk_type",
                "experiment_id", "project_code",
                "title", "author", "content",
                "@search.reranker_score"
            ]
        )

        output = []
        for r in results:
            output.append({
                "id":              r.get("id"),
                "exp_number_full": r.get("exp_number_full"),
                "chunk_type":      r.get("chunk_type"),
                "experiment_id":   r.get("experiment_id"),
                "project_code":    r.get("project_code"),
                "title":           r.get("title"),
                "author":          r.get("author"),
                "content":         r.get("content"),
                "reranker_score":  r.get("@search.reranker_score"),
            })

        return {"query": q, "count": len(output), "results": output}

    except Exception as e:
        raise HTTPException(500, detail=str(e))
