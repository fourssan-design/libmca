import io
import os
from datetime import date
from typing import Optional
from fastapi import FastAPI, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates
import pandas as pd
from pydantic import BaseModel
from sqlalchemy import Column, Date, Integer, String, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session, sessionmaker

# 1. إعداد التطبيق
app = FastAPI(title="نظام مكتبة دار الثقافة - أدرار")
templates = Jinja2Templates(directory="templates")

# 2. إعداد قاعدة البيانات المحلية (SQLite)
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
  book_number = Column(String, index=True, nullable=True)
  title = Column(String, index=True)
  author = Column(String, index=True)
  category = Column(String, index=True)
  total_copies = Column(Integer, default=1)


# جدول الحجوزات
class Reservation(Base):
  __tablename__ = "reservations"
  id = Column(Integer, primary_key=True, index=True)
  book_id = Column(Integer)
  user_name = Column(String)
  reservation_date = Column(Date)


# إنشاء الجداول
Base.metadata.create_all(bind=engine)


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


# الصفحة الرئيسية لتصفح الكتب
@app.get("/", response_class=HTMLResponse)
def read_root(request: Request, db: Session = Depends(get_db)):
  books = db.query(Book).limit(50).all()
  return templates.TemplateResponse(request, "index.html", {"books": books})


# API للبحث عن الكتب
@app.get("/api/books")
def search_books(query: Optional[str] = None, db: Session = Depends(get_db)):
  if query:
    books = (
        db.query(Book)
        .filter(
            Book.title.contains(query)
            | Book.author.contains(query)
            | Book.category.contains(query)
            | Book.book_number.contains(query)
        )
        .all()
    )
  else:
    books = db.query(Book).limit(50).all()
  return books


# API لإحصائيات قاعدة البيانات
@app.get("/api/stats")
def get_database_stats(db: Session = Depends(get_db)):
  total_books = db.query(Book).count()
  categories = db.query(Book.category).distinct().all()
  cat_list = [c[0] for c in categories if c[0]]
  return {
      "total_books": total_books,
      "categories_count": len(cat_list),
      "categories": cat_list,
  }


# API لتنزيل ملف قاعدة البيانات
@app.api_route("/api/download-db", methods=["GET", "HEAD"])
def download_database():
  db_path = "library.db"
  if os.path.exists(db_path):
    return FileResponse(
        db_path, media_type="application/octet-stream", filename="library.db"
    )
  return {"error": "ملف قاعدة البيانات غير موجود بعد."}


# API لتسجيل حجز جديد
@app.post("/api/reserve")
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


# API استيراد الكتب من ملفات Excel مع حماية بكلمة السر
@app.post("/api/upload-excel")
def upload_excel(
    category_name: str = "تاريخ",
    admin_password: str = "",
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
  # التحقق من كلمة سر أمين المكتبة
  if admin_password != "admin123":
    raise HTTPException(
        status_code=403, detail="كلمة سر أمين المكتبة غير صحيحة!"
    )

  try:
    contents = file.file.read()
    df = pd.read_excel(io.BytesIO(contents), header=None)

    added_count = 0
    for index, row in df.iloc[2:].iterrows():
      b_num = (
          str(row.iloc[0]).strip()
          if pd.notna(row.iloc[0]) and str(row.iloc[0]) != "nan"
          else ""
      )
      title = (
          str(row.iloc[1]).strip()
          if pd.notna(row.iloc[1]) and str(row.iloc[1]) != "nan"
          else ""
      )
      author = (
          str(row.iloc[2]).strip()
          if pd.notna(row.iloc[2]) and str(row.iloc[2]) != "nan"
          else "غير معروف"
      )
      note = (
          str(row.iloc[3]).strip()
          if pd.notna(row.iloc[3]) and str(row.iloc[3]) != "nan"
          else ""
      )

      if title:
        full_title = f"{title} ({note})" if note else title
        book = Book(
            book_number=b_num,
            title=full_title,
            author=author,
            category=category_name,
            total_copies=1,
        )
        db.add(book)
        added_count += 1

    db.commit()
    return {
        "message": (
            f"تمت إضافة {added_count} كتاباً في تصنيف '{category_name}' بنجاح!"
        )
    }
  except Exception as e:
    return {"error": str(e)}
