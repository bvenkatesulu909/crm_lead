"""Catalogue endpoints: /api/v1/products and /api/v1/price-books.

Thin layer: check the caller's coarse permission (RBAC), call the service, commit once.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.db import get_db_session
from app.core.errors import problem_responses
from app.modules.catalog import service
from app.modules.catalog.schemas import (
    PriceBookCreate,
    PriceBookRead,
    PriceBookUpdate,
    PriceRead,
    PriceSet,
    ProductCreate,
    ProductPage,
    ProductRead,
    ProductUpdate,
)
from app.modules.identity.api import require_any_permission

router = APIRouter(tags=["catalogue"], responses=problem_responses(401, 403))
Reader = Annotated[Principal, Depends(require_any_permission(Permission.CATALOG_READ))]
Manager = Annotated[Principal, Depends(require_any_permission(Permission.CATALOG_MANAGE))]
Db = Annotated[Session, Depends(get_db_session)]


@router.get("/products", summary="List and search products")
def list_products(
    principal: Reader,
    session: Db,
    q: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    active: bool | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=100_000),
) -> ProductPage:
    items, total = service.list_products(
        session, principal, q=q.strip() if q else None, active=active, limit=limit, offset=offset
    )
    return ProductPage(
        items=[ProductRead.model_validate(p) for p in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/products",
    status_code=status.HTTP_201_CREATED,
    summary="Add a product (managers)",
    responses=problem_responses(409, 422),
)
def create_product(
    data: ProductCreate, principal: Manager, session: Db, response: Response
) -> ProductRead:
    product = service.create_product(session, principal, data)
    session.commit()
    response.headers["Location"] = f"/api/v1/products/{product.id}"
    return ProductRead.model_validate(product)


@router.get("/products/{product_id}", summary="Get one product", responses=problem_responses(404))
def get_product(product_id: uuid.UUID, principal: Reader, session: Db) -> ProductRead:
    return ProductRead.model_validate(service.get_product(session, principal, product_id))


@router.patch(
    "/products/{product_id}",
    summary="Change or deactivate a product (managers)",
    responses=problem_responses(404, 409, 422),
)
def update_product(
    product_id: uuid.UUID, data: ProductUpdate, principal: Manager, session: Db
) -> ProductRead:
    product = service.update_product(session, principal, product_id, data)
    session.commit()
    return ProductRead.model_validate(product)


@router.get("/price-books", summary="List price books")
def list_price_books(
    principal: Reader, session: Db, active: bool | None = None
) -> list[PriceBookRead]:
    return [
        PriceBookRead.model_validate(b)
        for b in service.list_price_books(session, principal, active=active)
    ]


@router.post(
    "/price-books",
    status_code=status.HTTP_201_CREATED,
    summary="Create a price book (managers)",
    responses=problem_responses(409, 422),
)
def create_price_book(data: PriceBookCreate, principal: Manager, session: Db) -> PriceBookRead:
    book = service.create_price_book(session, principal, data)
    session.commit()
    return PriceBookRead.model_validate(book)


@router.get(
    "/price-books/{book_id}", summary="Get one price book", responses=problem_responses(404)
)
def get_price_book(book_id: uuid.UUID, principal: Reader, session: Db) -> PriceBookRead:
    return PriceBookRead.model_validate(service.get_price_book(session, principal, book_id))


@router.patch(
    "/price-books/{book_id}",
    summary="Rename, (de)activate or make default (managers)",
    responses=problem_responses(404, 409, 422),
)
def update_price_book(
    book_id: uuid.UUID, data: PriceBookUpdate, principal: Manager, session: Db
) -> PriceBookRead:
    book = service.update_price_book(session, principal, book_id, data)
    session.commit()
    return PriceBookRead.model_validate(book)


@router.get(
    "/price-books/{book_id}/prices",
    summary="Prices in a price book",
    responses=problem_responses(404),
)
def list_prices(book_id: uuid.UUID, principal: Reader, session: Db) -> list[PriceRead]:
    return service.list_prices(session, principal, book_id)


@router.put(
    "/price-books/{book_id}/prices/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Set a product's price in a price book (managers; audited)",
    responses=problem_responses(404, 422),
)
def set_price(
    book_id: uuid.UUID, product_id: uuid.UUID, data: PriceSet, principal: Manager, session: Db
) -> Response:
    service.set_price(session, principal, book_id, product_id, data.unit_price)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/price-books/{book_id}/prices/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a product from a price book (managers; audited)",
    responses=problem_responses(404),
)
def remove_price(
    book_id: uuid.UUID, product_id: uuid.UUID, principal: Manager, session: Db
) -> Response:
    service.remove_price(session, principal, book_id, product_id)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
