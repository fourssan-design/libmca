from datetime import date
from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import Column, Date, Integer, String, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session, sessionmaker

# إعداد قاعدة البيانات المحلية (SQLite)
SQLALCHEMY_DATABASE_URL = "sqlite:///./library.db"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# جدول الكتب في قاعدة البيانات
class Book(Base):
  __tablename__ = "books"
  id = Column(Integer, primary_key=True, index=True)
  title = Column(String, index=True)
  author = Column(String, index=True)
  category = Column(String)
  total_copies = Column(Integer, default=1)


# جدول الحجوزات
class Reservation(Base):
  __tablename__ = "reservations"
  id = Column(Integer, primary_key=True, index=True)
  book_id = Column(Integer)
  user_name = Column(String)
  reservation_date = Column(Date)


Base.metadata.create_all(bind=engine)

app = FastAPI(title="نظام مكتبة دار الثقافة")
templates = Jinja2Templates(directory="templates")


def get_db():
  db = SessionLocal()
  try:
    yield db
  finally:
    db.close()


class ReservationCreate(BaseModel):
  book_id: int
  user_name: str
  reservation_date: date


@app.get("/", response_class=HTMLResponse)
def read_root(request: Request, db: Session = Depends(get_db)):
  books = db.query(Book).all()
  return templates.TemplateResponse(
      "index.html", {"request": request, "books": books}
  )


@app.get("/api/books")
def search_books(query: Optional[str] = None, db: Session = Depends(get_db)):
  if query:
    books = (
        db.query(Book)
        .filter(
            Book.title.contains(query)
            | Book.author.contains(query)
            | Book.category.contains(query)
        )
        .all()
    )
  else:
    books = db.query(Book).all()
  return books


@app.api_route("/api/reserve", methods=["POST"])
def reserve_book(reservation: ReservationCreate, db: Session = Depends(get_db)):
  book = db.query(Book).filter(Book.id == reservation.book_id).first()
  if not book:
    raise HTTPException(status_code=404, detail="الكتاب غير موجود")

  new_res = Reservation(
      book_id=reservation.book_id,
      user_name=reservation.user_name,
      reservation_date=reservation.reservation_date,
  )
  db.add(new_res)
  db.commit()
  db.refresh(new_res)
  return {
      "message": "تم حجز الكتاب بنجاح!",
      "reservation_id": new_res.id,
      "date": str(new_res.reservation_date),
  }
