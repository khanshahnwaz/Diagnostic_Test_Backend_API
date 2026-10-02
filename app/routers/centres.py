from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.deps import require_admin
from app.models import CentreTest, DiagnosticCentre, DiagnosticTest
from app.schemas import (
    CentreCreate,
    CentreOut,
    DiagnosticTestOut,
    OfferingCreate,
    OfferingOut,
    Page,
)

router = APIRouter(tags=["centres & tests"])


def get_centre_or_404(db: Session, centre_id: int) -> DiagnosticCentre:
    centre = db.scalar(
        select(DiagnosticCentre)
        .where(DiagnosticCentre.id == centre_id)
        .options(selectinload(DiagnosticCentre.offerings).selectinload(CentreTest.test))
    )
    if centre is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Centre not found")
    return centre


@router.get("/centres", response_model=Page[CentreOut])
def list_centres(
    location: str | None = Query(default=None, description="case-insensitive match on location"),
    test_id: int | None = Query(default=None, description="only centres offering this test"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = select(DiagnosticCentre)
    if location:
        query = query.where(func.lower(DiagnosticCentre.location) == location.strip().lower())
    if test_id is not None:
        query = query.where(
            DiagnosticCentre.id.in_(select(CentreTest.centre_id).where(CentreTest.test_id == test_id))
        )

    total = db.scalar(select(func.count()).select_from(query.subquery()))
    centres = db.scalars(
        query.options(selectinload(DiagnosticCentre.offerings).selectinload(CentreTest.test))
        .order_by(DiagnosticCentre.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return Page(items=centres, total=total, page=page, page_size=page_size)


@router.get("/centres/{centre_id}", response_model=CentreOut)
def get_centre(centre_id: int, db: Session = Depends(get_db)):
    return get_centre_or_404(db, centre_id)


@router.post(
    "/centres",
    response_model=CentreOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
def create_centre(data: CentreCreate, db: Session = Depends(get_db)):
    centre = DiagnosticCentre(name=data.name.strip(), location=data.location.strip(), address=data.address)
    db.add(centre)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Centre with this name already exists in that location")
    return get_centre_or_404(db, centre.id)


@router.post(
    "/centres/{centre_id}/tests",
    response_model=OfferingOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
def add_test_to_centre(centre_id: int, data: OfferingCreate, db: Session = Depends(get_db)):
    centre = get_centre_or_404(db, centre_id)
    name = data.name.strip()

    # reuse the test if some other centre already offers it
    test = db.scalar(select(DiagnosticTest).where(func.lower(DiagnosticTest.name) == name.lower()))
    if test is None:
        test = DiagnosticTest(name=name, description=data.description)
        db.add(test)
        db.flush()

    offering = db.scalar(
        select(CentreTest).where(CentreTest.centre_id == centre.id, CentreTest.test_id == test.id)
    )
    if offering is None:
        offering = CentreTest(centre_id=centre.id, test_id=test.id, price=data.price)
        db.add(offering)
    else:
        # already offered here, treat it as a price update
        offering.price = data.price

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Could not save test, please retry")
    db.refresh(offering)
    return offering


@router.get("/tests", response_model=Page[DiagnosticTestOut])
def list_tests(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    total = db.scalar(select(func.count()).select_from(DiagnosticTest))
    tests = db.scalars(
        select(DiagnosticTest).order_by(DiagnosticTest.id).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return Page(items=tests, total=total, page=page, page_size=page_size)
